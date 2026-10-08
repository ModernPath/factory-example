Factory run `001-title-max-length` for `factory/issues/001-title-max-length.md`. **Draft: a person decides whether to merge.**

## Acceptance criteria
1. `create_task("x" * 81)` raises `ValidationError` with the message "Title must be at most 80 characters."
2. `create_task("x" * 80)` returns a `Task` whose `title` is `"x" * 80`.
3. The length is measured on the cleaned title (after surrounding whitespace is stripped): `create_task("  " + "x" * 80 + "  ")` returns a `Task` whose `title` is `"x" * 80`, and `create_task("  " + "x" * 81 + "  ")` raises `ValidationError` with the message "Title must be at most 80 characters."


## Evidence
- RED: `test_sr_1_3_title_at_most_80_characters` failed before implementation (factory/runs/001-title-max-length/red.txt)
- GREEN: `python3 -m pytest -q app/tests` → 5 passed in 0.03s
- Review: approve, no findings
- Cost: $0.4419 across all stages

Log and stage outputs: `factory/runs/001-title-max-length/`.
