# Rehearsals: factory concepts in four small scripts

Warm-ups before building `factory/`. Each script isolates one idea from the
course's software-factory slides, using the agent CLI you already pay for (no
API key). They come from the ModernPath live training's session 4 and were
adapted for this repository.

| Script | Idea | Slide |
|---|---|---|
| `01_minimal_factory.py` | A factory is a policy around an agent run: prompt template, allowed tools, turn limit | m09-01 |
| `02_factory_catalog.py` | Same agent, different role policy (analyzer, planner, fixer), different behaviour | m09-02 |
| `03_resumable_factory.py` | Session state saved outside the conversation, so work resumes | m09-03 |
| `04_spec_loop_factory.py` | A spec loop: implement → machine checks → review, until approved or out of iterations | m09-05 |

`factory/run.sh` is where these ideas meet the course's project work: narrow
stages, gates in the script, a stop report and a draft PR.

## Setup

The Claude backend uses the Agent SDK, which needs Python 3.10 or later:

```bash
uv venv --python 3.12 .venv-rehearsals
source .venv-rehearsals/bin/activate
uv pip install -r rehearsals/requirements.txt pytest
claude --version   # or: codex --version, opencode --version
```

## Run

From the repository root. Scripts 01–03 only read unless you ask the fixer
to change something. Script 04 edits `app/`, so give it a branch of its own:

```bash
python rehearsals/01_minimal_factory.py --backend claude "Summarize this repository in five bullets"
python rehearsals/02_factory_catalog.py analyzer --backend claude "Which validation rules does app/tasks.py enforce?"
python rehearsals/02_factory_catalog.py planner --backend codex "Plan adding a rule that rejects due dates in the past"
python rehearsals/03_resumable_factory.py start --backend claude "Read app/tasks.py and remember its rule ids"
python rehearsals/03_resumable_factory.py resume --backend claude "Which rule id would a new title rule get?"

git switch -c rehearsal/spec-loop
python rehearsals/04_spec_loop_factory.py --backend claude --spec rehearsals/spec.example.json
git switch main   # inspect the branch, then delete it
```

## What each backend really enforces

The same options do not mean the same thing everywhere, so check before you
rely on a limit:

| Option | claude | codex | opencode |
|---|---|---|---|
| `allowed_tools` | enforced | ignored | ignored |
| `permission_mode` | enforced | mapped to `--sandbox read-only` / `workspace-write` | ignored |
| `max_turns` | enforced | ignored | ignored |
| timeout | enforced by the script | enforced by the script | enforced by the script |

This is why `factory/run.sh` never relies on the agent for its gates: the
script checks files, diffs and test results itself.

## Two differences from `factory/run.sh` worth noticing

- **The review verdict.** Script 04 looks for the text `FINAL_STATUS:
  APPROVED` anywhere in the review. A reply that says "I would not write
  FINAL_STATUS: APPROVED" passes. `run.sh` requires a JSON verdict and stops
  on anything else.
- **Session reuse.** Script 04 resumes the implementer's session for its
  review, so the reviewer has seen the implementer's reasoning. `run.sh`
  reviews in a fresh, read-only context that sees only the code.
