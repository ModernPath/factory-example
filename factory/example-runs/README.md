# Example runs

Real runs of `factory/run.sh` with Claude Code (`claude-sonnet-5-5`, the
headless default) on 2026-10-08. Each folder is a copy of
`factory/runs/<run id>/` with empty stderr files removed and the branch's
diff added as `branch.diff`. The factory branches themselves were not pushed.

| Run | Outcome | Stages | Cost | Wall time |
|---|---|---|---|---|
| [`001-title-max-length`](001-title-max-length/) | Reviewed change and `pr.md` | spec, test, RED, implement, GREEN, review, PR | $0.44 | ~40 s |
| [`002-blank-title-rejected`](002-blank-title-rejected/) | Stopped at the RED gate | spec, test, **RED stop** | $0.23 | ~25 s |
| [`003-reject-tab-and-newline-titles`](003-reject-tab-and-newline-titles/) | Stopped at the RED gate | spec, test, **RED stop** | $0.23 | ~25 s |

## What to read

- **001**: `spec.md` turns the issue into three criteria. The spec stage
  noticed that the issue speaks of the *cleaned* title, and added a criterion
  for padded titles. `branch.diff` holds the one test and the three-line rule;
  `log` has the turns, cost and seconds of each stage; `pr.md` is the PR body.
- **002** asks for a rule the app already has, labelled SR-1.1 and tested.
  The new test passed at once, and `stop.md` tells a person to close the issue
  or sharpen it.
- **003** asks for behaviour the app already has **by accident**: `strip()`
  already removes tabs and line breaks, but no rule or test names it. This is
  the case the RED gate exists for, because nothing in the code points at the
  answer.

## The same issue does not always stop in the same place

In an earlier run of issue 002, the spec agent noticed the rule before any
test existed. It wrote a `BLOCKED:` line instead of a spec, and the spec gate
stopped the run for $0.13:

> BLOCKED: SR-1.1 already exists. `validate_new_task` in `app/tasks.py`
> already raises `ValidationError("Title is required.")` for an empty or
> whitespace-only title (comment `# SR-1.1`), and
> `app/tests/test_tasks.py::test_sr_1_1_title_is_required` already covers it.
> A new test named after SR-1.1 would pass immediately and could not go RED.
> Should this issue be closed as already done, or is a different rule id or
> behaviour intended?

On the run kept here, the spec agent did not notice, and the RED gate caught
it one stage later. Which stage stops a bad issue varies from run to run,
because it depends on what the model notices. **That** a bad issue stops does
not vary, because the gates are in the script.
