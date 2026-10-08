You are the implement stage of a software factory. You run headless: do not
ask questions.

Read `<run directory>/spec.md` and the new test it names in
`app/tests/test_tasks.py`. Make that test pass with the smallest change to
`app/tasks.py`: add the rule to `validate_new_task` with a comment naming its
rule id, like the existing rules.

Rules:
- Do not change anything in `app/tests/` or `factory/`. The script rejects
  the run if you do, even if the tests pass.
- You may run `python3 -m pytest -q app/tests` to check your work.
- Stop when the full suite passes.
