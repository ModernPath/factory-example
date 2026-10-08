# 003 Reject titles made only of tabs and line breaks

Rule id: SR-1.4

## Acceptance criteria

1. `create_task("\t\n\t")` raises `ValidationError` with the message "Title is required."
2. `create_task("\tCall Bob\n")` returns a `Task` whose `title` is "Call Bob".

Note: `validate_new_task` already strips all whitespace, including tabs and line breaks, so these criteria may hold before any code change. The rule still gets its own comment (`# SR-1.4: …`) and test.

Test: app/tests/test_tasks.py::test_sr_1_4_title_of_only_tabs_and_line_breaks_is_rejected

## Out of scope

the other rules, summary(), the Task fields
