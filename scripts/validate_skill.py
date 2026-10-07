#!/usr/bin/env python3
"""Check a skill folder against Anthropic's skill-authoring rules.

Usage:
  python3 validate_skill.py <skill-folder> [--json] [--ban-em-dash]
  python3 validate_skill.py --all <folder-of-skills> [--json] [--ban-em-dash]

Each finding has a level:
  ERROR  breaks a rule; the skill may not load, trigger or read as intended
  WARN   likely problem; fix it or say why it stays
  NOTE   worth a look; often fine

Every finding carries a rule ID from references/audit-checklist.md, so an
audit report can quote the result rule by rule. Rules that need judgment
are not checked here; the checklist covers them.

--all checks every skill folder inside a folder and prints one summary table.
--json prints machine-readable results instead of text.
--ban-em-dash also flags the em dash character (a common AI-writing tell).

Exit codes: 0 = no errors (warnings and notes allowed), 1 = at least one
error, 2 = the check could not run (bad path or arguments).

Standard library only, Python 3.8 or newer. Run it; there is no need to
read it.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

# ---------------------------------------------------------------------------
# Limits. Each one says where it comes from.
# ---------------------------------------------------------------------------

# Anthropic best-practices page: the name field allows at most 64 characters.
NAME_MAX = 64
# Anthropic best-practices page: the description field allows at most 1,024 characters.
DESC_MAX = 1024
# Claude Code skills page: description plus when_to_use is cut at 1,536 characters
# in the skill listing that Claude reads when it picks a skill.
LISTING_MAX = 1536
# Anthropic best-practices page: keep the SKILL.md body under 500 lines.
BODY_MAX_LINES = 500
# Anthropic best-practices page: reference files longer than 100 lines need a
# contents list at the top.
TOC_MIN_LINES = 100
# Where the contents list must start. Claude may preview a file with a partial
# read such as head -100, so the list has to begin well inside that window.
TOC_SEARCH_LINES = 50
# Claude Code skills page: after compaction only the first 5,000 tokens of a skill stay.
COMPACT_KEEP_TOKENS = 5000
# Rough average for English text. Good enough to say which line the cut falls near.
CHARS_PER_TOKEN = 4
# Descriptions shorter than this are almost always vague ("Helps with documents" is 20).
DESC_MIN_CHARS = 50
# A few capitalised words mark a real hard line. Past this many per file they stop
# standing out, and a rule that truly must hold every time belongs in a hook.
SHOUT_MAX = 5
# Claude Code skills page: compatibility accepts up to 500 characters.
COMPAT_MAX = 500
# Files bigger than this are data, not instructions; scanning them only slows the check.
MAX_TEXT_BYTES = 2_000_000
# Line numbers printed per finding. More than this is noise; the count shows the rest.
MAX_LINES_SHOWN = 6
# Files listed per grouped finding (orphans, backups). The count shows the rest.
MAX_FILES_SHOWN = 8

# Claude Code skills page, frontmatter reference: every field Claude Code reads.
CLAUDE_CODE_FIELDS = {
    "name", "description", "when_to_use", "argument-hint", "arguments",
    "disable-model-invocation", "user-invocable", "allowed-tools", "disallowed-tools",
    "model", "effort", "context", "agent", "background", "hooks", "paths", "shell",
    "metadata", "license", "compatibility",
}
# Claude Code skills page: the only fields claude.ai uploads and the Skills API accept.
PORTABLE_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
BOOL_FIELDS = {"disable-model-invocation", "user-invocable", "background"}
BOOL_WORDS = {"true": True, "yes": True, "on": True, "1": True,
              "false": False, "no": False, "off": False, "0": False}
EFFORT_VALUES = {"low", "medium", "high", "xhigh", "max"}
SHELL_VALUES = {"bash", "powershell"}
# Anthropic best-practices page: reserved words that may not appear in a name.
RESERVED_WORDS = ("anthropic", "claude")
# Anthropic best-practices page: vague and overly generic names to avoid.
VAGUE_NAMES = {"helper", "helpers", "utils", "utilities", "tools", "documents", "docs",
               "data", "files", "misc", "stuff", "general", "common"}
VAGUE_NAME_PARTS = {"helper", "helpers", "utils", "util", "misc", "stuff"}
VAGUE_FILE_RE = re.compile(r"^(doc|docs|file|files|misc|stuff|temp|tmp|untitled|new|notes?|other)\d*$", re.I)

# Files that belong to a repository, not to the instructions Claude reads.
REPO_FILE_RE = re.compile(
    r"^(readme|changelog|license|licence|contributing|code_of_conduct|security|notice|authors)(\.[a-z]+)?$", re.I)
MANIFEST_FILES = {"requirements.txt", "requirements-dev.txt", "package.json", "package-lock.json",
                  "pyproject.toml", "setup.py", "setup.cfg", "pnpm-lock.yaml", "yarn.lock"}
# Folders that never hold instructions. evals/ is where Anthropic's skill-creator keeps test cases.
SKIP_DIRS = {"node_modules", "__pycache__", "evals", "venv", ".venv"}
TEXT_EXTS = {".md", ".txt", ".py", ".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".sh", ".bash",
             ".ps1", ".bat", ".cmd", ".json", ".yaml", ".yml", ".html", ".htm", ".css", ".xml",
             ".csv", ".toml", ".ini", ".cfg", ".svg", ".jsx", ".tsx", ".rb", ".go", ".rs", ".java"}
PY_EXTS = {".py"}
JS_EXTS = {".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".jsx", ".tsx"}
BACKUP_RE = re.compile(r"\.(?:bak|orig|old|backup)(?:$|[._-])|~$|[._-]backup\b|\bbackup[._-]", re.I)

RULE_ORDER = ["FM1", "FM2", "FM3", "FM4", "FM5", "DS1", "DS2", "DS3", "DS4",
              "ST1", "ST2", "ST4", "ST5", "ST6", "ST7", "CT3", "CT9", "WF1",
              "SC5", "NM2", "NM4", "HK1", "STYLE"]
MECHANICAL_RULES = [r for r in RULE_ORDER if r != "STYLE"]
LEVEL_ORDER = {"ERROR": 0, "WARN": 1, "NOTE": 2}

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

FIRST_PERSON_RE = re.compile(
    r"(?<![\w'])(?:I|[Ww]e)\s+(?:can|will|help|am|could|would)\b"
    r"|(?<![\w'])(?:I'm|I'll|I've|[Ww]e'll|[Ww]e're)(?![\w'])"
    r"|\b[Jj]eg (?:kan|vil|hjelper)\b|\b[Vv]i (?:kan|vil|hjelper)\b")
SECOND_PERSON_RE = re.compile(
    r"\byou\s+(?:can|could|will|should|may|might)\b|\byou'll\b"
    r"|\bdu (?:kan|vil|bør|skal)\b", re.I)
# English cues first, then the Norwegian ones skills in this library use
# ("Bruk når", "Brukes ved", "Aktiveres med /x", "når brukeren").
WHEN_CUE_RE = re.compile(
    r"\buse (?:it |this |this skill |them )?(?:when|whenever|for|if|on|to)\b"
    r"|\bwhen (?:the |a )?(?:user|users|you|someone|asked|working|dealing|handling|editing"
    r"|reviewing|creating|writing|building)\b"
    r"|\bwhenever\b|\btrigger(?:s|ed)? (?:on|when|by|for)\b|\binvoke[sd]? (?:when|for|on)\b"
    r"|\bactivates? (?:when|for|on)\b|\bfor (?:requests|questions|tasks) (?:about|like|involving|that)\b"
    r"|\bbruk(?:es)? (?:den |denne |skillen )?(?:når|ved|for|hvis|til)\b"
    r"|\bnår (?:brukeren|du|noen|det)\b|\baktiveres? (?:ved|når|med|av)\b"
    r"|\b(?:utløses|trigges) (?:av|ved|på)\b|\bved (?:spørsmål|«|\"|/)",
    re.I)
XML_TAG_RE = re.compile(r"<\s*/?\s*[A-Za-z][\w:-]*(?:\s[^<>]*)?/?>")
MONTHS = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
          r"|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
TIME_PHRASE_RE = re.compile(
    r"\b(?:before|after|until|since|as of|by|starting|prior to|beginning)\s+(?:early |mid-?|late )?"
    r"(?:" + MONTHS + r"\.?\s+)?(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?(?:19|20)\d{2}\b"
    r"|\b(?:as of (?:today|now|this writing)|at the time of writing|this year|next year|last year"
    r"|the latest (?:version|model|release)|new in (?:19|20)\d{2})\b",
    re.I)
ISO_DATE_RE = re.compile(r"\b(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b")
REASONING_ECHO_RE = re.compile(
    r"\bshow (?:me )?your (?:reasoning|thinking|thought process|chain[- ]of[- ]thought)\b"
    r"|\bexplain your (?:reasoning|thinking|thought process) (?:in|step|before|first|fully|at length)\b"
    r"|\b(?:write|spell|lay|print|type) out your (?:reasoning|thinking|thought process|chain[- ]of[- ]thought)\b"
    r"|\bthink step[- ]by[- ]step,? (?:and|then) (?:write|show|explain|output|include|list|print)\b"
    r"|\b(?:include|output|print|reproduce|echo|transcribe|narrate|reveal) your (?:internal |full |hidden )?"
    r"(?:reasoning|thinking|thought process|chain[- ]of[- ]thought)\b"
    r"|\bthink (?:out loud|aloud)\b"
    r"|<(?:thinking|reasoning|scratchpad|inner_monologue)>",
    re.I)
SHOUT_RE = re.compile(r"\b(?:CRITICAL|MUST|ALWAYS|NEVER|KRITISK|ALDRI|ALLTID|IKKE|OBLIGATORISK)\b")
HOOK_HINT_RE = re.compile(
    r"\b(?:must always|every (?:single )?time|without exception|no exceptions|before every|after every)\b",
    re.I)
GO_BACK_RE = re.compile(
    r"\b(?:return|go back|loop back|jump back|back) to (?:step|stage|phase)\b"
    r"|\brepeat (?:from|until|steps?)\b|\bstart again from\b"
    r"|\btilbake til (?:steg|trinn|fase|punkt)\b|\bgjenta (?:fra|steg|trinn)\b"
    r"|\bstart (?:på nytt|om igjen) fra\b|\bkjør (?:\S+\s+){0,3}på nytt\b", re.I)
CHECKBOX_RE = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s")
TODO_RE = re.compile(r"\b(?:TODO|FIXME)\b")
# A quoted or guillemet-wrapped TODO is a word the skill talks about (a checklist
# item such as 'no "TODO" left in the output'), not unfinished text.
QUOTED_WORD_RE = re.compile('"[^"\\n]{1,40}"|\'[^\'\\n]{1,40}\'|«[^»\\n]{1,40}»|' + chr(0x201C)
                            + "[^" + chr(0x201D) + "\\n]{1,40}" + chr(0x201D))


def unfinished(text):
    """True when TODO/FIXME appears outside quotes."""
    return bool(TODO_RE.search(QUOTED_WORD_RE.sub(" ", text)))
TODO_COMMENT_RE = re.compile(r"(?:#|//|/\*|<!--)\s*(?:TODO|FIXME)\b")
PLACEHOLDER_RE = re.compile(r"\[FILL:")
WIN_PATH_RE = re.compile(
    r"(?<![\w\\])[A-Za-z]:\\(?=[\w .-])"
    r"|(?<![\w\\/])[\w.-]+(?:\\(?![_*])[\w.-]+)+\.[A-Za-z0-9]{1,5}\b")
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*([\w+-]*)")
INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^)]*[\"'])?\s*\)")
REF_LINK_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)")
LINK_TARGET_RE = re.compile(r"\]\([^)]*\)")
PATHISH_RE = re.compile(r"[\w.${}/~-]*[\w-]\.[A-Za-z0-9]{1,8}\b")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
TOC_RE = re.compile(r"^\s{0,3}(?:#{1,6}\s*)?(?:\*\*)?(?:table of )?contents(?:\*\*)?\s*:?\s*$", re.I)
OLD_SECTION_RE = re.compile(r"^(?:old patterns?|legacy|history|changelog|deprecated)\b", re.I)
KEY_RE = re.compile(r"^([A-Za-z0-9_][\w.-]*)[ \t]*:(?:[ \t]+(.*?))?[ \t]*$")

# Python imports whose pip package has a different name.
PY_PACKAGE_NAMES = {
    "yaml": "pyyaml", "PIL": "pillow", "cv2": "opencv-python", "bs4": "beautifulsoup4",
    "docx": "python-docx", "pptx": "python-pptx", "fitz": "pymupdf", "sklearn": "scikit-learn",
    "skimage": "scikit-image", "dateutil": "python-dateutil", "dotenv": "python-dotenv",
    "win32com": "pywin32", "win32api": "pywin32", "Crypto": "pycryptodome", "jwt": "pyjwt",
    "magic": "python-magic", "serial": "pyserial", "attr": "attrs", "OpenSSL": "pyopenssl",
    "googleapiclient": "google-api-python-client", "Levenshtein": "python-levenshtein",
}
NODE_BUILTINS = {
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console", "constants", "crypto",
    "dgram", "diagnostics_channel", "dns", "domain", "events", "fs", "http", "http2", "https",
    "inspector", "module", "net", "os", "path", "perf_hooks", "process", "punycode", "querystring",
    "readline", "repl", "stream", "string_decoder", "sys", "timers", "tls", "trace_events", "tty",
    "url", "util", "v8", "vm", "wasi", "worker_threads", "zlib", "test",
}
# Fallback for Python 3.8 and 3.9, which lack sys.stdlib_module_names.
STDLIB_FALLBACK = {
    "__future__", "abc", "argparse", "array", "ast", "asyncio", "base64", "binascii", "bisect",
    "builtins", "bz2", "calendar", "cgi", "cmath", "codecs", "collections", "colorsys", "concurrent",
    "configparser", "contextlib", "copy", "csv", "ctypes", "curses", "dataclasses", "datetime",
    "dbm", "decimal", "difflib", "dis", "email", "encodings", "enum", "errno", "faulthandler",
    "fcntl", "filecmp", "fileinput", "fnmatch", "fractions", "ftplib", "functools", "gc", "getopt",
    "getpass", "gettext", "glob", "gzip", "hashlib", "heapq", "hmac", "html", "http", "imaplib",
    "importlib", "inspect", "io", "ipaddress", "itertools", "json", "keyword", "linecache",
    "locale", "logging", "lzma", "mailbox", "math", "mimetypes", "mmap", "msvcrt", "multiprocessing",
    "netrc", "numbers", "operator", "optparse", "os", "pathlib", "pdb", "pickle", "pkgutil",
    "platform", "plistlib", "poplib", "posixpath", "pprint", "profile", "pstats", "pty", "queue",
    "quopri", "random", "re", "readline", "reprlib", "resource", "sched", "secrets", "select",
    "selectors", "shelve", "shlex", "shutil", "signal", "site", "smtplib", "socket", "socketserver",
    "sqlite3", "ssl", "stat", "statistics", "string", "stringprep", "struct", "subprocess", "sys",
    "sysconfig", "tarfile", "tempfile", "termios", "textwrap", "threading", "time", "timeit",
    "tkinter", "token", "tokenize", "traceback", "tracemalloc", "tty", "turtle", "types", "typing",
    "unicodedata", "unittest", "urllib", "uuid", "venv", "warnings", "wave", "weakref", "webbrowser",
    "winreg", "winsound", "wsgiref", "xml", "xmlrpc", "zipfile", "zipimport", "zlib", "zoneinfo",
}
STDLIB = set(getattr(sys, "stdlib_module_names", ())) or STDLIB_FALLBACK

DQ_ESCAPES = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v",
              "f": "\f", "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\",
              "N": "\x85", "_": "\xa0", "L": chr(0x2028), "P": chr(0x2029)}
# Characters named by code point so the source stays plain ASCII.
EM_DASH = chr(0x2014)
BOM = chr(0xFEFF)
# Straight and curly double-quoted spans; quoted trigger phrases are skipped by the
# third-person check.
QUOTED_SPAN_RE = re.compile('"[^"]*"|' + chr(0x201C) + "[^" + chr(0x201D) + "]*" + chr(0x201D))


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

class Report:
    """Findings for one skill folder."""

    def __init__(self, root, label):
        self.root = root
        self.label = label
        self.name = None
        self.findings = []

    def add(self, level, rule, file, lines, message):
        self.findings.append({
            "level": level, "rule": rule, "file": file,
            "lines": sorted({n for n in (lines or []) if n}), "message": message,
        })

    def count(self, level):
        return sum(1 for f in self.findings if f["level"] == level)

    def sorted_findings(self):
        def key(f):
            rule_rank = RULE_ORDER.index(f["rule"]) if f["rule"] in RULE_ORDER else 99
            return (LEVEL_ORDER[f["level"]], rule_rank, f["file"], f["lines"][:1])
        return sorted(self.findings, key=key)

    def passed_rules(self):
        flagged = {f["rule"] for f in self.findings if f["level"] in ("ERROR", "WARN")}
        return [r for r in MECHANICAL_RULES if r not in flagged]


def short(text, limit=70):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def posix(path):
    return str(path).replace("\\", "/")


def indent_of(line):
    return len(line) - len(line.lstrip(" "))


# ---------------------------------------------------------------------------
# Frontmatter: a small YAML reader for the subset skills use. It reports the
# same mistakes that make a real YAML parser reject the block, because Claude
# Code then loads the skill with no fields set.
# ---------------------------------------------------------------------------

def fold(parts):
    out = ""
    for p in parts:
        if p == "\n":
            out = out.rstrip(" ") + "\n"
            continue
        if out and not out.endswith("\n"):
            out += " "
        out += p
    return out.strip()


def typed(key, text, line, quoted=False):
    if not quoted:
        low = text.strip().lower()
        if key in BOOL_FIELDS and low in BOOL_WORDS:
            return {"kind": "bool", "value": BOOL_WORDS[low], "line": line}
        if low in ("", "null", "~"):
            return {"kind": "null", "value": None, "line": line}
    return {"kind": "str", "value": text, "line": line}


def strip_quotes(text):
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    return t


def split_top_level(inner):
    items, depth, quote, buf = [], 0, None, ""
    for ch in inner:
        if quote:
            buf += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            items.append(buf)
            buf = ""
            continue
        buf += ch
    if buf.strip():
        items.append(buf)
    return [strip_quotes(i) for i in items if i.strip()]


def parse_plain(key, value, line, cont, problems):
    segments = [(line, value)] + [(n, t.strip()) for n, t in cont]
    parts = []
    for n, seg in segments:
        if not seg:
            parts.append("\n")
            continue
        comment = re.search(r"[ \t]#", seg)
        if comment:
            problems.append(("WARN", n, "'%s': text after ' #' is read as a YAML comment and dropped. "
                             "Wrap the value in double quotes to keep it." % key))
            seg = seg[: comment.start()].rstrip()
        if ": " in seg or seg.endswith(":"):
            problems.append(("ERROR", n, "'%s' has an unquoted ': ' (or ends with ':'), which YAML reads as "
                             "a new key, so the frontmatter will not parse. Wrap the value in double quotes."
                             % key))
        parts.append(seg)
        if comment:
            break
    return typed(key, fold(parts), line)


def parse_quoted(key, value, line, cont, problems, quote):
    segments = [(line, value)] + [(n, t.strip()) for n, t in cont]
    src, starts = "", []
    for i, (n, seg) in enumerate(segments):
        if i:
            src += "\n" if not seg else " "
        starts.append((len(src), n))
        src += seg

    def line_at(pos):
        found = line
        for start, n in starts:
            if start <= pos:
                found = n
        return found

    out, i = [], 1
    while i < len(src):
        ch = src[i]
        if quote == '"' and ch == "\\":
            nxt = src[i + 1] if i + 1 < len(src) else ""
            if nxt in DQ_ESCAPES:
                out.append(DQ_ESCAPES[nxt])
                i += 2
                continue
            width = {"x": 2, "u": 4, "U": 8}.get(nxt)
            if width and re.fullmatch(r"[0-9A-Fa-f]{%d}" % width, src[i + 2: i + 2 + width]):
                try:
                    out.append(chr(int(src[i + 2: i + 2 + width], 16)))
                except ValueError:
                    pass
                i += 2 + width
                continue
            problems.append(("ERROR", line_at(i), "'%s': '\\%s' is not a valid escape inside double quotes "
                             "(Windows paths cause this), so the frontmatter will not parse. Use forward "
                             "slashes or single quotes." % (key, nxt)))
            out.append(nxt)
            i += 2
            continue
        if ch == quote:
            if quote == "'" and src[i + 1: i + 2] == "'":
                out.append("'")
                i += 2
                continue
            rest = src[i + 1:].strip()
            if rest and not rest.startswith("#"):
                problems.append(("ERROR", line_at(i), "'%s' has text after its closing quote, so the "
                                 "frontmatter will not parse. Put the whole value inside the quotes." % key))
            return typed(key, "".join(out), line, quoted=True)
        out.append(ch)
        i += 1
    problems.append(("ERROR", line, "'%s' opens a quote that never closes, so the frontmatter will not parse."
                     % key))
    return {"kind": "str", "value": "".join(out), "line": line}


def parse_flow(key, value, line, cont, problems):
    src = fold([value] + [t.strip() for _, t in cont])
    opener = src[0]
    depth, quote, end = 0, None, None
    for i, ch in enumerate(src):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                end = i
                break
    kind = "list" if opener == "[" else "map"
    if end is None:
        problems.append(("ERROR", line, "'%s' opens '%s' but never closes it, so the frontmatter will not "
                         "parse. Wrap the value in double quotes." % (key, opener)))
        return {"kind": "str", "value": src, "line": line}
    rest = src[end + 1:].strip()
    if rest and not rest.startswith("#"):
        problems.append(("ERROR", line, "'%s' starts with '%s', so YAML reads it as a %s, and the text after "
                         "the closing bracket breaks the frontmatter. Wrap the whole value in double quotes."
                         % (key, opener, kind)))
        return {"kind": "str", "value": src, "line": line}
    if kind == "list":
        return {"kind": "list", "value": split_top_level(src[1:end]), "line": line}
    return {"kind": "map", "value": src, "line": line}


def parse_block_scalar(key, value, line, cont, problems):
    header = re.match(r"^([|>])([1-9]?)([+-]?)([1-9]?)\s*(#.*)?$", value)
    if not header:
        problems.append(("ERROR", line, "'%s' has a block marker ('|' or '>') followed by other text, so the "
                         "frontmatter will not parse." % key))
        return {"kind": "str", "value": value, "line": line}
    style = header.group(1)
    explicit = header.group(2) or header.group(4)
    body = [(n, t) for n, t in cont]
    nonblank = [t for _, t in body if t.strip()]
    if not nonblank:
        return {"kind": "str", "value": "", "line": line}
    ind = int(explicit) if explicit else indent_of(nonblank[0])
    for n, t in body:
        if t.strip() and indent_of(t) < ind:
            problems.append(("ERROR", n, "'%s': a line inside the block value is indented less than the "
                             "first line, so the frontmatter will not parse." % key))
            break
    rows = [t[ind:] if t.strip() else "" for _, t in body]
    if style == "|":
        text = "\n".join(rows)
    else:
        text = fold([r.strip() if r.strip() else "\n" for r in rows])
    return {"kind": "str", "value": text.strip("\n"), "line": line}


def parse_value(key, value, line, cont, problems):
    v = value.strip()
    if not v:
        body = [(n, t) for n, t in cont if t.strip()]
        if not body:
            return {"kind": "null", "value": None, "line": line}
        first = body[0][1].strip()
        if first.startswith("- ") or first == "-":
            base = min(indent_of(t) for _, t in body)
            items = [strip_quotes(t.strip()[1:]) for _, t in body
                     if indent_of(t) == base and t.strip().startswith("-")]
            return {"kind": "list", "value": items, "line": line}
        if re.match(r"^[\w.-]+[ \t]*:(?:[ \t]|$)", first):
            return {"kind": "map", "value": "\n".join(t for _, t in cont), "line": line}
        # The value starts on the next line, for example a quoted description.
        start = next(i for i, (_, t) in enumerate(cont) if t.strip())
        first_line, first_text = cont[start]
        return parse_value(key, first_text.strip(), first_line, cont[start + 1:], problems)
    c = v[0]
    if c in "|>":
        return parse_block_scalar(key, v, line, cont, problems)
    if c in "\"'":
        return parse_quoted(key, v, line, cont, problems, c)
    if c in "[{":
        return parse_flow(key, v, line, cont, problems)
    if c in "@`%":
        problems.append(("ERROR", line, "'%s' starts with '%s', which YAML reserves, so the frontmatter will "
                         "not parse. Wrap the value in double quotes." % (key, c)))
    elif c in "&*!":
        problems.append(("WARN", line, "'%s' starts with '%s', which YAML reads as an anchor, alias or tag. "
                         "Wrap the value in double quotes." % (key, c)))
    elif v.startswith("- ") or v == "-":
        problems.append(("ERROR", line, "'%s' starts with '- ', which YAML reads as a list item in the wrong "
                         "place, so the frontmatter will not parse. Wrap the value in double quotes." % key))
    elif c == "#":
        problems.append(("WARN", line, "'%s' starts with '#', so YAML reads the value as a comment and the "
                         "field is empty. Wrap the value in double quotes." % key))
        return {"kind": "null", "value": None, "line": line}
    return parse_plain(key, v, line, cont, problems)


def parse_frontmatter(lines):
    """Return (fields, problems, body_start). problems: (level, line, message)."""
    problems, fields = [], {}
    if not lines:
        problems.append(("ERROR", 1, "SKILL.md is empty."))
        return fields, problems, 0
    first = lines[0]
    if first.startswith(BOM):
        problems.append(("WARN", 1, "SKILL.md starts with a byte-order mark. Some loaders then miss the "
                         "frontmatter. Save the file as UTF-8 without a BOM."))
        first = first[1:]
    if first.strip() != "---":
        later = any(l.strip() == "---" for l in lines[1:40])
        where = "a --- line appears further down, but " if later else ""
        problems.append(("ERROR", 1, "frontmatter must start on line 1: %sClaude Code reads it only when the "
                         "opening --- is the first line, so this skill has no name or description." % where))
        return fields, problems, 0
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() in ("---", "...")), None)
    if end is None:
        problems.append(("ERROR", 1, "frontmatter has no closing --- line."))
        return fields, problems, 0
    block = lines[1:end]
    seen, i = {}, 0
    while i < len(block):
        raw = block[i]
        n = i + 2
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        lead = raw[: len(raw) - len(raw.lstrip())]
        if "\t" in lead:
            problems.append(("ERROR", n, "a tab is used for indentation; YAML allows spaces only, so the "
                             "frontmatter will not parse."))
        if lead:
            problems.append(("ERROR", n, "an indented line has no key above it, so the frontmatter will not "
                             "parse."))
            i += 1
            continue
        m = KEY_RE.match(raw)
        if not m:
            problems.append(("ERROR", n, "this line is not 'key: value' (a space must follow the colon), so "
                             "the frontmatter will not parse."))
            i += 1
            continue
        key, value = m.group(1), m.group(2) or ""
        j, cont = i + 1, []
        while j < len(block):
            nxt = block[j]
            if not nxt.strip() or nxt[0] in " \t" or (not value.strip() and nxt.startswith("-")):
                cont.append((j + 2, nxt))
                j += 1
            else:
                break
        while cont and not cont[-1][1].strip():
            cont.pop()
        tabbed = [cn for cn, ct in cont if ct.strip() and "\t" in ct[: len(ct) - len(ct.lstrip())]]
        if tabbed:
            problems.append(("ERROR", tabbed[0], "a tab is used for indentation; YAML allows spaces only, so "
                             "the frontmatter will not parse."))
        if key in seen:
            problems.append(("WARN", n, "duplicate key '%s' (first on line %d). Most YAML parsers keep the "
                             "last value; some reject the file." % (key, seen[key])))
        seen[key] = n
        fields[key] = parse_value(key, value, n, cont, problems)
        i = j
    return fields, problems, end + 1


# ---------------------------------------------------------------------------
# Reading files
# ---------------------------------------------------------------------------

def read_text(path):
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def is_repo_file(path):
    return bool(REPO_FILE_RE.match(path.name))


def collect_files(root):
    """Every file that belongs to this skill. Sub-folders with their own SKILL.md are separate skills."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        keep = []
        for d in sorted(dirnames):
            if d.startswith(".") or d in SKIP_DIRS:
                continue
            if (here / d / "SKILL.md").is_file():
                continue
            keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            if f.startswith(".") or f.endswith(".pyc"):
                continue
            files.append(here / f)
    return files


def make_views(lines, skip_until=0):
    """Three views of a Markdown file with the same line count:
    full = as written; no_inline = inline code removed (fenced code kept);
    prose = inline code and fenced code removed. Lines before skip_until are blanked
    in no_inline and prose (used for the SKILL.md frontmatter)."""
    no_inline, prose = [], []
    fence = None
    for idx, line in enumerate(lines):
        if idx < skip_until:
            no_inline.append("")
            prose.append("")
            continue
        if fence:
            no_inline.append(line)
            prose.append("")
            stripped = line.strip()
            if stripped and set(stripped) == {fence[0]} and len(stripped) >= len(fence):
                fence = None
            continue
        m = FENCE_RE.match(line)
        if m:
            fence = m.group(1)
            no_inline.append(line)
            prose.append("")
            continue
        cleaned = INLINE_CODE_RE.sub("", line)
        no_inline.append(cleaned)
        prose.append(cleaned)
    return no_inline, prose


def old_section_mask(prose):
    """True for lines under an 'Old patterns' style heading or inside <details> blocks."""
    mask, level, details = [], None, 0
    for line in prose:
        h = HEADING_RE.match(line)
        if h:
            lvl = len(h.group(1))
            if level is not None and lvl <= level:
                level = None
            if OLD_SECTION_RE.match(h.group(2).strip()):
                level = lvl
        if re.search(r"<details\b", line, re.I):
            details += 1
        mask.append(level is not None or details > 0)
        if re.search(r"</details>", line, re.I):
            details = max(0, details - 1)
    return mask


def links_in(prose):
    found = []
    for n, line in enumerate(prose, 1):
        for m in LINK_RE.finditer(line):
            found.append((n, m.group(1)))
        m = REF_LINK_RE.match(line)
        if m:
            found.append((n, m.group(1)))
    return found


def local_target(raw):
    t = raw.strip()
    if t.startswith("#") or t.startswith("mailto:"):
        return None
    if re.match(r"^[a-z][a-z0-9+.-]*:", t, re.I) and not re.match(r"^[a-z]:[\\/]", t, re.I):
        return None
    t = t.split("#")[0].split("?")[0]
    t = t.replace("${CLAUDE_SKILL_DIR}/", "")
    return unquote(t) or None


def resolve(base_file, target):
    p = Path(target).expanduser()
    if not p.is_absolute():
        p = base_file.parent / p
    try:
        return p.resolve()
    except OSError:
        return p


def inside(root, path):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def lines_text(lines):
    shown = lines[:MAX_LINES_SHOWN]
    text = ",".join(str(n) for n in shown)
    if len(lines) > MAX_LINES_SHOWN:
        text += " (+%d more)" % (len(lines) - MAX_LINES_SHOWN)
    return text


def files_text(names):
    shown = ", ".join(names[:MAX_FILES_SHOWN])
    if len(names) > MAX_FILES_SHOWN:
        shown += " (+%d more)" % (len(names) - MAX_FILES_SHOWN)
    return shown


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def name_problems(name, folder_name=None):
    """(level, rule, message) problems with a skill name. Shared with init_skill.py."""
    out = []
    if not re.fullmatch(r"[a-z0-9-]+", name):
        out.append(("ERROR", "FM2", "name '%s' may use only lowercase letters, numbers and hyphens." % name))
    if len(name) > NAME_MAX:
        out.append(("ERROR", "FM2", "name is %d characters; the limit is %d." % (len(name), NAME_MAX)))
    for word in RESERVED_WORDS:
        if word in name.lower():
            out.append(("ERROR", "FM2", "name '%s' contains the reserved word '%s'. Anthropic does not allow "
                        "'anthropic' or 'claude' in a skill name." % (name, word)))
    if re.fullmatch(r"[a-z0-9-]+", name) and (name.startswith("-") or name.endswith("-") or "--" in name):
        out.append(("NOTE", "FM2", "name starts or ends with a hyphen, or has two in a row. Use single "
                    "hyphens between words."))
    if folder_name and name != folder_name:
        out.append(("WARN", "FM2", "name '%s' differs from the folder name '%s'. Keep them the same so the "
                    "folder, the slash command and the name all match." % (name, folder_name)))
    parts = [p for p in re.split(r"[-_\s]+", name.lower()) if p]
    vague = [p for p in parts if p in VAGUE_NAME_PARTS]
    if name.lower() in VAGUE_NAMES or vague:
        word = vague[0] if vague else name.lower()
        out.append(("WARN", "FM3", "name '%s' is vague ('%s'). Name the activity instead, for example "
                    "processing-pdfs or pdf-processing." % (name, word)))
    return out


def check_frontmatter(rep, folder_name, fields):
    def val(key):
        f = fields.get(key)
        return f["value"] if f else None

    def line(key):
        f = fields.get(key)
        return [f["line"]] if f else []

    # FM2 / FM3: name
    name_field = fields.get("name")
    if not name_field or name_field["kind"] == "null":
        rep.add("ERROR", "FM2", "SKILL.md", [], "frontmatter has no name. Anthropic's page requires one; "
                "claude.ai and the Skills API reject a skill without it (Claude Code falls back to the "
                "folder name).")
    elif name_field["kind"] != "str":
        rep.add("ERROR", "FM2", "SKILL.md", line("name"), "name must be plain text.")
    else:
        name = str(name_field["value"]).strip()
        rep.name = name
        for level, rule, msg in name_problems(name, folder_name):
            rep.add(level, rule, "SKILL.md", line("name"), msg)

    # FM4: known and portable fields, valid values
    unknown = [k for k in fields if k not in CLAUDE_CODE_FIELDS]
    non_portable = [k for k in fields if k in CLAUDE_CODE_FIELDS and k not in PORTABLE_FIELDS]
    if unknown:
        rep.add("NOTE", "FM4", "SKILL.md", [fields[k]["line"] for k in unknown],
                "Claude Code ignores unknown fields without an error: %s. Move them under metadata: to "
                "keep them." % ", ".join(unknown))
    if non_portable or unknown:
        rep.add("NOTE", "FM4", "SKILL.md", [], "claude.ai uploads and the Skills API accept only name, "
                "description, license, compatibility, metadata and allowed-tools; any other field makes the "
                "upload fail. This skill also uses: %s. Fine for Claude Code only."
                % ", ".join(non_portable + unknown))
    effort = val("effort")
    if effort is not None and str(effort).strip().lower() not in EFFORT_VALUES:
        rep.add("WARN", "FM4", "SKILL.md", line("effort"), "effort '%s' is not one of low, medium, high, "
                "xhigh, max." % effort)
    context = val("context")
    if context is not None and str(context).strip() != "fork":
        rep.add("WARN", "FM4", "SKILL.md", line("context"), "context accepts only 'fork' (or leave it out).")
    shell = val("shell")
    if shell is not None and str(shell).strip().lower() not in SHELL_VALUES:
        rep.add("WARN", "FM4", "SKILL.md", line("shell"), "shell accepts only bash or powershell.")
    compat = val("compatibility")
    if isinstance(compat, str) and len(compat) > COMPAT_MAX:
        rep.add("WARN", "FM4", "SKILL.md", line("compatibility"), "compatibility is %d characters; the limit "
                "is %d." % (len(compat), COMPAT_MAX))
    for key in BOOL_FIELDS:
        f = fields.get(key)
        if f and f["kind"] not in ("bool", "null"):
            rep.add("WARN", "FM4", "SKILL.md", line(key), "%s should be true or false (unquoted)." % key)

    # FM5: invocation settings that cancel each other out
    manual_only = val("disable-model-invocation") is True
    if manual_only and val("user-invocable") is False:
        rep.add("WARN", "FM5", "SKILL.md", line("user-invocable"), "disable-model-invocation: true and "
                "user-invocable: false together mean nobody can invoke this skill.")

    # DS1-DS4: description
    desc_field = fields.get("description")
    desc = ""
    if not desc_field or desc_field["kind"] == "null" or (desc_field["kind"] == "str"
                                                         and not str(desc_field["value"]).strip()):
        rep.add("ERROR", "DS1", "SKILL.md", [], "frontmatter has no description. Claude picks skills by "
                "their description, so without one this skill cannot trigger on its own.")
    elif desc_field["kind"] != "str":
        rep.add("ERROR", "DS1", "SKILL.md", line("description"), "description must be plain text, not a "
                "list or a map.")
    else:
        desc = str(desc_field["value"]).strip()
        dl = line("description")
        if len(desc) > DESC_MAX:
            rep.add("ERROR", "DS1", "SKILL.md", dl, "description is %d characters; the limit is %d."
                    % (len(desc), DESC_MAX))
        tag = XML_TAG_RE.search(desc)
        if tag:
            rep.add("ERROR", "DS1", "SKILL.md", dl, "description contains an XML tag (%s); Anthropic does not "
                    "allow them." % short(tag.group(0), 30))
        unquoted = QUOTED_SPAN_RE.sub(" ", desc)
        person = FIRST_PERSON_RE.search(unquoted) or SECOND_PERSON_RE.search(unquoted)
        if person:
            rep.add("WARN", "DS2", "SKILL.md", dl, "description is not in third person (found \"%s\"). It is "
                    "injected into the system prompt; write \"Processes Excel files\", not \"I can help\" or "
                    "\"You can use this\"." % person.group(0))
        if len(desc) < DESC_MIN_CHARS:
            rep.add("WARN", "DS3", "SKILL.md", dl, "description is only %d characters, which is usually too "
                    "vague to pick from many skills. Say what it does and when to use it, with specific key "
                    "words." % len(desc))
        when = val("when_to_use")
        when_text = when if isinstance(when, str) else ""
        if not manual_only and not WHEN_CUE_RE.search(desc + " " + when_text):
            rep.add("WARN", "DS3", "SKILL.md", dl, "description says what the skill does but not when to use "
                    "it. Add a \"Use when ...\" clause with the words people actually type.")
        combined = len(desc) + (len(when_text) + 1 if when_text else 0)
        if combined > LISTING_MAX:
            rep.add("WARN", "DS4", "SKILL.md", dl, "description plus when_to_use is %d characters. Claude Code "
                    "cuts this text at %s characters in the skill listing, so the rest is never seen when "
                    "Claude picks a skill. Put the key use case first and trim." % (combined, "{:,}".format(
                        LISTING_MAX)))
        if PLACEHOLDER_RE.search(desc):
            rep.add("WARN", "CT9", "SKILL.md", dl, "description still holds a [FILL: ...] placeholder from the "
                    "scaffold. Replace it before sharing.")
        if unfinished(desc):
            rep.add("ERROR", "CT9", "SKILL.md", dl, "description contains TODO or FIXME.")
    return manual_only


def python_imports(text, line_offset=0):
    """Yield (line, top-level module, optional) for absolute imports."""
    rows = text.splitlines()
    for i, row in enumerate(rows):
        m = re.match(r"^(\s*)from\s+(\.*)([A-Za-z_][\w.]*)\s+import\b", row)
        if m:
            if m.group(2):
                continue
            ind, mods = len(m.group(1)), [m.group(3)]
        else:
            m = re.match(r"^(\s*)import\s+([A-Za-z_][\w.]*(?:\s+as\s+\w+)?(?:\s*,\s*[A-Za-z_][\w.]*"
                         r"(?:\s+as\s+\w+)?)*)\s*(?:#.*)?$", row)
            if not m:
                continue
            ind = len(m.group(1))
            mods = [p.strip().split()[0] for p in m.group(2).split(",")]
        optional = ind > 0 and inside_try(rows, i, ind)
        for mod in mods:
            yield i + 1 + line_offset, mod.split(".")[0], optional


def inside_try(rows, i, ind):
    for j in range(i - 1, max(-1, i - 12), -1):
        s = rows[j]
        if not s.strip() or s.lstrip().startswith("#"):
            continue
        if indent_of(s) < ind:
            t = s.strip()
            return t.startswith(("try:", "except", "if TYPE_CHECKING"))
    return False


def js_imports(text):
    for i, row in enumerate(text.splitlines()):
        for m in re.finditer(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)|^\s*import\s+(?:[^'\"]*?\s+from\s+)?"
                             r"['\"]([^'\"]+)['\"]|import\(\s*['\"]([^'\"]+)['\"]\s*\)", row):
            spec = m.group(1) or m.group(2) or m.group(3)
            if not spec or spec.startswith((".", "/", "node:", "bun:", "http:", "https:")):
                continue
            parts = spec.split("/")
            pkg = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
            if pkg in NODE_BUILTINS:
                continue
            yield i + 1, pkg


def has_install_line(names, corpus, manifests):
    for name in names:
        n = re.escape(name)
        if re.search(r"(?:pip3?|pipx|uv(?: pip)?|python3? -m pip|py -m pip|poetry|conda|npm|pnpm|yarn|bun)"
                     r"\s+(?:install|add|i)\b[^\n]*?(?<![\w-])" + n + r"(?![\w-])", corpus, re.I):
            return True
        if re.search(r"(?im)^\s*" + n + r"\s*(?:[<>=!~;\[]|$)", manifests):
            return True
        if re.search(r"\"" + n + r"\"\s*:", manifests):
            return True
    return False


def check_skill_body(rep, root, skill_md, lines, body_start):
    body = lines[body_start:]
    body_lines = len(body)
    if body_lines > BODY_MAX_LINES:
        rep.add("WARN", "ST1", "SKILL.md", [], "SKILL.md body is %d lines. Keep it under %d and move detail into "
                "reference files that SKILL.md links." % (body_lines, BODY_MAX_LINES))
    budget = COMPACT_KEEP_TOKENS * CHARS_PER_TOKEN
    chars, cut_line = 0, None
    for idx, row in enumerate(body):
        chars += len(row) + 1
        if chars > budget and cut_line is None:
            cut_line = body_start + idx + 1
    if cut_line:
        rep.add("NOTE", "ST2", "SKILL.md", [cut_line], "SKILL.md body is about {:,} tokens. After compaction "
                "Claude Code keeps only the first {:,} tokens of a skill, which ends near line {}. Keep the "
                "rules that matter most above that line.".format(chars // CHARS_PER_TOKEN,
                                                                 COMPACT_KEEP_TOKENS, cut_line))


def validate(root, label, ban_em_dash=False):
    root = Path(root)
    try:
        root = root.resolve()
    except OSError:
        pass
    rep = Report(root, label)
    try:
        names = os.listdir(root)
    except OSError:
        rep.add("ERROR", "FM1", "SKILL.md", [], "cannot read the folder %s." % posix(label))
        return rep
    skill_name = "SKILL.md" if "SKILL.md" in names else next((n for n in names if n.lower() == "skill.md"), None)
    if not skill_name:
        rep.add("ERROR", "FM1", "SKILL.md", [], "no SKILL.md in this folder. A skill is a folder with a "
                "SKILL.md file at its top level.")
        return rep
    if skill_name != "SKILL.md":
        rep.add("ERROR", "FM1", skill_name, [], "the file is named '%s'. Name it SKILL.md exactly; "
                "case-sensitive systems will not find it." % skill_name)
    skill_md = root / skill_name
    text = read_text(skill_md) or ""
    lines = text.splitlines()

    fields, problems, body_start = parse_frontmatter(lines)
    for level, n, msg in problems:
        rep.add(level, "FM1", "SKILL.md", [n], msg)
    manual_only = check_frontmatter(rep, root.name, fields)
    has_hooks = "hooks" in fields and fields["hooks"]["kind"] != "null"
    check_skill_body(rep, root, skill_md, lines, body_start)

    files = collect_files(root)
    rel = {f: f.relative_to(root).as_posix() for f in files}

    # Read every text file once.
    docs, texts = {}, {}
    for f in files:
        if f.suffix.lower() not in TEXT_EXTS and f.name not in MANIFEST_FILES:
            continue
        t = read_text(f)
        if t is None:
            continue
        texts[f] = t
        if f.suffix.lower() == ".md" and not is_repo_file(f) and not BACKUP_RE.search(f.name):
            rows = t.splitlines()
            skip = body_start if f == skill_md else 0
            no_inline, prose = make_views(rows, skip)
            docs[f] = {"full": rows, "no_inline": no_inline, "prose": prose}

    # Mentions: which file names and paths each text file names, for reachability.
    mentions = {}
    for f, t in texts.items():
        if is_repo_file(f):
            continue
        tokens = set()
        for tok in PATHISH_RE.findall(t):
            tok = tok.replace("${CLAUDE_SKILL_DIR}/", "").lstrip("./")
            tokens.add(tok)
            tokens.add(tok.rsplit("/", 1)[-1])
        for m in re.finditer(r"^\s*(?:from|import)\s+\.?([A-Za-z_]\w*)", t, re.M):
            tokens.add(m.group(1) + ".py")
        for m in re.finditer(r"(?:require\(|from\s+|import\()\s*['\"]\.{1,2}/([^'\"]+)['\"]", t):
            spec = m.group(1)
            tokens.add(spec)
            tokens.add(spec.rsplit("/", 1)[-1])
            for ext in (".js", ".mjs", ".cjs", ".ts"):
                tokens.add(spec.rsplit("/", 1)[-1] + ext)
        mentions[f] = tokens
    skill_mentions = mentions.get(skill_md, set())

    def mentioned_by(f, by):
        toks = mentions.get(by, set())
        return rel[f] in toks or f.name in toks

    # Links from SKILL.md
    skill_links = set()
    if skill_md in docs:
        for n, raw in links_in(docs[skill_md]["prose"]):
            t = local_target(raw)
            if t:
                skill_links.add(resolve(skill_md, t))

    def from_skill_md(f):
        return f.resolve() in skill_links or mentioned_by(f, skill_md)

    md_refs = [f for f in docs if f != skill_md]
    md_ref_set = {f.resolve() for f in md_refs}

    # ST4 / ST6: links in every Markdown file
    dead, outside, linked_from_refs, nested = [], [], set(), {}
    for f, d in docs.items():
        cross = []
        for n, raw in links_in(d["prose"]):
            t = local_target(raw)
            if not t:
                continue
            target = resolve(f, t)
            if not target.exists():
                dead.append((f, n, t))
                continue
            if not inside(root, target):
                outside.append((f, n, t))
                continue
            if f == skill_md or target not in md_ref_set or target == f.resolve():
                continue
            linked_from_refs.add(target)
            tgt_file = next(x for x in md_refs if x.resolve() == target)
            if from_skill_md(tgt_file):
                cross.append((n, rel[tgt_file]))
            else:
                nested.setdefault(tgt_file, []).append((f, n))
        if cross:
            names_ = sorted({c[1] for c in cross})
            rep.add("NOTE", "ST4", rel[f], [c[0] for c in cross], "links to other reference files (%s). "
                    "SKILL.md links them too, so this is not deep nesting, but chains invite partial reads. "
                    "Prefer pointing from SKILL.md." % files_text(names_))
    for tgt_file, sources in sorted(nested.items(), key=lambda kv: rel[kv[0]]):
        first_src = sources[0][0]
        via = files_text(["%s:%d" % (rel[s], n) for s, n in sources])
        rep.add("ERROR", "ST4", rel[first_src], [n for s, n in sources if s == first_src],
                "%s is reached only through other reference files (%s), never from SKILL.md. Claude may only "
                "preview files it reaches that way (for example with head -100). Link it from SKILL.md, or "
                "fold its content into the file that needs it." % (rel[tgt_file], via))
    for f, n, t in dead:
        rep.add("ERROR", "ST6", rel[f], [n], "link target does not exist: %s." % short(t, 60))
    if outside:
        rep.add("NOTE", "ST6", rel[outside[0][0]], [o[1] for o in outside if o[0] == outside[0][0]],
                "%d link(s) point outside the skill folder (%s). They break when the skill is copied, zipped "
                "or shared." % (len(outside), files_text(sorted({short(o[2], 40) for o in outside}))))

    # ST6: orphans, vague names, backups
    orphan_md = [f for f in md_refs if not from_skill_md(f) and f.resolve() not in linked_from_refs]
    for f in orphan_md:
        rep.add("WARN", "ST6", rel[f], [], "%s is never linked from SKILL.md, so Claude has no reason to open "
                "it. Link it from SKILL.md with a line on when to read it, or delete it." % rel[f])
    others = [f for f in files if f != skill_md and f.suffix.lower() != ".md" and not is_repo_file(f)
              and f.name not in MANIFEST_FILES and not BACKUP_RE.search(f.name)]
    orphans = [rel[f] for f in others if not any(mentioned_by(f, by) for by in mentions if by != f)]
    if orphans:
        rep.add("WARN", "ST6", "SKILL.md", [], "%d bundled file(s) are never mentioned by any file in the "
                "skill: %s. Mention each where it is used, or delete it." % (len(orphans), files_text(orphans)))
    vague = [rel[f] for f in files if VAGUE_FILE_RE.match(f.stem) and not is_repo_file(f)]
    if vague:
        rep.add("NOTE", "ST6", "SKILL.md", [], "vague file names: %s. Name files for what they hold, for "
                "example form_validation_rules.md, not doc2.md." % files_text(vague))
    backups = [rel[f] for f in files if BACKUP_RE.search(f.name)]
    if backups:
        rep.add("WARN", "ST6", "SKILL.md", [], "backup or old copies sit inside the skill: %s. Keep backups "
                "outside the skill folder so they never load or get shared." % files_text(backups))

    # Per-document scans
    checkbox_files, go_back_found, hook_hits = [], False, []
    for f, d in docs.items():
        r = rel[f]
        full, no_inline, prose = d["full"], d["no_inline"], d["prose"]
        if f != skill_md and len(full) > TOC_MIN_LINES:
            if not any(TOC_RE.match(x) for x in prose[:TOC_SEARCH_LINES]):
                rep.add("ERROR", "ST5", r, [], "%s is %d lines with no contents list in its first %d lines. Add "
                        "a '## Contents' list at the top so a partial read still shows everything the file "
                        "covers." % (r, len(full), TOC_SEARCH_LINES))
        win = [(n, m.group(0)) for n, x in enumerate(full, 1) for m in [WIN_PATH_RE.search(x)] if m]
        if win:
            rep.add("ERROR", "ST7", r, [w[0] for w in win], "backslash in a path (%s). Use forward slashes; "
                    "backslash paths fail on Mac and Linux." % short(win[0][1], 40))
        mask = old_section_mask(prose)
        dated_text = [LINK_TARGET_RE.sub("", x) if not mask[i] else "" for i, x in enumerate(prose)]
        times = [(n, m.group(0)) for n, x in enumerate(dated_text, 1) for m in [TIME_PHRASE_RE.search(x)] if m]
        if times:
            rep.add("WARN", "CT3", r, [t[0] for t in times], "time-sensitive wording (\"%s\"). It goes stale "
                    "silently. State the current way; move old ways under an '## Old patterns' heading."
                    % short(times[0][1], 40))
        dates = [(n, m.group(0)) for n, x in enumerate(dated_text, 1) for m in [ISO_DATE_RE.search(x)] if m]
        if dates:
            rep.add("NOTE", "CT3", r, [t[0] for t in dates], "%d dated marker(s) such as %s. If a date stands in "
                    "for a rule's reason, write the reason instead; dates can sit in an '## Old patterns' "
                    "section." % (len(dates), dates[0][1]))
        todos = [n for n, x in enumerate(prose, 1) if unfinished(x)]
        if todos:
            rep.add("ERROR", "CT9", r, todos, "TODO or FIXME left in the skill. Finish or delete it before "
                    "sharing.")
        fills = [n for n, x in enumerate(no_inline, 1) if PLACEHOLDER_RE.search(x)]
        if fills:
            rep.add("WARN", "CT9", r, fills, "%d unfilled [FILL: ...] placeholder(s) from the scaffold. Replace "
                    "each one before sharing." % len(fills))
        echo = [(n, m.group(0)) for n, x in enumerate(no_inline, 1) for m in [REASONING_ECHO_RE.search(x)] if m]
        if echo:
            rep.add("WARN", "NM2", r, [e[0] for e in echo], "asks Claude to write out its reasoning (\"%s\"). "
                    "Newer models (Claude Fable 5, Opus 5.5, Sonnet 5.5) may decline this with the "
                    "reasoning_extraction refusal. Ask for the answer, or a short explanation of it, instead."
                    % short(echo[0][1], 40))
        shouts = [n for n, x in enumerate(prose, 1) for _ in SHOUT_RE.findall(x)]
        if len(shouts) > SHOUT_MAX:
            rep.add("WARN", "NM4", r, sorted(set(shouts)), "%d capitalised CRITICAL, MUST, ALWAYS or NEVER. "
                    "Newer models follow brief, plain instructions, and capitals stop standing out when they "
                    "are everywhere. Keep them for true hard lines and give the reason." % len(shouts))
        hook_hits += [(r, n, m.group(0)) for n, x in enumerate(prose, 1) for m in [HOOK_HINT_RE.search(x)] if m]
        if sum(1 for x in no_inline if CHECKBOX_RE.match(x)) >= 3:
            checkbox_files.append(r)
        if any(GO_BACK_RE.search(x) for x in no_inline):
            go_back_found = True
        if ban_em_dash:
            dashes = [n for n, x in enumerate(full, 1) if EM_DASH in x]
            if dashes:
                rep.add("WARN", "STYLE", r, dashes, "%d line(s) with an em dash. Use ' - ' or a comma."
                        % len(dashes))

    if hook_hits and not has_hooks:
        first = hook_hits[0]
        rep.add("NOTE", "HK1", first[0], [h[1] for h in hook_hits if h[0] == first[0]], "words like \"%s\" mark "
                "a rule that must hold every time, and the frontmatter has no hooks. Prose can be skipped or "
                "cut by compaction; if the rule truly must hold, enforce it with a hook (frontmatter hooks:)."
                % first[2].lower())
    if checkbox_files and not go_back_found:
        rep.add("NOTE", "WF1", checkbox_files[0], [], "has a checklist but no go-back line anywhere in the "
                "skill. Add one such as 'If the check fails, return to Step 2' so Claude loops instead of "
                "pushing on.")

    # Scripts: TODO comments and packages (SC5)
    corpus = "\n".join(t for f, t in texts.items() if f.name not in MANIFEST_FILES)
    manifests = "\n".join(t for f, t in texts.items() if f.name in MANIFEST_FILES)
    local_modules = {f.stem for f in files if f.suffix.lower() in PY_EXTS}
    local_modules |= {f.parent.name for f in files if f.name == "__init__.py"}
    missing, needed = {}, set()

    def note_dep(module, display, where, n, tool):
        needed.add(display)
        names = {module, display, display.lower(), display.replace("_", "-"), display.replace("-", "_")}
        if not has_install_line(names, corpus, manifests):
            missing.setdefault(display, (where, n, tool))

    for f, t in texts.items():
        suffix = f.suffix.lower()
        if suffix in PY_EXTS or suffix in JS_EXTS or suffix in {".sh", ".ps1", ".bash"}:
            todo_rows = [n for n, x in enumerate(t.splitlines(), 1) if TODO_COMMENT_RE.search(x)]
            if todo_rows:
                rep.add("ERROR", "CT9", rel[f], todo_rows, "TODO or FIXME comment left in a script. Finish or "
                        "delete it before sharing.")
        if suffix in PY_EXTS:
            for n, mod, optional in python_imports(t):
                if optional or mod in STDLIB or mod in local_modules or mod == "__future__":
                    continue
                note_dep(mod, PY_PACKAGE_NAMES.get(mod, mod), rel[f], n, "pip install")
        elif suffix in JS_EXTS:
            for n, pkg in js_imports(t):
                note_dep(pkg, pkg, rel[f], n, "npm install")
    for f, d in docs.items():
        full = "\n".join(d["full"])
        for m in re.finditer(r"^\s{0,3}(?:```|~~~)\s*(?:python|py|python3)\s*\n(.*?)^\s{0,3}(?:```|~~~)",
                             full, re.M | re.S):
            offset = full[: m.start(1)].count("\n")
            for n, mod, optional in python_imports(m.group(1), offset):
                if optional or mod in STDLIB or mod in local_modules:
                    continue
                note_dep(mod, PY_PACKAGE_NAMES.get(mod, mod), rel[f], n, "pip install")
    for display, (file_part, line_no, tool) in sorted(missing.items()):
        rep.add("WARN", "SC5", file_part, [line_no], "%s needs the package '%s' but no install line was found "
                "anywhere in the skill. Add '%s %s' next to the script or code that needs it."
                % (file_part, display, tool, display))
    if needed:
        rep.add("NOTE", "SC5", "SKILL.md", [], "this skill needs packages outside the standard library (%s). "
                "Claude Code and claude.ai can install them; the Claude API has no network access and no "
                "runtime installs, so there they must already be available." % files_text(sorted(needed)))
    return rep


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def counts_line(rep):
    e, w, n = rep.count("ERROR"), rep.count("WARN"), rep.count("NOTE")

    def plural(k, word):
        return "%d %s%s" % (k, word, "" if k == 1 else "s")
    return "%s, %s, %s" % (plural(e, "error"), plural(w, "warning"), plural(n, "note"))


def print_report(rep):
    name = " (name: %s)" % rep.name if rep.name else ""
    print("Skill: %s%s" % (posix(rep.label), name))
    print()
    findings = rep.sorted_findings()
    if not findings:
        print("No findings.")
    for f in findings:
        where = f["file"] + (":" + lines_text(f["lines"]) if f["lines"] else "")
        print("%-5s  %-5s  %s  %s" % (f["level"], f["rule"], where, f["message"]))
    print()
    print("Passed (no errors or warnings): %s" % " ".join(rep.passed_rules()))
    verdict = "fix the errors first." if rep.count("ERROR") else "no errors."
    print("Result: %s - %s" % (counts_line(rep), verdict))
    print("Rule IDs match references/audit-checklist.md. Judgment rules are not checked by this script.")


def print_table(reports, folder):
    rows = []
    for rep in sorted(reports, key=lambda r: (-r.count("ERROR"), -r.count("WARN"), r.label)):
        top = []
        for f in rep.sorted_findings():
            if f["level"] in ("ERROR", "WARN") and f["rule"] not in top:
                top.append(f["rule"])
        rows.append((Path(rep.label).name, str(rep.count("ERROR")), str(rep.count("WARN")),
                     str(rep.count("NOTE")), " ".join(top[:4]) or "-"))
    head = ("Skill", "Errors", "Warnings", "Notes", "Rules with errors or warnings")
    widths = [max(len(head[i]), *(len(r[i]) for r in rows)) if rows else len(head[i]) for i in range(5)]
    print("Skills in %s" % posix(folder))
    print()
    fmt = "%-{0}s  %{1}s  %{2}s  %{3}s  %s".format(*widths[:4])
    print(fmt % head)
    print(fmt % tuple("-" * w for w in widths))
    for r in rows:
        print(fmt % r)
    with_errors = sum(1 for r in reports if r.count("ERROR"))
    warn_only = sum(1 for r in reports if not r.count("ERROR") and r.count("WARN"))
    clean = len(reports) - with_errors - warn_only
    print()
    print("%d skill%s: %d with errors, %d with warnings only, %d with no errors or warnings."
          % (len(reports), "" if len(reports) == 1 else "s", with_errors, warn_only, clean))
    print("Run the script on one skill folder to see its findings.")


def as_json(reports):
    return {
        "skills": [{
            "path": posix(r.label), "name": r.name,
            "counts": {"error": r.count("ERROR"), "warn": r.count("WARN"), "note": r.count("NOTE")},
            "passed": r.passed_rules(), "findings": r.sorted_findings(),
        } for r in reports],
        "totals": {
            "skills": len(reports),
            "error": sum(r.count("ERROR") for r in reports),
            "warn": sum(r.count("WARN") for r in reports),
            "note": sum(r.count("NOTE") for r in reports),
        },
    }


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(
        description="Check a skill folder against Anthropic's skill-authoring rules.",
        epilog="Exit codes: 0 no errors, 1 errors found, 2 could not run.")
    parser.add_argument("path", nargs="?", help="a skill folder (the folder that holds SKILL.md)")
    parser.add_argument("--all", metavar="FOLDER", help="check every skill folder inside FOLDER")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--ban-em-dash", action="store_true", help="also flag the em dash character")
    args = parser.parse_args(argv)

    if bool(args.path) == bool(args.all):
        parser.print_usage()
        print("Give either one skill folder or --all FOLDER.")
        return 2
    if args.all:
        folder = Path(args.all).expanduser()
        if not folder.is_dir():
            print("Not a folder: %s" % posix(args.all))
            return 2
        skills = sorted(p for p in folder.iterdir()
                        if p.is_dir() and not p.name.startswith(".") and (p / "SKILL.md").is_file())
        if not skills:
            print("No skill folders (folders holding SKILL.md) inside %s" % posix(args.all))
            return 2
        reports = [validate(p, posix(Path(args.all) / p.name), args.ban_em_dash) for p in skills]
        if args.json:
            print(json.dumps(as_json(reports), indent=2))
        else:
            print_table(reports, args.all)
        return 1 if any(r.count("ERROR") for r in reports) else 0

    folder = Path(args.path).expanduser()
    if not folder.is_dir():
        if folder.name.lower() == "skill.md" and folder.is_file():
            folder = folder.parent
        else:
            print("Not a folder: %s" % posix(args.path))
            return 2
    label = posix(args.path).rstrip("/") or posix(args.path)
    if label.lower().endswith("skill.md"):
        label = label[: -len("skill.md")].rstrip("/") or "."
    rep = validate(folder, label, args.ban_em_dash)
    if args.json:
        print(json.dumps(as_json([rep]), indent=2))
    else:
        print_report(rep)
    return 1 if rep.count("ERROR") else 0


if __name__ == "__main__":
    sys.exit(main())
