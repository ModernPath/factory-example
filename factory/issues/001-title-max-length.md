# 001 Reject task titles longer than 80 characters
Rule id: SR-1.3
Change: Creating a task whose cleaned title is longer than 80 characters raises ValidationError with the message "Title must be at most 80 characters." A title of exactly 80 characters is still accepted.
Acceptance check: create_task("x" * 81) → ValidationError "Title must be at most 80 characters."; create_task("x" * 80) → a Task with that title
Out of scope: the other rules, summary(), the Task fields
Verification: python3 -m pytest -q app/tests
