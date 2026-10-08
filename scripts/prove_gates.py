#!/usr/bin/env python3
"""Prove each gate is load-bearing: remove it, run the tests, put it back.

A gate is proven only when it has been seen to fire. The tests show each gate
firing; this script shows the reverse: with the gate removed, some test goes
red. It covers factory/run.sh (tests/test_factory.py) and the agent factory,
rehearsals/05_agent_factory.py (tests/test_agent_factory.py). Run from the
repository root:

  python3 scripts/prove_gates.py            # both
  python3 scripts/prove_gates.py run.sh     # or one of them
  python3 scripts/prove_gates.py agent

Every line must say RED. Do not edit the factories while it runs.
"""

import pathlib
import subprocess
import sys

RUN_SH_GATES = [
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

AGENT_GATES = [
    ("contract gate", "problems = contract_problems(spec)", "problems = []"),
    ("copy: existing folder", "    if agent_dir.exists():", "    if False:"),
    ("tests gate: only tests/ changes", "    if outside_tests:", "    if False:"),
    ("tests gate: offline and temp data forced", "    if not re.search(r'setenv\\([^)]*OFFLINE', text) or not re.search(r'setenv\\([^)]*DATA_DIR', text):", "    if False:"),
    ("tests gate: every action tested", "    if untested:", "    if False:"),
    ("RED gate: tests already pass", "    if proc.returncode == 0:\n        raise Stop('red-gate'", "    if False:\n        raise Stop('red-gate'"),
    ("RED gate: not a test failure", "    if proc.returncode not in (1, 2) and not missing_agent:", "    if False:"),
    ("RED gate: conftest importing the missing agent counts", "    missing_agent = proc.returncode == 4 and", "    missing_agent = False and"),
    ("scope gate: frozen tests", "    if (touched := changed(frozen, now)):", "    if False:"),
    ("scope gate: nothing outside the agent folder", "    if kit_paths or repo_paths:", "    if False:"),
    ("structure", "    problems += [f'missing {p}' for p in required if not (agent_dir / p).is_file()]", "    pass"),
    ("no leftover reference names", "                if LEFTOVERS.search(line) and 'note' not in names.name:", "                if False:"),
    ("no .env files", "        if path.name in ('.env', '.env.local'):", "        if False:"),
    ("no values in .env.example", "        if line.strip() and not line.lstrip().startswith('#') and line.split('=', 1)[-1].strip():", "        if False:"),
    ("GREEN gate", "    if proc.returncode != 0:\n        return [f'GREEN gate", "    if False:\n        return [f'GREEN gate"),
    ("GREEN gate: skipped tests", "    if passed < defined or re.search(", "    if False and re.search("),
    ("smoke: servers answer", "        return [f'{label} did not answer", "        return []\n        return [f'{label} did not answer"),
    ("review only reads", "    if (edited := changed(reviewed, snapshot(agent_dir))):", "    if False:"),
    ("review: valid verdict", "    if verdict is None:", "    if False:"),
    ("resume at a pending review", "        if green_file.exists() and green_file.read_text() == str(attempt):", "        if False:"),
    ("no stray top-level files", "    problems += [f'{p.name}: unexpected file", "    [f'{p.name}: unexpected file"),
    ("removal stays inside the agent folder", "        if rel is None or rel.parts[:1] == ('tests',) or not target.is_file():", "        if not target.is_file():"),
    ("no stale reference files", "    problems += [f'{p} is a reference file", "    [f'{p} is a reference file"),
    ("verdict gate", "        if verdict['verdict'] == 'approve':", "        if True:"),
    ("attempts are bounded", "            if attempt > run.args.max_attempts:", "            if False:"),
    ("run budget", "    if run.spent() >= run.args.max_cost_usd:", "    if False:"),
    ("stage timeout", "text=True, timeout=run.args.stage_timeout)", "text=True, timeout=None)"),
    ("resume: skip finished stages", "    if 'tests' in run.done():", "    if False:"),
    ("dirty kit refusal", "    if 'copy' not in run.done() and (dirty := kit_changes_outside(kit, '\\0')):", "    if False:"),
]

TARGETS = {
    "run.sh": (pathlib.Path("factory/run.sh"), "tests/test_factory.py", RUN_SH_GATES),
    "agent": (pathlib.Path("rehearsals/05_agent_factory.py"), "tests/test_agent_factory.py", AGENT_GATES),
}


def pytest(test_file):
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", test_file],
                          capture_output=True, text=True)


hollow = 0
for key in sys.argv[1:] or list(TARGETS):
    path, test_file, gates = TARGETS[key]
    original = path.read_text()
    print(f"# {path}")
    try:
        for name, old, new in gates:
            assert original.count(old) == 1, f"{name}: anchor found {original.count(old)} times"
            path.write_text(original.replace(old, new))
            r = pytest(test_file)
            failing = [l.split(" - ")[0].replace("FAILED ", "") for l in r.stdout.splitlines() if l.startswith("FAILED")]
            hollow += not failing
            print(f"## {name}: {'RED' if failing else 'STILL GREEN (hollow!)'}" + (f" — first: {failing[0]}" if failing else ""))
    finally:
        path.write_text(original)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", test_file], capture_output=True, text=True)
    hollow += r.returncode != 0
    print("restored:", r.stdout.strip().splitlines()[-1])
sys.exit(1 if hollow else 0)
