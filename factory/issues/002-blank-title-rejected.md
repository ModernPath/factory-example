# 002 Reject a blank task title
Rule id: SR-1.1
Change: Creating a task whose title is empty or only whitespace raises ValidationError with the message "Title is required."
Acceptance check: create_task("   ") → ValidationError "Title is required."
Out of scope: the other rules, summary(), the Task fields
Verification: python3 -m pytest -q app/tests
