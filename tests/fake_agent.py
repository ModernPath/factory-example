#!/usr/bin/env python3
"""A stand-in for `claude -p` so the factory's gates can be tested for free.

run.sh calls it with FACTORY_BACKEND=fake. It reads the stage from
FACTORY_STAGE and does what a well-behaved agent would, unless the test asks
that stage to misbehave with FACTORY_FAKE_<STAGE>=<behaviour>:

  spec:      good | missing | blocked | touches_repo
  test:      good | existing | two_tests | touches_app | edits_existing
  implement: good | touches_tests | broken | fails | slow
  review:    good | changes | garbage
  any stage: expensive (reports a high cost)

It prints a result object shaped like Claude Code's `--output-format json`
and appends the stage name to <run>/fake-calls, so tests can see which
stages actually ran.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

STAGE = os.environ["FACTORY_STAGE"]
RUN = Path(os.environ["FACTORY_RUN"])
BEHAVIOUR = os.environ.get(f"FACTORY_FAKE_{STAGE.upper()}", "good")
TASKS = Path("app/tasks.py")
TESTS = Path("app/tests/test_tasks.py")

NEW_RULE_TEST = '''

def test_sr_1_3_title_at_most_80_characters():
    assert create_task("x" * 80).title == "x" * 80
    with pytest.raises(ValidationError, match="Title must be at most 80 characters."):
        create_task("x" * 81)
'''

EXISTING_RULE_TEST = '''

def test_sr_1_1_blank_title_is_rejected():
    with pytest.raises(ValidationError, match="Title is required."):
        create_task("   ")
'''

RULE = '''    # SR-1.3: titles stay short enough for the list view.
    if len(cleaned) > 80:
        raise ValidationError("Title must be at most 80 characters.")
'''


def spec(test_name: str, issue: str) -> str:
    return (
        f"# {issue}\n\n## Acceptance criteria\n\n"
        "1. create_task with an 81-character title raises ValidationError.\n"
        "2. create_task with an 80-character title succeeds.\n\n"
        f"Test: app/tests/test_tasks.py::{test_name}\n\n## Out of scope\n\nOther rules.\n"
    )


def act() -> str:
    if STAGE == "spec":
        if BEHAVIOUR == "missing":
            return "I could not write the spec."
        if BEHAVIOUR == "blocked":
            (RUN / "spec.md").write_text("# 001\n\nBLOCKED: Should the limit count characters or bytes?\n")
            return "Blocked."
        existing = os.environ.get("FACTORY_FAKE_TEST") == "existing"
        name = "test_sr_1_1_blank_title_is_rejected" if existing else "test_sr_1_3_title_at_most_80_characters"
        (RUN / "spec.md").write_text(spec(name, "001"))
        if BEHAVIOUR == "touches_repo":
            TASKS.write_text(TASKS.read_text() + "\n# spec stage was here\n")
        return "Wrote spec.md."

    if STAGE == "test":
        text = TESTS.read_text()
        if BEHAVIOUR == "existing":
            TESTS.write_text(text + EXISTING_RULE_TEST)
        elif BEHAVIOUR == "two_tests":
            TESTS.write_text(text + NEW_RULE_TEST + NEW_RULE_TEST.replace("80_characters", "80_chars_again"))
        elif BEHAVIOUR == "edits_existing":
            TESTS.write_text(text.replace('match="Title is required"', 'match="Title"') + NEW_RULE_TEST)
        else:
            TESTS.write_text(text + NEW_RULE_TEST)
            if BEHAVIOUR == "touches_app":
                TASKS.write_text(TASKS.read_text() + "\n# test stage was here\n")
        return "Added the test."

    if STAGE == "implement":
        if BEHAVIOUR == "fails":
            raise RuntimeError("simulated agent failure")
        if BEHAVIOUR == "slow":
            time.sleep(30)
        rule = RULE.replace("at most 80 characters.", "at most 80 chars.") if BEHAVIOUR == "broken" else RULE
        source = TASKS.read_text()
        TASKS.write_text(re.sub(r"(    return cleaned\n)", rule + r"\1", source, count=1))
        if BEHAVIOUR == "touches_tests":
            TESTS.write_text(TESTS.read_text().replace('create_task("x" * 81)', 'create_task("x" * 80)'))
        return "Implemented the rule."

    if STAGE == "review":
        if BEHAVIOUR == "garbage":
            return "Looks good to me!"
        if BEHAVIOUR == "changes":
            return json.dumps({"verdict": "changes", "findings": ["error message differs from the issue"]})
        return 'Reviewed.\n{"verdict": "approve", "findings": []}'

    raise SystemExit(f"unknown stage {STAGE}")


def main() -> None:
    with open(RUN / "fake-calls", "a") as calls:
        calls.write(STAGE + "\n")
    cost = 2.0 if BEHAVIOUR == "expensive" else 0.01
    try:
        text = act()
        result = {"type": "result", "subtype": "success", "is_error": False, "result": text}
    except RuntimeError as exc:
        result = {"type": "result", "subtype": "error_during_execution", "is_error": True, "result": str(exc)}
    result.update({"num_turns": 3, "total_cost_usd": cost, "duration_ms": 1000})
    print(json.dumps(result))


if __name__ == "__main__":
    main()
