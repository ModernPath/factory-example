# 003 Reject titles made only of tabs and line breaks
Rule id: SR-1.4
Change: A title pasted from a spreadsheet can be only tabs and line breaks, for example "\t\n\t". Creating a task with such a title raises ValidationError with the message "Title is required."
Acceptance check: create_task("\t\n\t") → ValidationError "Title is required."; create_task("\tCall Bob\n") → a Task titled "Call Bob"
Out of scope: the other rules, summary(), the Task fields
Verification: python3 -m pytest -q app/tests
