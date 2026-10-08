# 002 Reject a blank task title

Rule id: SR-1.1

Note: `app/tasks.py` already contains the SR-1.1 check in `validate_new_task`. This spec fixes the behaviour with a test; no behaviour change is expected.

## Acceptance criteria

1. `create_task("")` raises `ValidationError` with the message "Title is required."
2. `create_task("   ")` raises `ValidationError` with the message "Title is required."
3. A title of only whitespace characters other than spaces (for example `"\t\n"`) raises `ValidationError` with the message "Title is required."
4. A title with non-whitespace content, such as `create_task("Buy milk")`, does not raise and returns a `Task` with that title.

Test: app/tests/test_tasks.py::test_sr_1_1_blank_title_rejected

## Out of scope

the other rules, summary(), the Task fields
