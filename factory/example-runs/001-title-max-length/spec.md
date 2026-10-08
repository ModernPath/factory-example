# 001 Reject task titles longer than 80 characters

Rule id: SR-1.3

## Acceptance criteria

1. `create_task("x" * 81)` raises `ValidationError` with the message "Title must be at most 80 characters."
2. `create_task("x" * 80)` returns a `Task` whose `title` is `"x" * 80`.
3. The length is measured on the cleaned title (after surrounding whitespace is stripped): `create_task("  " + "x" * 80 + "  ")` returns a `Task` whose `title` is `"x" * 80`, and `create_task("  " + "x" * 81 + "  ")` raises `ValidationError` with the message "Title must be at most 80 characters."

Test: app/tests/test_tasks.py::test_sr_1_3_title_at_most_80_characters

## Out of scope

the other rules, summary(), the Task fields
