#!/usr/bin/env python3
"""Agent factory: build a new agent in agent-example's format, gates in code.

The factory takes an agent contract (a spec file, or an idea it turns into
one) and builds the agent where the agent kit says agents go: a new folder at
the root of an agent-example checkout, copied from example-agent.

  spec     contract as JSON          gate: the contract is complete
  copy     example-agent -> <name>/  (no agent; secrets, data and evals left behind)
  tests    agent rewrites tests/     gate: only tests/ changed, offline + temp data,
                                           every action tested
  red      -                         gate: the suite fails before the agent exists
  build    agent builds the agent    gates: tests/ untouched, nothing outside <name>/,
                                            structure, no leftovers, no secrets,
                                            GREEN, CLI/tools/API/UI start
  review   fresh read-only session   gate: a JSON verdict of "approve"
  handoff  handoff.md                what a person still checks before committing

A failed quality gate or a "changes" verdict sends the work back to build,
within --max-attempts. A scope gate never does: an agent that edits its own
tests or the kit is not fixed by asking again, so the run stops for a person.
The factory commits nothing: the new folder is left untracked in the kit.

Usage (from the factory-example root):
  python rehearsals/05_agent_factory.py --spec rehearsals/agent-specs/reading-list-agent.json
  python rehearsals/05_agent_factory.py --idea "an agent that tracks my reading list"
  python rehearsals/05_agent_factory.py --spec ... --kit ../agent-example --backend codex

Run it again with the same arguments to resume: finished stages are skipped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PROMPTS = HERE / 'agent-prompts'
RUNS = Path(os.environ.get('FACTORY_AGENT_RUNS', HERE / 'agent-runs'))
EXAMPLE_SPEC = HERE / 'agent-specs' / 'reading-list-agent.json'
FAKE_AGENT = REPO / 'tests' / 'fake_agent_builder.py'

SKIP_DIRS = {'.git', '.venv', '__pycache__', '.pytest_cache', 'agent-runs'}
LEFT_BEHIND = {'.env', '.env.local', '.venv', '__pycache__', '.pytest_cache', 'evals', 'test_evals.py'}
REFERENCE_FILES = ['example_agent.py', 'example_chat.py', 'example_core.py', 'example_service.py',
                   'memory/note_schema.json', 'skills/note-search.md', 'skills/note-summary.md', 'skills/note-taking.md',
                   'subagents/note_summarizer.py', 'tools/add_note.py', 'tools/delete_note.py', 'tools/search_notes.py']
LEFTOVERS = re.compile(r'\bexample_(core|service|chat|agent)\b|EXAMPLE_AGENT_|Example Agent|\bNoteStore\b|\bnote_summarizer\b')
TEXT_SUFFIXES = {'.py', '.md', '.html', '.json', '.txt', '.ini', '.example', '.css', '.js'}
API_KEY_VARS = ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_AI_STUDIO_KEY')


class Stop(Exception):
    """A gate fired: the run ends here and stop.md tells a person why."""

    def __init__(self, stage: str, reason: str, decision: str, details: str = '') -> None:
        super().__init__(reason)
        self.stage, self.reason, self.decision, self.details = stage, reason, decision, details


class Retry(Exception):
    """A quality gate failed: the build gets another attempt with these problems."""


@dataclass
class Names:
    name: str    # reading-list-agent
    base: str    # reading_list   -> reading_list_core.py ...
    prefix: str  # READING_LIST_AGENT -> READING_LIST_AGENT_OFFLINE ...


@dataclass
class Run:
    args: argparse.Namespace
    kit: Path
    run_dir: Path
    python: str

    def log(self, line: str) -> None:
        stamped = f'{datetime.now():%H:%M:%S} {line}'
        print(stamped, flush=True)
        with open(self.run_dir / 'log', 'a', encoding='utf-8') as f:
            f.write(stamped + '\n')

    def done(self) -> list[str]:
        path = self.run_dir / 'state'
        return [line.split()[0] for line in path.read_text().splitlines()] if path.exists() else []

    def mark(self, stage: str) -> None:
        with open(self.run_dir / 'state', 'a', encoding='utf-8') as f:
            f.write(f'{stage} {datetime.now().isoformat(timespec="seconds")}\n')

    def spent(self) -> float:
        path = self.run_dir / 'costs'
        return sum(float(x) for x in path.read_text().split()) if path.exists() else 0.0


# --------------------------------------------------------------------------- #
# The contract
# --------------------------------------------------------------------------- #
def contract_problems(spec: dict[str, Any]) -> list[str]:
    if 'blocked' in spec:
        return [f'BLOCKED: {spec["blocked"]}']
    problems = []
    if not re.fullmatch(r'[a-z][a-z0-9]*(-[a-z0-9]+)*-agent', str(spec.get('name', ''))):
        problems.append('"name" must be kebab case and end with "-agent"')
    if not str(spec.get('purpose', '')).strip():
        problems.append('"purpose" is empty')
    record = spec.get('record') or {}
    if not re.fullmatch(r'[a-z][a-z0-9_]*', str(record.get('name', ''))):
        problems.append('"record.name" must be snake case')
    fields = record.get('fields') or []
    if not fields or any(not f.get('name') or not str(f.get('rule', '')).strip() for f in fields):
        problems.append('every record field needs a name and a rule a test can check')
    actions = spec.get('actions') or []
    names = [str(a.get('name', '')) for a in actions]
    if not 1 <= len(actions) <= 6:
        problems.append('give one to six actions')
    if any(not re.fullmatch(r'[a-z][a-z0-9_]*', n) for n in names) or len(set(names)) != len(names):
        problems.append('action names must be unique and snake case')
    if any(not str(a.get('does', '')).strip() for a in actions):
        problems.append('every action needs "does"')
    surfaces = spec.get('surfaces') or []
    if 'cli' not in surfaces or not set(surfaces) <= {'cli', 'api', 'ui'}:
        problems.append('"surfaces" must include "cli" and may add "api" and "ui"')
    return problems


def names_for(spec: dict[str, Any]) -> Names:
    name = spec['name']
    return Names(name=name, base=name[: -len('-agent')].replace('-', '_'), prefix=name.replace('-', '_').upper())


# --------------------------------------------------------------------------- #
# Things the gates look at
# --------------------------------------------------------------------------- #
def snapshot(root: Path) -> dict[str, str]:
    """sha256 of every file under root, skipping caches and virtualenvs."""
    files = {}
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        if path.is_file() and not SKIP_DIRS.intersection(rel.parts):
            files[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


def kit_changes_outside(kit: Path, name: str) -> list[str]:
    out = subprocess.run(['git', '-C', str(kit), 'status', '--porcelain', '--untracked-files=all'],
                         capture_output=True, text=True, check=True).stdout
    paths = [line[3:] for line in out.splitlines()]
    return [p for p in paths if not p.startswith(f'{name}/')]


def agent_env(names: Names, data_dir: Path) -> dict[str, str]:
    """Offline, a throwaway data dir, and no provider key reaching the agent."""
    env = {k: v for k, v in os.environ.items() if k not in API_KEY_VARS}
    env.update({f'{names.prefix}_OFFLINE': '1', f'{names.prefix}_DATA_DIR': str(data_dir), 'PYTHONDONTWRITEBYTECODE': '1'})
    return env


def test_command(run: Run) -> list[str]:
    # The browser tests need Playwright and a browser; a person runs them (handoff.md).
    return [run.python, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--ignore=tests/test_browser.py']


def run_suite(run: Run, names: Names, agent_dir: Path) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as data:
        return subprocess.run(test_command(run), cwd=agent_dir, env=agent_env(names, Path(data)),
                              capture_output=True, text=True, timeout=600)


def tail(text: str, lines: int = 25) -> str:
    return '\n'.join(text.strip().splitlines()[-lines:])


# --------------------------------------------------------------------------- #
# Running an agent
# --------------------------------------------------------------------------- #
def prompt_for(stage: str, **values: str) -> str:
    text = (PROMPTS / f'{stage}.md').read_text(encoding='utf-8')
    if 'KIT' in values:
        values.setdefault('KIT_RULES', (Path(values['KIT']) / 'AGENTS.md').read_text(encoding='utf-8'))
    for key, value in values.items():
        text = text.replace('{{' + key + '}}', value)
    if (unfilled := re.findall(r'\{\{[A-Z_]+\}\}', text)):
        raise ValueError(f'{stage}.md: unfilled {unfilled}')
    return text


def run_agent(run: Run, stage: str, prompt: str, *, cwd: Path, tools: list[str], writes: bool,
              max_turns: int, extra_env: dict[str, str] | None = None) -> str:
    if run.spent() >= run.args.max_cost_usd:
        raise Stop(stage, f'the run budget of ${run.args.max_cost_usd:g} is used up (${run.spent():.2f} spent)',
                   'Raise --max-cost-usd to continue, or stop here.')
    (run.run_dir / f'{stage}.prompt.md').write_text(prompt, encoding='utf-8')
    started = time.time()
    if run.args.backend == 'fake':
        env = {**os.environ, **(extra_env or {}), 'FACTORY_STAGE': stage, 'FACTORY_RUN': str(run.run_dir),
               'FACTORY_KIT': str(run.kit)}
        try:
            proc = subprocess.run([sys.executable, str(FAKE_AGENT)], cwd=cwd, env=env, capture_output=True,
                                  text=True, timeout=run.args.stage_timeout)
        except subprocess.TimeoutExpired:
            raise Stop(stage, f'the agent timed out after {run.args.stage_timeout}s', 'Rerun to retry this stage.')
        data = json.loads(proc.stdout.strip().splitlines()[-1])
        ok, text, cost, why = not data['is_error'], data['result'], data.get('total_cost_usd'), data['subtype']
    else:
        from backend_runner import BackendRunOptions, run_sync
        result = run_sync(BackendRunOptions(
            backend=run.args.backend, prompt=prompt, cwd=cwd, allowed_tools=tools,
            permission_mode='acceptEdits' if writes else 'default', max_turns=max_turns,
            model=run.args.model, timeout_seconds=run.args.stage_timeout))
        ok, text, cost, why = result.ok, result.text, result.cost_usd, result.stop_reason
    with open(run.run_dir / 'costs', 'a') as f:
        f.write(f'{cost or 0}\n')
    (run.run_dir / f'{stage}.out.txt').write_text(text, encoding='utf-8')
    cost_note = f'${cost:.2f}' if cost is not None else 'cost not reported'
    run.log(f'{stage}: agent finished in {time.time() - started:.0f}s, {cost_note}')
    if not ok:
        reason = why if why.startswith(('claude_error: timeout', 'codex_error: timeout', 'opencode_error: timeout')) \
            else f'the agent did not finish: {why}'
        raise Stop(stage, reason, 'Rerun to retry this stage, or read the prompt and output in the run folder.')
    return text


def check_outside(run: Run, stage: str, names: Names, repo_before: dict[str, str]) -> None:
    kit_paths = kit_changes_outside(run.kit, names.name)
    repo_paths = changed(repo_before, snapshot(REPO))
    if kit_paths or repo_paths:
        raise Stop(stage, f'the {stage} stage changed files outside {names.name}/',
                   'Inspect and revert those files by hand; the factory does not undo them.',
                   '\n'.join([f'kit: {p}' for p in kit_paths] + [f'factory: {p}' for p in repo_paths]))


# --------------------------------------------------------------------------- #
# Stages
# --------------------------------------------------------------------------- #
def stage_spec(run: Run) -> dict[str, Any]:
    spec_path = run.run_dir / 'spec.json'
    if 'spec' not in run.done():
        if run.args.spec:
            shutil.copy(run.args.spec, spec_path)
        else:
            repo_before = snapshot(REPO)
            prompt = prompt_for('spec', IDEA=run.args.idea, KIT=str(run.kit), SPEC_PATH=str(spec_path),
                                EXAMPLE_SPEC=EXAMPLE_SPEC.read_text(encoding='utf-8'))
            run_agent(run, 'spec', prompt, cwd=run.kit, tools=['Read', 'Glob', 'Grep', 'Write'], writes=True,
                      max_turns=20)
            if kit_changes_outside(run.kit, '\0') or changed(repo_before, snapshot(REPO)):
                raise Stop('spec', 'the spec stage changed repository files', 'Revert them; the spec stage only writes spec.json.')
        if not spec_path.exists():
            raise Stop('spec', 'spec.json is missing', 'Write the contract by hand and pass it with --spec.')
        try:
            spec = json.loads(spec_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            raise Stop('spec', f'spec.json is not JSON: {exc}', 'Fix the contract and pass it with --spec.')
        problems = contract_problems(spec)
        if problems:
            raise Stop('spec', '; '.join(problems), 'Answer the question or complete the contract, then pass it with --spec.')
        run.mark('spec')
        run.log(f'spec: contract for {spec["name"]} with {len(spec["actions"])} actions')
    return json.loads(spec_path.read_text(encoding='utf-8'))


def stage_copy(run: Run, names: Names, agent_dir: Path) -> None:
    if 'copy' in run.done():
        return run.log('skip copy')
    if agent_dir.exists():
        raise Stop('copy', f'{agent_dir} already exists', 'Pick another agent name or move that folder away.')

    def ignore(directory: str, entries: list[str]) -> set[str]:
        skipped = {e for e in entries if e in LEFT_BEHIND or e.endswith('.pyc')}
        if Path(directory).as_posix().endswith('memory/data'):
            skipped |= {e for e in entries if e != '.gitkeep'}  # the reference's live notes stay behind
        return skipped

    shutil.copytree(run.kit / 'example-agent', agent_dir, ignore=ignore)
    (run.run_dir / 'copy.snapshot.json').write_text(json.dumps(snapshot(agent_dir), indent=1))
    run.mark('copy')
    run.log(f'copy: example-agent -> {agent_dir} (without .env files, memory data, caches or evals)')


def stage_tests(run: Run, spec: dict[str, Any], names: Names, agent_dir: Path) -> None:
    if 'tests' in run.done():
        return run.log('skip tests')
    repo_before = snapshot(REPO)
    tools = ', '.join(f'tools/{a["name"]}.py' for a in spec['actions'])
    prompt = prompt_for('tests', SPEC=json.dumps(spec, indent=2), AGENT_DIR=str(agent_dir), KIT=str(run.kit),
                        BASE=names.base, PREFIX=names.prefix, TOOLS=tools, TEST_CMD=' '.join(test_command(run)))
    run_agent(run, 'tests', prompt, cwd=agent_dir, writes=True, max_turns=60,
              tools=['Read', 'Glob', 'Grep', 'Edit', 'Write', f'Bash({run.python} -m pytest:*)', 'Bash(ls:*)'],
              extra_env={'FACTORY_SPEC': json.dumps(spec)})
    check_outside(run, 'tests', names, repo_before)

    before = json.loads((run.run_dir / 'copy.snapshot.json').read_text())
    outside_tests = [p for p in changed(before, snapshot(agent_dir)) if not p.startswith('tests/')]
    if outside_tests:
        raise Stop('tests', 'the tests stage changed files outside tests/',
                   'Delete the agent folder and rerun with a new --run-id.', '\n'.join(outside_tests))
    conftest = agent_dir / 'tests' / 'conftest.py'
    text = conftest.read_text(encoding='utf-8') if conftest.exists() else ''
    if not re.search(r'setenv\([^)]*OFFLINE', text) or not re.search(r'setenv\([^)]*DATA_DIR', text):
        raise Stop('tests', 'tests/conftest.py does not force offline mode and a temporary data dir',
                   'Fix conftest.py by hand, or rerun with a new --run-id.')
    test_files = sorted((agent_dir / 'tests').glob('*.py'))
    all_tests = '\n'.join(p.read_text(encoding='utf-8') for p in test_files)
    untested = [a['name'] for a in spec['actions'] if a['name'] not in all_tests]
    if untested:
        raise Stop('tests', f'no test names the action(s) {", ".join(untested)}',
                   'Add the tests by hand, or rerun with a new --run-id.')
    broken = subprocess.run([run.python, '-m', 'py_compile', *map(str, test_files)], capture_output=True, text=True)
    if broken.returncode != 0:
        raise Stop('tests', 'a test file does not compile', 'Fix the test by hand, or rerun with a new --run-id.',
                   tail(broken.stderr))
    run.mark('tests')
    run.log(f'tests: {len(test_files)} test files, every action named, offline and temp data forced')


def stage_red(run: Run, names: Names, agent_dir: Path) -> None:
    if 'red' in run.done():
        return run.log('skip red')
    proc = run_suite(run, names, agent_dir)
    if proc.returncode == 0:
        raise Stop('red-gate', 'the new tests passed before the agent was built',
                   'The tests do not describe anything new. Read them, then rerun with a new --run-id.', tail(proc.stdout))
    output = proc.stdout + proc.stderr
    # 1 = tests failed, 2 = a test module failed to import. 4 is a usage error, except
    # when conftest itself imports the agent that does not exist yet. 5 = nothing collected.
    missing_agent = proc.returncode == 4 and 'while loading conftest' in output and 'Error' in output
    if proc.returncode not in (1, 2) and not missing_agent:
        raise Stop('red-gate', f'pytest exited {proc.returncode}, which is not a test failure',
                   'Read the output and fix the tests by hand.', tail(proc.stdout + proc.stderr))
    (run.run_dir / 'tests.snapshot.json').write_text(json.dumps(
        {p: h for p, h in snapshot(agent_dir).items() if p.startswith('tests/')}, indent=1))
    (run.run_dir / 'red.txt').write_text(proc.stdout + proc.stderr)
    run.mark('red')
    summary = [line for line in output.splitlines() if re.search(r'\d+ (failed|errors?)\b|Error while|ImportError', line)]
    run.log(f'RED gate: the suite fails before the build ({summary[-1].strip() if summary else tail(output, 1)})')


def quality_problems(run: Run, spec: dict[str, Any], names: Names, agent_dir: Path) -> list[str]:
    problems = []
    surfaces = set(spec['surfaces'])
    required = ['README.md', '.env.example', '.gitignore', 'requirements.txt', 'pytest.ini', 'agent_cli.py',
                'agent_env.py', 'agent_llm.py', f'{names.base}_core.py', f'{names.base}_service.py',
                f'{names.base}_chat.py', f'{names.base}_agent.py', 'memory/memory.py', 'memory/data/.gitkeep',
                'tests/conftest.py', *[f'tools/{a["name"]}.py' for a in spec['actions']]]
    required += ['api/main.py'] if 'api' in surfaces else []
    required += ['ui/app.py'] if 'ui' in surfaces else []
    required += [f'subagents/{spec["subagent"]["name"]}.py'] if spec.get('subagent') else []
    problems += [f'missing {p}' for p in required if not (agent_dir / p).is_file()]
    if not list((agent_dir / 'skills').glob('*.md')):
        problems.append('no skill Markdown in skills/')
    # A reference file emptied out still says "this is the notes agent". Remove it, don't stub it.
    stale = [p for p in REFERENCE_FILES if (agent_dir / p).exists() and p not in required]
    problems += [f'{p} is a reference file; remove it (mv it to its new name, or delete it)' for p in stale]
    expected_top = {Path(p).parts[0] for p in required} | {'tests', 'skills', 'tools', 'subagents', 'ui', 'api', 'memory'}
    problems += [f'{p.name}: unexpected file at the top of the agent folder' for p in sorted(agent_dir.iterdir())
                 if p.is_file() and p.name not in expected_top]

    for path in sorted(agent_dir.rglob('*')):
        rel = path.relative_to(agent_dir)
        if not path.is_file() or SKIP_DIRS.intersection(rel.parts):
            continue
        if path.name in ('.env', '.env.local'):
            problems.append(f'{rel} must not exist in the agent folder')
        if rel.parts[:2] == ('memory', 'data') and path.name != '.gitkeep':
            problems.append(f'{rel}: data files do not belong in the agent folder')
        if path.suffix in TEXT_SUFFIXES or path.name.startswith('.env'):
            for n, line in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                if LEFTOVERS.search(line) and 'note' not in names.name:
                    problems.append(f'{rel}:{n}: reference name left over: {line.strip()[:80]}')
    for n, line in enumerate((agent_dir / '.env.example').read_text().splitlines() if (agent_dir / '.env.example').exists() else [], 1):
        if line.strip() and not line.lstrip().startswith('#') and line.split('=', 1)[-1].strip():
            problems.append(f'.env.example:{n} sets a value; keep names only')
    if problems:
        return problems

    proc = run_suite(run, names, agent_dir)
    passed = int(m.group(1)) if (m := re.search(r'(\d+) passed', proc.stdout)) else 0
    defined = sum(len(re.findall(r'^\s*def test_', p.read_text(encoding='utf-8'), re.M))
                  for p in (agent_dir / 'tests').glob('test_*.py') if p.name != 'test_browser.py')
    if proc.returncode != 0:
        return [f'GREEN gate: the suite fails\n{tail(proc.stdout + proc.stderr, 40)}']
    if passed < defined or re.search(r'\d+ (skipped|xfailed|deselected)', proc.stdout):
        return [f'GREEN gate: {passed} passed for {defined} test functions, or tests were skipped: {tail(proc.stdout, 1)}']
    run.log(f'GREEN gate: {tail(proc.stdout, 1)}')
    return smoke_problems(run, spec, names, agent_dir)


def smoke_problems(run: Run, spec: dict[str, Any], names: Names, agent_dir: Path) -> list[str]:
    """Start what a person would start. A 404 is a failure, not a sign of life."""
    problems = []
    with tempfile.TemporaryDirectory() as data:
        env = agent_env(names, Path(data))

        def call(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run([run.python, *args], cwd=agent_dir, env=env, capture_output=True, text=True, timeout=60)

        cli = f'{names.base}_agent.py'
        if 'usage' not in (proc := call(cli, '--help')).stdout.lower() or proc.returncode != 0:
            problems.append(f'{cli} --help fails: {tail(proc.stderr, 3)}')
        command = next((c for c in spec.get('offline_commands', []) if '<' not in c), None)
        if command and ((proc := call(cli, '--offline', command)).returncode != 0 or not proc.stdout.strip()):
            problems.append(f'{cli} --offline "{command}" fails: {tail(proc.stderr, 3)}')
        for action in spec['actions']:
            if (proc := call(f'tools/{action["name"]}.py', '--help')).returncode != 0:
                problems.append(f'tools/{action["name"]}.py --help fails: {tail(proc.stderr, 3)}')
        if 'api' in spec['surfaces']:
            problems += serve(run, agent_dir, env, 'api/main.py', 'API_PORT', '/health', 'API')
        if 'ui' in spec['surfaces']:
            problems += serve(run, agent_dir, env, 'ui/app.py', 'PORT', '/', 'UI', want_html=True)
    if not problems:
        run.log('smoke: CLI, tools' + (', API' if 'api' in spec['surfaces'] else '')
                + (' and UI' if 'ui' in spec['surfaces'] else '') + ' start and answer')
    return problems


def serve(run: Run, agent_dir: Path, env: dict[str, str], script: str, port_var: str, path: str, label: str,
          want_html: bool = False) -> list[str]:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    proc = subprocess.Popen([run.python, script], cwd=agent_dir, env={**env, port_var: str(port)},
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(40):
            time.sleep(0.25)
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=2) as resp:
                    body = resp.read().decode('utf-8', errors='replace').lower()
                    if resp.status == 200 and (not want_html or '<html' in body):
                        return []
                    return [f'{label} GET {path} answered {resp.status} without the expected content']
            except OSError:
                if proc.poll() is not None:
                    break
        proc.terminate()
        return [f'{label} did not answer GET {path} on 127.0.0.1:{port}: {tail(proc.stderr.read() if proc.stderr else "", 5)}']
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def parse_verdict(text: str) -> dict[str, Any] | None:
    """The last JSON object in the reply that is a well-formed verdict. Prose may contain braces too."""
    decoder = json.JSONDecoder()
    found = None
    for start in (i for i, ch in enumerate(text) if ch == '{'):
        try:
            data, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get('verdict') in ('approve', 'changes') and isinstance(data.get('findings'), list):
            found = data
    return found


def stage_build_and_review(run: Run, spec: dict[str, Any], names: Names, agent_dir: Path) -> None:
    if 'review' in run.done():
        return run.log('skip build and review')
    attempts_file = run.run_dir / 'attempts'
    feedback_file = run.run_dir / 'feedback.md'
    green_file = run.run_dir / 'green'  # holds the attempt that passed every gate and awaits review

    while True:
        attempt = int(attempts_file.read_text()) if attempts_file.exists() else 0
        if green_file.exists() and green_file.read_text() == str(attempt):
            run.log(f'skip build attempt {attempt}: it passed its gates, resuming at review')
        else:
            attempt += 1
            if attempt > run.args.max_attempts:
                raise Stop('build', f'not done after {run.args.max_attempts} attempts',
                           'Read feedback.md. Fix by hand, or raise --max-attempts and rerun.')
            attempts_file.write_text(str(attempt))
            problems = build(run, spec, names, agent_dir, attempt, feedback_file)
            if problems:
                feedback_file.write_text('\n'.join(f'- {p}' for p in problems) + '\n', encoding='utf-8')
                run.log(f'build attempt {attempt}: {len(problems)} problem(s), sent back; first: {problems[0].splitlines()[0]}')
                continue
            green_file.write_text(str(attempt))

        verdict = review(run, spec, names, agent_dir, attempt)
        if verdict['verdict'] == 'approve':
            run.mark('review')
            run.log(f'review: approve on attempt {attempt}' + (f' with {len(verdict["findings"])} note(s)' if verdict['findings'] else ''))
            return
        green_file.unlink()
        feedback_file.write_text('\n'.join(f'- review: {f}' for f in verdict['findings']) + '\n', encoding='utf-8')
        run.log(f'review: changes requested on attempt {attempt}: {verdict["findings"][0] if verdict["findings"] else "(no findings given)"}')


def build(run: Run, spec: dict[str, Any], names: Names, agent_dir: Path, attempt: int, feedback_file: Path) -> list[str]:
    """One build attempt. Scope violations stop the run; quality problems are returned."""
    frozen = json.loads((run.run_dir / 'tests.snapshot.json').read_text())
    spec_text = json.dumps(spec, indent=2)
    feedback = feedback_file.read_text(encoding='utf-8') if feedback_file.exists() else ''
    prompt = prompt_for('build', SPEC=spec_text, AGENT_DIR=str(agent_dir), KIT=str(run.kit), BASE=names.base,
                        PREFIX=names.prefix, TOOLS=', '.join(f'tools/{a["name"]}.py' for a in spec['actions']),
                        TEST_CMD=' '.join(test_command(run)), ATTEMPT=str(attempt), MAX_ATTEMPTS=str(run.args.max_attempts),
                        FAILURES=f'The previous attempt was sent back for these reasons. Fix them first:\n\n{feedback}' if feedback else '')
    repo_before = snapshot(REPO)
    run_agent(run, 'build', prompt, cwd=agent_dir, writes=True, max_turns=150,
              tools=['Read', 'Glob', 'Grep', 'Edit', 'Write', f'Bash({run.python} -m pytest:*)',
                     f'Bash({run.python} -m py_compile:*)', 'Bash(mv:*)', 'Bash(mkdir:*)', 'Bash(ls:*)'],
              extra_env={'FACTORY_SPEC': spec_text, 'FACTORY_ATTEMPT': str(attempt)})

    # Scope gates: these stop the run. Asking again does not undo them.
    check_outside(run, 'build', names, repo_before)
    remove_listed(run, agent_dir)
    now = {p: h for p, h in snapshot(agent_dir).items() if p.startswith('tests/')}
    if (touched := changed(frozen, now)):
        raise Stop('build', 'the build changed the frozen tests',
                   'The tests no longer prove anything. Delete the folder and rerun with a new --run-id.',
                   '\n'.join(touched))

    # Quality gates: these send the work back.
    return quality_problems(run, spec, names, agent_dir)


def remove_listed(run: Run, agent_dir: Path) -> None:
    """Delete what the build listed in .factory-remove. The agent cannot delete; the script can, inside its limits."""
    listing = agent_dir / '.factory-remove'
    if not listing.exists():
        return
    refused = []
    for line in listing.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        root = agent_dir.resolve()
        target = (root / line.strip()).resolve()
        rel = target.relative_to(root) if target.is_relative_to(root) else None
        if rel is None or rel.parts[:1] == ('tests',) or not target.is_file():
            refused.append(line.strip())
            continue
        target.unlink()
        run.log(f'build: removed {rel} as listed')
    listing.unlink()
    if refused:
        raise Stop('build', 'the build asked to remove files outside its folder, in tests/, or that are not files',
                   'Read the list; the factory deletes only files in the agent folder outside tests/.', '\n'.join(refused))


def review(run: Run, spec: dict[str, Any], names: Names, agent_dir: Path, attempt: int) -> dict[str, Any]:
    """A fresh, read-only session. Only a JSON verdict counts."""
    repo_before = snapshot(REPO)
    reviewed = snapshot(agent_dir)
    text = run_agent(run, 'review', prompt_for('review', SPEC=json.dumps(spec, indent=2), AGENT_DIR=str(agent_dir), KIT=str(run.kit)),
                     cwd=agent_dir, tools=['Read', 'Glob', 'Grep'], writes=False, max_turns=60,
                     extra_env={'FACTORY_ATTEMPT': str(attempt)})
    check_outside(run, 'review', names, repo_before)
    if (edited := changed(reviewed, snapshot(agent_dir))):
        raise Stop('review', 'the review changed files', 'A reviewer only reads. Inspect the changes by hand.',
                   '\n'.join(edited))
    verdict = parse_verdict(text)
    if verdict is None:
        raise Stop('review', 'the review returned no valid verdict', 'Read review.out.txt and decide yourself.')
    (run.run_dir / 'review.json').write_text(json.dumps(verdict, indent=2) + '\n')
    return verdict


def stage_handoff(run: Run, spec: dict[str, Any], names: Names, agent_dir: Path) -> None:
    if 'handoff' in run.done():
        return run.log('skip handoff')
    verdict = json.loads((run.run_dir / 'review.json').read_text())
    notes = '\n'.join(f'- {f}' for f in verdict['findings']) or '- none'
    attempts = (run.run_dir / 'attempts').read_text().strip()
    (run.run_dir / 'handoff.md').write_text(f"""# {names.name}: ready for a person

Built by the agent factory in `{agent_dir}`, from the contract in `spec.json`.
Nothing is committed: the folder is untracked in the agent kit.

## What the factory checked

- The tests were written first, failed before the build (`red.txt`) and were
  not changed afterwards.
- Offline test suite passes without a provider key, against a temporary data dir.
- The reference's structure is kept, with no `example_`/note names, `.env`
  files or data files left in the folder.
- `{names.base}_agent.py --help`, the offline CLI, one `--help` per tool
  ({', '.join(a['name'] for a in spec['actions'])}){', the API health check' if 'api' in spec['surfaces'] else ''}{' and the UI home page' if 'ui' in spec['surfaces'] else ''} start and answer.
- An independent, read-only review approved it on build attempt {attempts}.

Review notes:

{notes}

## What a person still does (agent kit AGENTS.md, steps 6 and 7)

1. Read `README.md`: is this the contract you meant?
2. Run the browser tests: `pip install playwright && playwright install chromium`,
   then `python -m pytest tests/test_browser.py`.
3. Use the UI and chat in a real browser, with and without a provider key.
4. Commit the folder in the agent kit and add it to the "Registered agents"
   table in `AGENTS.md`. Or delete it.

Agent cost for this run: ${run.spent():.2f}.
""", encoding='utf-8')
    run.mark('handoff')
    run.log(f'handoff: {run.run_dir / "handoff.md"}')


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def write_stop(run: Run, stop: Stop) -> None:
    (run.run_dir / 'stop.md').write_text(
        f'# Stopped\n\nstage={stop.stage}\nreason: {stop.reason}\n\n'
        + (f'```\n{stop.details}\n```\n\n' if stop.details else '')
        + f'Decision needed: {stop.decision}\n\nAgent cost so far: ${run.spent():.2f}\n', encoding='utf-8')
    run.log(f'STOP at {stop.stage}: {stop.reason}')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a new agent in agent-example format, with gates in code',
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument('--spec', type=Path, help='agent contract (see rehearsals/agent-specs/)')
    what.add_argument('--idea', help='one-sentence idea; the spec stage turns it into a contract')
    parser.add_argument('--kit', type=Path, default=REPO.parent / 'agent-example',
                        help='agent-example checkout (default: ../agent-example)')
    parser.add_argument('--backend', choices=['claude', 'codex', 'opencode', 'fake'], default='claude')
    parser.add_argument('--model', default=None)
    parser.add_argument('--python', default=sys.executable,
                        help="Python with the agent's requirements installed (default: this one)")
    parser.add_argument('--max-attempts', type=int, default=3, help='build attempts, review rounds included')
    parser.add_argument('--max-cost-usd', type=float, default=20.0, help='stop before an agent call once spent')
    parser.add_argument('--stage-timeout', type=int, default=1800, help='seconds per agent call')
    parser.add_argument('--run-id', help='run folder name under rehearsals/agent-runs/')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    kit = args.kit.resolve()
    if not (kit / 'example-agent').is_dir() or not (kit / 'AGENTS.md').is_file():
        print(f'error: {kit} is not an agent-example checkout.\n'
              f'  git clone https://github.com/ModernPath/agent-example {kit}', file=sys.stderr)
        return 2
    if args.spec:
        try:
            run_id = args.run_id or json.loads(args.spec.read_text())['name']
        except (OSError, ValueError, KeyError) as exc:
            print(f'error: cannot read the agent name from {args.spec}: {exc}', file=sys.stderr)
            return 2
    else:
        run_id = args.run_id or re.sub(r'[^a-z0-9]+', '-', args.idea.lower()).strip('-')[:40]
    run = Run(args=args, kit=kit, run_dir=RUNS / run_id, python=args.python)
    run.run_dir.mkdir(parents=True, exist_ok=True)
    (run.run_dir / 'stop.md').unlink(missing_ok=True)

    if 'handoff' in run.done():
        run.log(f'already done: {run.run_dir / "handoff.md"}')
        return 0
    if 'copy' not in run.done() and (dirty := kit_changes_outside(kit, '\0')):
        print(f'error: the agent kit has uncommitted changes; commit or stash them first:\n  '
              + '\n  '.join(dirty[:10]), file=sys.stderr)
        return 2

    run.log(f'agent factory: backend={args.backend} model={args.model or "default"} kit={kit}')
    try:
        spec = stage_spec(run)
        names = names_for(spec)
        agent_dir = kit / names.name
        stage_copy(run, names, agent_dir)
        stage_tests(run, spec, names, agent_dir)
        stage_red(run, names, agent_dir)
        stage_build_and_review(run, spec, names, agent_dir)
        stage_handoff(run, spec, names, agent_dir)
    except Stop as stop:
        write_stop(run, stop)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
