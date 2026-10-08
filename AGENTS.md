# Agent instructions

This repository is a teaching example: a small task-list app in `app/` and a
software factory in `factory/` that changes it.

If you were started by `factory/run.sh`, your stage prompt is your contract.
Do only that stage's work, change only the files it allows, and never edit
`factory/`. The script checks your work after you finish, so a claim in your
reply does not count; the files and the test results do.

Conventions in `app/`:

- Python 3.9 compatible, standard library only; tests use pytest.
- Each validation rule lives in `app.tasks.validate_new_task`, raises
  `ValidationError` with a full-sentence message, and carries a comment with
  its rule id (`# SR-1.n: …`).
- Each rule has one test in `app/tests/test_tasks.py` named after its rule id
  (`test_sr_1_n_…`).
- Verify with `python3 -m pytest -q app/tests`.
