# Decisions

## 2026-10-08 — Operating policy for the validation-rule factory

**The factory may do unattended:** turn an issue in `factory/issues/` into a
spec, one failing test, an implementation and a review on its own branch
`factory/<run id>`, and write `pr.md` or open a **draft** pull request. It
stops by itself on any failed gate, on running out of turns, time (600 s per
stage) or budget ($3 per run), and when the reviewer asks for changes.

**Always needs a person:**

- merging a factory branch or marking its PR ready for review;
- changing gates, prompts or anything else under `factory/`;
- changing the issue format or the task class;
- anything involving secrets, credentials, CI configuration or dependencies;
- deciding what a stop report asks: close the issue, sharpen it, or fix by hand.

**Why:** the gates check what a machine can check: that a new test failed
first, that the suite passes, that only allowed files changed, and that a
read-only reviewer approved. Whether the change is worth having, and whether
the gates themselves are still right, is a human decision.

**Revisit when:** the factory has run on ten real issues. Count accepted PRs,
stops by gate, review time and cost per accepted PR (see the course slide on
measuring a factory).
