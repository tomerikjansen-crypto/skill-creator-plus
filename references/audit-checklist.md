# Audit checklist

The single list of rules this skill enforces. AUDIT marks every rule pass, fail or not applicable, with evidence. NEW and REFINE run it before calling a skill done. How to write each part well is in authoring-guide.md. How to test is in testing.md.

## Contents
- How to mark a rule
- Frontmatter and naming (FM1 to FM5)
- Description (DS1 to DS4)
- Structure (ST1 to ST7)
- Content (CT1 to CT12)
- Workflows (WF1 to WF4)
- Scripts and packages (SC1 to SC5)
- Newer models (NM1 to NM5)
- Hooks (HK1)
- Testing (TS1 to TS3)
- Library checks (LB1, LB2)
- Failure modes to name
- Report format
- Sources

## How to mark a rule

- **Check: script.** Take the validator's result. Pass means no ERROR or WARN for that rule ID. A NOTE alone is a pass; mention it if it matters.
- **Check: script + read.** The validator flags candidates. Read each one in context and decide. A pattern match inside a quoted example is not a failure.
- **Check: read.** Judgment. Cite the file and line that shows the pass or the fail. "Looks fine" is not evidence.
- **Not applicable (N/A)** only when the rule cannot apply, for example SC1 to SC5 in a skill with no scripts. Say why in the evidence column.
- **Second reader.** For a skill in daily use or with consequences (it commits, moves files, routes work), start a fresh-context agent on the same checklist and the same files before you write your table, without showing it your findings. Why: the first audit of this skill's own library found that one reader marked style rules and missed every finding that changed behaviour; the fresh reader found them. Merge, and verify each of its fact findings on disk before it enters the report.
- **The validator's word patterns** cover English and the Norwegian cues used here. A DS2, DS3, NM4 or WF1 hit in another language, or a CT9 hit on a quoted word, is a candidate to read, not a fail.

Source codes: P = Anthropic's skill authoring best practices. CC = Claude Code skills docs. HK = Claude Code hooks docs. F5, O55, S55 = the prompting guides for Claude Fable 5, Opus 5.5 and Sonnet 5.5. ADV = advice from practice, not an Anthropic rule. Links are under Sources.

## Frontmatter and naming

- **FM1 Frontmatter parses.** The opening `---` is line 1 and the YAML parses. Why: Claude Code reads frontmatter only from line 1, and when the YAML fails it loads the skill with no fields, so the skill cannot trigger on its own. Check: script. Source: CC.
- **FM2 Valid name.** Lowercase letters, numbers and hyphens, at most 64 characters, no "anthropic" or "claude", same as the folder name. Check: script. Source: P.
- **FM3 Name says the activity.** A gerund (`processing-pdfs`) or a clear activity name (`pdf-processing`). Not vague (`helper`, `utils`, `tools`, `data`), and the same pattern as the rest of the library. Check: script + read. Source: P.
- **FM4 Only recognised fields.** Claude Code ignores unknown fields without an error. claude.ai uploads and the Skills API accept only `name`, `description`, `license`, `compatibility`, `metadata` and `allowed-tools`, and reject anything else. Check: script. Source: CC.
- **FM5 Invocation set on purpose.** `disable-model-invocation: true` for task skills with side effects that a person should start (deploy, send, pay). `user-invocable: false` for background knowledge. `paths` when the skill only matters for certain files. Why: each choice changes who can start the skill and what it costs in context. Check: read. Source: CC.

## Description

- **DS1 Present and within limits.** Not empty, at most 1,024 characters, no XML tags. Check: script. Source: P.
- **DS2 Third person.** "Processes Excel files", not "I can help you" or "You can use this". Why: the description is injected into the system prompt, and a mixed point of view causes discovery problems. Check: script + read. Source: P.
- **DS3 What and when, in the user's words.** Says what the skill does and when to use it, with the specific terms people type. Why: Claude picks from possibly 100+ skills using descriptions alone. Check: script (the "when" cue) + read (the words). The "when" part is N/A with `disable-model-invocation: true`, because Claude never sees that description. Source: P.
- **DS4 Key use case first.** The most important trigger comes first, and `description` plus `when_to_use` stays under 1,536 characters. Why: Claude Code cuts the combined text at that length in the skill listing. Check: script + read. Source: CC.

## Structure

- **ST1 SKILL.md body under 500 lines.** Check: script. Source: P.
- **ST2 Most important instructions near the top.** Why: after compaction, Claude Code re-attaches only the first 5,000 tokens of a skill. Check: script (flags long bodies) + read (is the top the part that matters most?). Source: CC.
- **ST3 Split by area, details on demand.** One reference file per domain or branch, advanced paths behind links, so a task loads only what it needs. Large reference files get `grep` hints. Check: read. Source: P.
- **ST4 One level deep.** Every reference file is linked straight from SKILL.md. Why: Claude may only preview a file it reaches through another file, for example with `head -100`. Check: script. Source: P.
- **ST5 Contents list on long files.** Any reference file over 100 lines starts with a contents list. Why: a partial read still shows the full scope. Check: script. Source: P.
- **ST6 Every file reachable and well named.** No dead links, no orphan files, no backups inside the skill, and names that say what a file holds (`form_validation_rules.md`, not `doc2.md`). Check: script + read. Source: P.
- **ST7 Forward slashes only.** `scripts/helper.py`, even on Windows. Why: backslash paths break on Mac and Linux. Check: script. Source: P.

## Content

- **CT1 Concise.** Only what Claude does not already know. Challenge every paragraph: does Claude need this, can I assume it knows this, does it justify its tokens? Check: read. Source: P.
- **CT2 Freedom matches risk.** Plain guidance where many approaches work, a template or parameterised script where one pattern is preferred, an exact script where a mistake is costly (money, deletion, publishing, migrations). Mix levels inside one skill. Test each step by asking "what if Claude does this differently?" If the answer is "nothing bad", loosen it. If it is "real damage", lock it down. Check: read. Source: P (the three levels), ADV (mixing and the test).
- **CT3 Nothing time-sensitive.** No rules like `before August 2025, use the old API`. Old ways go under an "Old patterns" heading. Check: script + read. Source: P.
- **CT4 One term per concept.** Always "field", never a mix of field, box and element. Check: read. Source: P.
- **CT5 Templates say how strict they are.** Strict ("use this exact structure") for data formats. Flexible ("a sensible default, adapt as needed") elsewhere. Check: read. Source: P.
- **CT6 Examples where style matters.** Input and output pairs, not a description of the style. Check: read. Source: P.
- **CT7 A default, not a menu.** One recommended approach plus one escape hatch for the exception. Check: read. Source: P.
- **CT8 MCP tools named in full.** `ServerName:tool_name`. Why: with several servers connected, a bare tool name may not be found. Check: read. Source: P.
- **CT9 Nothing unfinished.** No `TODO`, `FIXME` or scaffold placeholders. Check: script. Source: ADV.
- **CT10 One rule, one place.** No rule repeated across files. Fold new guidance into the rule it refines and delete what it replaces. Why: copies drift apart, and each repeat raises the cost of reading. Check: read. Source: ADV.
- **CT11 Facts hold in the environment.** Every path, tool name, file or frontmatter format the skill reads, command it runs and claim about how Claude Code or a plugin behaves is checked where the skill runs: the file exists (Glob, `stat`), the format is what the producing tool writes today (its installed references, not memory), the command passes the guards of the session type it names (a worktree session refuses loops and `$(...)`), and a status or return value means what the skill says it means (read the handler: `status: ok` with an id can still mean "existing item found, reminder not set"). Why: a skill audits clean as text and still routes work wrong when the thing it reads changed shape; the text rules above cannot see that. Check: read + verify on disk, one line of evidence per fact. Source: ADV.
- **CT12 Callers and callees checked.** The skill's behaviour is the skill plus what calls it and what it calls. List both (`grep` the skill name across skills, commands and agents; follow every "read X and follow it"), and check three things: the caller reaches this skill in every case it should (a caller that skips it when no project is active silently drops the code branch), a callee does not write or confirm on its own where this skill promises to do it later (double writes, approval given twice), and the entry Claude Code actually registers is the one you audited (a `commands/x.md` that reads `skills/x.md` is the skill; the file it reads is loaded by `Read` and is not re-attached after compaction). Why: in the first two audits of this library, every finding that changed real data lived at a boundary, not inside the file. Check: read callers and callees, cite file and line. Source: ADV.

## Workflows

- **WF1 Checklist with finish lines and a way back.** Multi-step tasks give Claude a checklist to copy and tick. Each step ends on a checkable "done when", and at least one line says where to go back ("If the check fails, return to Step 3"). Check: script (go-back line) + read. Source: P.
- **WF2 Feedback loop on quality-critical output.** Run the check, fix, repeat. The check can be a script or a style guide that Claude compares against. Check: read. Source: P.
- **WF3 Plan, validate, execute for risky jobs.** Batch, destructive or high-stakes work writes a plan file, checks it with a script, then runs it. Check: read. Source: P.
- **WF4 Standing instructions.** Guidance that applies all through a task is worded that way ("run the tests after each edit", not "run the tests"). Why: Claude Code loads the skill once and does not re-read the file on later turns. Check: read. Source: CC.

## Scripts and packages

All five are N/A when the skill has no scripts or code.

- **SC1 Solve, don't defer.** Scripts handle expected errors (missing file, no permission) instead of failing and leaving the mess to Claude. Check: read. Source: P.
- **SC2 No voodoo constants.** Each constant says why it has that value. Check: read. Source: P.
- **SC3 Run or read is explicit.** The skill says "run `x.py`" or "see `x.py` for the algorithm". Running is the default, because only the output costs tokens. Check: read. Source: P.
- **SC4 Errors that help.** Validation messages name the problem and the fix, for example "Field 'signature_date' not found. Available fields: ...". Check: read. Source: P.
- **SC5 Packages listed with install lines.** Each package has an install line (`pip install pypdf`) next to the code that needs it. Where it runs matters: Claude Code and claude.ai can install packages, the Claude API has no network access and no runtime installs. Check: script + read. Source: P.

## Newer models

Claude Fable 5, Opus 5.5 and Sonnet 5.5 follow instructions closely. Skills written for older models often over-steer them.

- **NM1 Not too prescriptive.** Look for instructions the model now handles well on its own: step-by-step hand-holding, long lists of behaviours, rules that restate common sense. Mark them as candidates to cut, then test before deleting (testing.md, "Test before you delete"). Why: skills built for prior models are often too prescriptive for newer ones and can make output worse. Check: read, then test. Source: F5, O55.
- **NM2 No reasoning echo.** No instruction to write out, show or transcribe the model's reasoning in the reply, for example `show your reasoning` or `think step by step and write it out`. A short explanation of the answer, or a summary of the actions taken, is fine. Why: these requests can be declined with the `reasoning_extraction` refusal, and server-side fallback does not retry it. Check: script + read. Source: F5, O55, S55.
- **NM3 The reason, not only the request.** Rules carry their reason. Claude can then apply the intent to cases the rule did not foresee, and a later editor can tell when the rule no longer applies. Check: read. Source: F5.
- **NM4 Brief steering.** A short instruction instead of an exhaustive list of each behaviour. Capitals (`CRITICAL`, `MUST`, `ALWAYS`, `NEVER`) only for real hard lines. Check: script (counts capitals) + read. Source: F5 (brief steering), ADV (capitals).
- **NM5 Verification made explicit.** Long or high-stakes work says how to check it, and prefers a fresh-context verifier (a subagent that did not do the work) over self-critique. Check: read. Source: F5.

## Hooks

- **HK1 A rule that has to hold on every run lives in a hook.** If a rule truly cannot bend (block a command, run a check before each edit), enforce it with a hook in the skill's frontmatter `hooks:` field instead of prose. Why: Claude Code runs a hook whenever its event fires, whether or not Claude is following the skill, and a skill's hooks stay registered for the rest of the session. Keep judgment calls in prose. Check: script (flags `must always` style wording when there are no hooks) + read. Source: CC, HK.

## Testing

- **TS1 Evaluations first.** At least three realistic prompts, written before the skill, with a baseline run without it. Check: read (are they in the skill folder or its repo?). Source: P.
- **TS2 Fresh-session test on real work.** A fresh Claude runs real tasks with the skill on and off, and someone watches which files it opens and what it skips. Why: leftover context from writing the skill hides gaps. Check: read (ask the user). Source: P, CC.
- **TS3 Tested on the models it will run on.** Haiku: enough guidance? Sonnet: clear and efficient? Opus: no over-explaining? Test prudently: run the full sweep for skills you rely on a lot or that have real consequences, and test the rest on the model you use most. Why: sweeping every skill across every model burns tokens for little gain. Check: read (ask the user). Source: P (the three questions), ADV (testing prudently).

## Library checks

Run these when auditing a folder of skills.

- **LB1 No overlapping descriptions.** Two skills should not claim the same trigger words. Merge them, or sharpen each description to its own job. Check: read (compare descriptions side by side). Source: ADV.
- **LB2 Unused skills turned off.** Every model-invoked description costs context on each turn. In Claude Code, `/skill-doctor` shows what each skill costs and how often it gets used. Check: read (ask the user to run it). Source: CC.

## Failure modes to name

Name the failure in the proposed change, so the user sees the pattern and not only the line. The names come from Matt Pocock's "writing-great-skills".

- **No-op:** a line the model already obeys by default (CT1, NM1). Delete the sentence.
- **Duplication:** one meaning in two places (CT10). Keep one.
- **Sediment:** stale layers kept because removing felt risky (CT3, CT10). Absorb into the principle above them.
- **Drift:** the environment moved and the skill did not: a renamed root, a format a tool stopped writing, a command a new guard refuses (CT11). Rewrite against what is there now.
- **Sprawl:** long even though every line is live (ST1, ST3). Move detail behind links, split by branch.
- **Premature completion:** steps end vaguely, so the agent rushes (WF1). Sharpen the "done when".

## Report format

Use this shape. Fails first, then N/A, then passes. For a folder of skills, start with the validator's `--all` table.

```markdown
# Skill audit: <skill-name>

Validator: <E> errors, <W> warnings, <N> notes. Checklist: <P> pass, <F> fail, <X> not applicable.

| Rule | Result | Evidence | Proposed change |
|---|---|---|---|
| DS2 Third person | Fail | SKILL.md:3 "I can help you with PDFs" | Rewrite as "Extracts text from PDFs ..." |
| SC1 Solve, don't defer | N/A | No scripts in the skill | - |
| ST4 One level deep | Pass | Validator: no ST4 findings | - |

## Changes, highest impact first
1. <change> - fixes <rule IDs> - <why it matters, one line>

## Needs your decision
- <anything that changes behaviour, or a deletion that needs a test first>

Nothing has been changed yet. Reply with the change numbers to apply.
```

## Sources

| Code | Page |
|---|---|
| P | https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices |
| CC | https://code.claude.com/docs/en/skills |
| HK | https://code.claude.com/docs/en/hooks#hooks-in-skills-and-agents |
| F5 | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5 |
| O55 | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5 |
| S55 | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5 |
