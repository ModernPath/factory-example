# Software factory example

A worked example for the software-factory module of ModernPath's *AI coding in
practice* course: a small factory that turns an issue file into a reviewed
draft pull request through headless coding agents. Between stages, a script
runs machine checks, and it stops and tells a person why whenever a check fails.

> A software factory is a reusable policy wrapper around an agent loop:
> goal contract + tool policy + quality gates.

```
factory/issues/001-….md
   │
   ▼  spec (read + write spec.md)        → spec gate: numbered criteria, a named test, no repo changes
   ▼  test (edit app/tests only)         → test gate: exactly one new test, nothing else touched
   │                                     → RED gate: the suite fails, because of that test
   ▼  implement (edit app/, run pytest)  → scope gate: tests and factory/ untouched
   │                                     → GREEN gate: the suite passes
   ▼  review (read-only, fresh context)  → verdict gate: JSON {"verdict": "approve"}
   ▼  draft PR (the script, not an agent) — a person decides whether to merge
```

## What is here

| Path | What it is | Course step |
|---|---|---|
| [`factory/README.md`](factory/README.md) | Task class, issue format, what each stage may change, when it stops | 1. Choose a recurring task |
| [`factory/issues/`](factory/issues/) | Issue 001 (a new rule) and 002 (a rule that already exists) | 1 |
| [`factory/prompts/`](factory/prompts/) | One versioned prompt per stage | 2. Run an agent headless |
| [`factory/run.sh`](factory/run.sh) | The pipeline: stages, gates, state file, budgets, stop report, draft PR | 2, 3. Assemble the pipeline |
| [`factory/example-runs/`](factory/example-runs/) | Two real runs: 001 to a PR, 002 stopped at the RED gate | 3, 4. Prove a check stops it |
| [`docs/decisions.md`](docs/decisions.md) | What the factory may do unattended, and what always needs a person | 4 |
| [`app/`](app/) | The task-list app the factory changes | — |
| [`tests/`](tests/) | Every gate tested against a fake agent, for free | — |
| [`scripts/prove_gates.py`](scripts/prove_gates.py) | Removes each gate in turn and confirms a test goes red | — |
| [`rehearsals/`](rehearsals/) | Four warm-up scripts: minimal factory, roles, resume, spec loop | Slides m09-01…05 |

## Run the factory

You need `git`, Python 3.9+ with pytest, and Claude Code (`claude`) or Codex
(`codex`) signed in. No API key: the CLIs use your subscription.

```bash
python3 -m pip install -r requirements.txt
python3 -m pytest -q app/tests                          # the app's own tests
bash factory/run.sh factory/issues/001-title-max-length.md
cat factory/runs/001-title-max-length/log
```

The run works on branch `factory/001-title-max-length` and returns you to the
branch you started on. Everything it produced is in
`factory/runs/<run id>/`: the log, the state file, each stage's agent output
(`<stage>.out.json`, with turns, duration and cost), `spec.md`, the RED and
GREEN test output, `diff.patch`, `review.json`, and `pr.md` or `stop.md`.

```bash
bash factory/run.sh factory/issues/002-blank-title-rejected.md   # must stop at the RED gate
cat factory/runs/002-blank-title-rejected/stop.md
```

Useful settings: `FACTORY_BACKEND=codex`, `FACTORY_PR=gh` (open a real draft
PR), `FACTORY_RUN_ID=<new id>` (start fresh), `FACTORY_MAX_COST_USD`,
`FACTORY_STAGE_TIMEOUT`, `FACTORY_MAX_TURNS`. See the header of `run.sh`.

Interrupt a run with Ctrl-C and run the same command again: finished stages
are skipped, the interrupted stage starts clean, and its partial work is kept
as a patch in the run folder.

## Prove the gates

```bash
python3 -m pytest -q tests          # each gate fires against a misbehaving fake agent
python3 scripts/prove_gates.py      # each gate removed in turn turns a test red
```

The fake agent (`tests/fake_agent.py`) prints the same JSON as `claude -p`.
Each test asks one stage to misbehave (no spec, two tests, an implementer that
weakens the test, a review that is not JSON, a stage that runs too long or
costs too much) and checks that the right gate stopped the run, that
`stop.md` says why, and that nothing reached `main`.

## Safety

- The factory never runs with `--dangerously-skip-permissions` or `--full-auto`.
  Each stage gets only the tools its job needs; Codex runs in
  `--sandbox read-only` or `workspace-write`.
- Claude runs with `--setting-sources project --strict-mcp-config`, so your
  personal hooks, settings and MCP servers do not join a factory run.
- Runs refuse to start on a dirty working tree, work only on `factory/<run id>`
  branches, and never merge.

## Built from

The rehearsals come from the ModernPath live training's session 4
(software factories). The pipeline follows the course module's four steps,
so its file names, stages and gates are the ones the lessons use.
