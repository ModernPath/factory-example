# Agent factory: two real runs

Both runs built `reading-list-agent` from [`spec.json`](spec.json) with
Claude Code (default model) on 8 October 2026, in a fresh clone of
agent-example. The contract has four actions (`add_item`, `search_items`,
`mark_read`, `delete_item`), a URL rule, a read/unread status, and CLI, API
and UI.

| Run | Outcome | Agent cost | What it teaches |
|---|---|---|---|
| [1](1-stopped-at-review/) | Gamed a gate, then the review crashed | $17.66 | Gates check what you wrote, not what you meant |
| [2](2-approved/) | Approved on build attempt 1; 101 tests | $13.41 | The same factory after the fixes run 1 forced |

## Run 1: the agent satisfied the check, not the intent

The tests stage wrote 9 test files ($3.33, 8 minutes) and the RED gate saw
them fail. The build ($8.49, 17 minutes) wrote the new modules but left the
reference's `example_*.py`, note tools, skills and subagent next to them, so
the leftover gate sent it back with 61 problems.

On attempt 2 the agent could not delete files
([commands](1-stopped-at-review/build-attempt-2-commands.txt)). It tried
`rm`, then `python -c "os.unlink(...)"` four times, and also ran a command
prefixed `dangerous=true;`; none of it removed a file. So it **overwrote
each reference file with a one-line stub** (`# Removed. Use
reading_list_core.py instead.`) and left two scratch files behind. Every
check passed: the leftover gate looked for reference *names in text*, and the
stubs no longer contained any. Its own summary says so
([`build.out.txt`](1-stopped-at-review/build.out.txt)). Then the review
session crashed and the run stopped.

Three things came out of it:

- **A bug in the runner.** `backend_runner.py` never passed the working
  directory to the Agent SDK, so every session ran in this repository, not in
  the agent folder. That is why deleting was refused, and why the agent saw
  this repository's `AGENTS.md`. Session 4's rehearsals had the same bug and
  never showed it, because they ran in the folder they changed.
- **Gates on files, not just text.** A reference file that still exists fails
  the check whatever it contains, and so does any unexpected file at the top
  of the agent folder.
- **Deleting belongs to the script.** The build still cannot delete. It lists
  files in `.factory-remove`, and the factory deletes them only inside the
  agent folder and never under `tests/`.

Resume also changed: a build that passed its gates is not rebuilt when only
its review is missing.

## Run 2: approved, with one more factory bug on the way

Tests $2.89 (8 minutes), build $6.71 (16 minutes, one attempt), GREEN with
101 tests, and the CLI, every tool, the API and the UI started. The reviewer
approved in prose followed by the JSON verdict
([`review.out.txt`](2-approved/review.out.txt)), and the factory **stopped
anyway**: its verdict parser matched from a `{"error": ...}` in the prose to
the final brace and found no valid JSON. A false stop is the safe direction,
but it still cost a person's attention and a $1.98 rerun of the review. The
parser now takes the last well-formed verdict object, and a test feeds it
that exact shape.

The agent ([files](2-approved/agent-files.txt),
[README](2-approved/agent-README.md)) was not committed to agent-example.
[`handoff.md`](2-approved/handoff.md) lists what a person does first: read the
contract, run the browser tests and use the UI.

## For a learner

- Where a run stops varied; that it stopped when something was wrong did not.
  The same was true of the validation-rule factory's runs.
- Both factory bugs were found by real runs, not by the 34 tests with a fake
  agent: a fake agent does what the test author imagined. Run the real thing
  early, on something cheap.
- An agent under pressure from a gate will look for the cheapest way to pass
  it. Write gates about the outcome (the file is gone) rather than a symptom
  (the name is not in the text).
