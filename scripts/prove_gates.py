#!/usr/bin/env python3
"""Prove each gate in factory/run.sh is load-bearing: remove it, run the tests, put it back.

A gate is proven only when it has been seen to fire. tests/test_factory.py
shows each gate firing; this script shows the reverse: with the gate removed,
some test goes red. Run from the repository root:

  python3 scripts/prove_gates.py

Every line must say RED. Do not edit factory/run.sh while it runs.
"""

import pathlib
import subprocess
import sys

RUN_SH = pathlib.Path("factory/run.sh")
GATES = [
    ("RED gate: new test already passes", 'if run_tests "$RUN/red.txt"; then', "if false; then"),
    ("RED gate: failure must be the new test", 'grep -q "$name" "$RUN/red.txt" || stop red-gate', 'true || stop red-gate'),
    ("spec gate: spec.md exists", '[ -s "$spec" ] || stop spec', 'true || stop spec'),
    ("spec gate: BLOCKED question", "if grep -q '^BLOCKED:' \"$spec\"; then", "if false; then"),
    ("spec gate: no repository changes", '[ -z "$(changed_files)" ] || stop spec', 'true || stop spec'),
    ("test gate: exactly one new test", '[ "$added" -eq 1 ] || stop test', 'true || stop test'),
    ("test gate: only app/tests changes", '[ -z "$outside" ] || stop test', 'true || stop test'),
    ("test gate: existing tests untouched", '[ "$removed" -eq 0 ] || stop test', 'true || stop test'),
    ("scope gate: implementer stays out of tests", '[ -z "$forbidden" ] || stop implement', 'true || stop implement'),
    ("GREEN gate", 'if ! run_tests "$RUN/green.txt"; then', "if false; then"),
    # Double quotes only: the Python sits inside a single-quoted bash string in run.sh.
    ("review: valid verdict", "if not ok: sys.exit(1)", 'if not ok: ok = True; data = {"verdict": "approve", "findings": []}'),
    ("verdict gate", 'if [ "$(json_field "$RUN/review.json" verdict)" != "approve" ]; then', "if false; then"),
    ("stage timeout", 'if [ "$rc" -eq 124 ] || [ "$rc" -eq 142 ]; then', "if false; then"),
    ("run budget", "if awk -v r=\"$remaining\" 'BEGIN {exit !(r <= 0)}'; then", "if false; then"),
    ("resume: skip finished stages", 'if is_done "$1"; then log', 'if false; then log'),
    ("dirty tree refusal", 'if [ -n "$(git status --porcelain)" ]; then\n    echo "run.sh: the working tree', 'if false; then\n    echo "run.sh: the working tree'),
    ("rejected work set aside", "  if [ -n \"$(git status --porcelain)\" ]; then\n    git add -A\n    git diff --cached", "  if false; then\n    git add -A\n    git diff --cached"),
]

original = RUN_SH.read_text()
hollow = 0
try:
    for name, old, new in GATES:
        assert original.count(old) == 1, f"{name}: anchor found {original.count(old)} times"
        RUN_SH.write_text(original.replace(old, new))
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_factory.py"],
                           capture_output=True, text=True)
        failing = [l.split(" - ")[0].replace("FAILED ", "") for l in r.stdout.splitlines() if l.startswith("FAILED")]
        hollow += not failing
        print(f"## {name}: {'RED' if failing else 'STILL GREEN (hollow!)'} — {len(failing)} failing")
        for f in failing:
            print("   ", f)
finally:
    RUN_SH.write_text(original)
r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_factory.py"], capture_output=True, text=True)
print("restored:", r.stdout.strip().splitlines()[-1])
sys.exit(1 if hollow or r.returncode else 0)
