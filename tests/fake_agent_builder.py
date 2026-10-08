#!/usr/bin/env python3
"""A stand-in for the agent in rehearsals/05_agent_factory.py, so its gates can be tested for free.

The factory runs it with --backend fake. It reads the stage from FACTORY_STAGE
and behaves well unless FACTORY_FAKE_<STAGE>=<behaviour> asks otherwise:

  spec:   good | invalid | blocked
  tests:  good | touches_code | online | misses_action | passes | no_tests
  build:  good | touches_tests | touches_kit | leftovers | broken | broken_once | fails | slow
          | skips | missing_tool | secrets | ui_port | stubs | junk | removes | removes_tests
  review: good | changes | changes_once | garbage | edits | fails | prose
  any:    expensive (reports a high cost)

"Good" work is a mechanical rename of the notes reference into memo-agent
(note -> memo, example -> memo), which is a real, working agent: the factory's
gates run its real test suite and start its real API and UI.
"""

import json
import os
import time
from pathlib import Path

STAGE = os.environ['FACTORY_STAGE']
RUN = Path(os.environ['FACTORY_RUN'])
KIT = Path(os.environ['FACTORY_KIT'])
BEHAVIOUR = os.environ.get(f'FACTORY_FAKE_{STAGE.upper()}', 'good')
ATTEMPT = int(os.environ.get('FACTORY_ATTEMPT', '1'))
HERE = Path('.')  # the factory starts us in the agent folder (the kit for the spec stage)

RENAMES = [
    ('example-agent', 'memo-agent'), ('EXAMPLE_AGENT', 'MEMO_AGENT'), ('Example Agent', 'Memo Agent'),
    ('example_', 'memo_'), ('Example', 'Memo'), ('NOTE', 'MEMO'), ('Note', 'Memo'), ('note', 'memo'),
]


def rename(text: str) -> str:
    for old, new in RENAMES:
        text = text.replace(old, new)
    return text


def rename_tree(root: Path, include) -> None:
    for path in sorted(root.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        rel = path.relative_to(root).as_posix()
        if not path.is_file() or '__pycache__' in rel or not include(rel):
            continue
        text = path.read_text(encoding='utf-8')
        path.write_text(rename(text), encoding='utf-8')
        target = root / rename(rel)
        if target != path:
            target.parent.mkdir(parents=True, exist_ok=True)
            path.rename(target)


def in_tests(rel: str) -> bool:
    return rel.startswith('tests/')


def act() -> str:
    if STAGE == 'spec':
        spec = json.loads((Path(__file__).resolve().parent.parent / 'rehearsals/agent-specs/memo-agent.json').read_text())
        if BEHAVIOUR == 'invalid':
            spec['name'] = 'Memo Agent'
        if BEHAVIOUR == 'blocked':
            spec = {'blocked': 'Should memos expire?'}
        (RUN / 'spec.json').write_text(json.dumps(spec))
        return 'Wrote the contract.'

    if STAGE == 'tests':
        tests = HERE / 'tests'
        if BEHAVIOUR == 'passes':
            conftest = tests / 'conftest.py'
            conftest.write_text(conftest.read_text() + '\n# MEMO_AGENT: add_memo search_memos delete_memo\n')
            return 'Tests written.'
        if BEHAVIOUR == 'no_tests':  # names everything, collects nothing
            for path in tests.glob('*.py'):
                path.unlink()
            (tests / 'conftest.py').write_text(
                'def pytest_configure():\n    pass\n\n\ndef env(monkeypatch):\n'
                '    monkeypatch.setenv("MEMO_AGENT_OFFLINE", "1")\n    monkeypatch.setenv("MEMO_AGENT_DATA_DIR", "x")\n')
            (tests / 'test_core.py').write_text('# add_memo search_memos delete_memo\n')
            return 'Tests written.'
        rename_tree(HERE, in_tests)
        if BEHAVIOUR == 'touches_code':
            (HERE / 'example_core.py').write_text((HERE / 'example_core.py').read_text() + '\n# was here\n')
        if BEHAVIOUR == 'online':
            conftest = tests / 'conftest.py'
            conftest.write_text(conftest.read_text().replace('monkeypatch.setenv(OFFLINE_ENV, "1")', 'pass'))
        if BEHAVIOUR == 'misses_action':
            for path in tests.glob('*.py'):
                path.write_text(path.read_text().replace('delete_memo', 'remove_memo'))
        return 'Tests written.'

    if STAGE == 'build':
        if BEHAVIOUR == 'fails':
            raise RuntimeError('simulated agent failure')
        if BEHAVIOUR == 'slow':
            time.sleep(30)
        rename_tree(HERE, lambda rel: not in_tests(rel))
        if BEHAVIOUR == 'touches_tests':
            core = HERE / 'tests' / 'test_core.py'
            core.write_text(core.read_text() + '\n\ndef test_extra():\n    assert True\n')
        if BEHAVIOUR == 'touches_kit':
            agents_md = KIT / 'AGENTS.md'
            agents_md.write_text(agents_md.read_text() + '\n| memo-agent | registered by the build | done |\n')
        if BEHAVIOUR == 'skips':  # pytest.ini is not frozen: deselect what fails
            ini = HERE / 'pytest.ini'
            ini.write_text(ini.read_text() + 'addopts = -k "not search"\n')
        if BEHAVIOUR == 'missing_tool':
            (HERE / 'tools' / 'delete_memo.py').unlink()
        if BEHAVIOUR == 'secrets':
            (HERE / '.env').write_text('GEMINI_API_KEY=not-a-real-key\n')
            env = HERE / '.env.example'
            env.write_text(env.read_text() + 'GEMINI_API_KEY=not-a-real-key\n')
        if BEHAVIOUR == 'ui_port':  # ignores PORT, so it is not where the smoke check looks
            app = HERE / 'ui' / 'app.py'
            app.write_text(app.read_text().replace('int(os.environ.get("PORT", DEFAULT_PORT))', 'DEFAULT_PORT'))
        if BEHAVIOUR == 'stubs':  # what a real run did when it could not delete
            (HERE / 'example_core.py').write_text('# Removed. Use memo_core.py instead.\n')
        if BEHAVIOUR == 'junk':
            (HERE / '_check.txt').write_text('test\n')
        if BEHAVIOUR == 'removes':
            (HERE / '_scratch.txt').write_text('scratch\n')
            (HERE / '.factory-remove').write_text('_scratch.txt\n')
        if BEHAVIOUR == 'removes_tests':
            (HERE / '.factory-remove').write_text('tests/test_core.py\n')
        if BEHAVIOUR == 'leftovers':
            env = HERE / '.env.example'
            env.write_text(env.read_text() + '# EXAMPLE_AGENT_MODEL=\n')
        core = HERE / 'memo_core.py'
        if BEHAVIOUR == 'broken' or (BEHAVIOUR == 'broken_once' and ATTEMPT == 1):
            core.write_text(core.read_text().replace('Memo title is required.', 'Missing title.'))
        else:  # a later attempt fixes what the feedback named
            core.write_text(core.read_text().replace('Missing title.', 'Memo title is required.'))
        return 'Built memo-agent.'

    if STAGE == 'review':
        if BEHAVIOUR == 'fails':
            raise RuntimeError('simulated agent failure')
        if BEHAVIOUR == 'garbage':
            return 'Looks good to me!'
        if BEHAVIOUR == 'prose':  # braces in the prose before the verdict, as a real review wrote
            return ('Chat tool errors are returned as {"error": ...} rather than raised.\n\n'
                    '{"verdict": "approve", "findings": []}')
        if BEHAVIOUR == 'edits':
            readme = HERE / 'README.md'
            readme.write_text(readme.read_text() + '\nReviewed.\n')
        if BEHAVIOUR == 'changes' or (BEHAVIOUR == 'changes_once' and ATTEMPT == 1):
            return json.dumps({'verdict': 'changes', 'findings': ['memo_service.py: delete skips the id check']})
        return 'Reviewed.\n{"verdict": "approve", "findings": []}'

    raise SystemExit(f'unknown stage {STAGE}')


def main() -> None:
    with open(RUN / 'fake-calls', 'a') as calls:
        calls.write(f'{STAGE}\n')
    cost = 9.0 if BEHAVIOUR == 'expensive' else 0.01
    try:
        result = {'is_error': False, 'subtype': 'success', 'result': act()}
    except RuntimeError as exc:
        result = {'is_error': True, 'subtype': 'error_during_execution', 'result': str(exc)}
    result['total_cost_usd'] = cost
    print(json.dumps(result))


if __name__ == '__main__':
    main()
