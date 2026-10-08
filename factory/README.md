# Factory: validation rules for task creation

This factory turns one issue file into one reviewed draft pull request for a
single task class. It is the course's software-factory module built for the
task list in `app/`.

## Task class

**Add one validation rule to task creation.** Each rule is a check in
`app.tasks.validate_new_task` that raises `ValidationError` with a message,
plus one test in `app/tests/` named after its rule id (`test_sr_1_3_…`).

Why this class: it recurs (every new field or business rule brings one), every
issue has the same shape, completion is checked by a command, and the change
stays inside one function and one test.

Not this factory's work: new features, refactoring, anything touching storage
or a user interface, and anything whose completion a test cannot show.

## Issue format

`factory/issues/<nnn>-<slug>.md`:

```markdown
# <nnn> <one-line title>
Rule id: SR-1.<n>
Change: <the behaviour to add, in one or two sentences>
Acceptance check: <input> → <expected outcome, including the error message>
Out of scope: <what must not change>
Verification: python3 -m pytest -q app/tests
```

Everything the agents need is in the issue or the repository. A factory agent
cannot ask a question halfway through a run. Test an issue by asking whether a
new developer could do the work from it and the repository alone.

## What each stage may change

| Stage | Agent permissions (Claude) | May change | Script gate after it |
|---|---|---|---|
| spec | Read, Grep, Glob, Write | `$RUN/spec.md` only | spec.md exists and has numbered criteria and a test name |
| test | Read, Grep, Glob, Edit, Write | `app/tests/` only | only test files changed, exactly one new test |
| (RED gate) | — | — | the suite must **fail** with the new test |
| implement | Read, Grep, Glob, Edit, Write, Bash(pytest) | `app/` except `app/tests/` | no test or `factory/` file changed |
| (GREEN gate) | — | — | the full suite passes |
| review | Read, Grep, Glob | nothing | returns valid JSON with `"verdict": "approve"` |
| PR | none: the script | — | one draft PR per branch, or `pr.md` |

## Never changed by the factory

- Tests, after the test stage has written its one test.
- `factory/` itself: prompts, gates, this README.
- CI configuration, dependencies, secrets and `.env*` files.
- The main branch. Every run works on `factory/<run id>`, and a person merges.

## When it stops for a person

Any failed gate, a stage that runs out of turns, time or budget, or a review
asking for changes. The run writes `factory/runs/<run id>/stop.md`: the failed
check, the stages already completed with their commits, and the decision a
person has to make. The operating policy is in `docs/decisions.md`.
