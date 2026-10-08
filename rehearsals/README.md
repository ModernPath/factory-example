# Rehearsals: factory concepts in five scripts

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
| `05_agent_factory.py` | A factory whose product is an agent: builds a new agent in [agent-example](https://github.com/ModernPath/agent-example)'s format, tests first, gates in code | — |

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

## The agent factory (05)

`05_agent_factory.py` builds a whole agent, not a validation rule. Its input
is an agent contract in `agent-specs/` (or a one-line `--idea` that a spec
stage turns into one). Its output is a new folder in an
[agent-example](https://github.com/ModernPath/agent-example) checkout, where
that kit's `AGENTS.md` says agents go, copied from `example-agent/` and
rebuilt for the new domain:

```
contract ──▶ copy example-agent/ ──▶ tests (agent writes tests/ only)
                                      │ gate: only tests/ changed, offline + temp data forced, every action tested
                                      ▼ RED gate: the suite fails before the agent exists
             build (agent; tests/ frozen) ◀──────────────┐ problems or "changes" go back,
                                      │ scope gates: stop │ within --max-attempts
                                      │ quality gates ────┘
                                      ▼ review (fresh, read-only) → JSON verdict
                                      ▼ handoff.md: what a person still checks
```

- **Scope gates stop the run:** changing the frozen tests, the kit outside
  the new folder, or this repository. Asking an agent again does not undo
  that, so a person decides.
- **Quality gates send the work back:** the kit's structure with the new names
  (`<name>_core.py`, `<NAME>_OFFLINE`, one `tools/<action>.py` per action), no
  `example_`/note names left, no `.env` files, data files or values in
  `.env.example`, the offline suite green with nothing skipped, and the CLI,
  every tool, the API's `/health` and the UI's home page started for real.
- **What it leaves to a person** is in `handoff.md`, following the kit's
  AGENTS.md steps 6–7: read the README contract, run the browser tests and use
  the UI, then commit the folder and register it, or delete it. The factory
  commits nothing.

```bash
git clone https://github.com/ModernPath/agent-example ../agent-example
python -m pip install -r ../agent-example/example-agent/requirements.txt
python rehearsals/05_agent_factory.py --spec rehearsals/agent-specs/reading-list-agent.json
cat rehearsals/agent-runs/reading-list-agent/log
```

Two real runs that built `reading-list-agent`, one that gamed a gate and one
approved, are in [`agent-example-runs/`](agent-example-runs/README.md).

`--python` names the interpreter with the agent's requirements if it is not
the one running the factory. Rerun the same command to resume. The gates are
tested in `tests/test_agent_factory.py` with a fake agent whose good work is
the notes reference renamed to `memo-agent`, so those tests run a real
agent's suite and start its real API and UI; `scripts/prove_gates.py agent`
removes each of its 29 gates in turn and shows a test going red.

### What changed from the live training's version

Session 4's `05_agent_factory.py` built agents into a folder layout that no
longer exists. It now builds into agent-example, and on the way:

- **Its API check accepted a 404 as a pass**, so an API with only `/docs` passed
  "at least one endpoint responds". Now `/health` must answer 200 and the UI's
  home page must be HTML, on the port the factory asked for.
- **The reviewer resumed the implementer's session** and was approved by the
  text `FINAL_STATUS: APPROVED` anywhere in its reply. Now the review is a
  fresh, read-only session, its tools have no write access, the factory checks
  that no file changed, and only a JSON verdict counts.
- **Nothing stopped an agent from editing its own checks.** Tests are now
  written first, must fail, and are frozen; a build that touches them, the kit
  or this repository stops the run.
- **Tests had to exist, but nothing said which.** Every contract action must
  be named in the tests, conftest must force offline mode and a temporary data
  dir, and a suite with skipped tests is not green.
- **The working directory never reached Claude.** `backend_runner.py` did not
  pass `cwd` to the Agent SDK, so every Claude session ran wherever the script
  was started. The first real run found it (see `agent-example-runs/`).
- **No budget or timeout for Claude.** The Agent SDK has no timeout of its
  own; `backend_runner.py` now enforces one and reports cost, and the factory
  stops before an agent call once `--max-cost-usd` is spent.

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
