"""The agent factory's gates (rehearsals/05_agent_factory.py), tested against a fake agent.

Each test copies the agent kit (agent-example's example-agent, AGENTS.md and
README.md) into a fresh git repository and runs the factory with
--backend fake. The fake's good work is a real agent (the notes reference
renamed to memo-agent), so the GREEN gate and the smoke checks run real tests
and start a real API and UI. The test then checks that the right gate stopped
the run and that stop.md says why.

Needs an agent-example checkout next to this repository (or AGENT_KIT), and a
Python with the agent's requirements (or AGENT_PYTHON); skipped otherwise.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FACTORY = REPO / "rehearsals" / "05_agent_factory.py"
MEMO_SPEC = REPO / "rehearsals" / "agent-specs" / "memo-agent.json"
KIT_SOURCE = Path(os.environ.get("AGENT_KIT", REPO.parent / "agent-example"))
AGENT_PYTHON = os.environ.get("AGENT_PYTHON", sys.executable)


def _agent_python_ready() -> bool:
    probe = "import fastapi, flask, dotenv, uvicorn, httpx, requests, google.genai"
    return subprocess.run([AGENT_PYTHON, "-c", probe], capture_output=True).returncode == 0


pytestmark = [
    pytest.mark.skipif(not (KIT_SOURCE / "example-agent").is_dir(), reason=f"no agent-example checkout at {KIT_SOURCE}"),
    pytest.mark.skipif(importlib.util.find_spec("pytest") is None or not _agent_python_ready(),
                       reason="AGENT_PYTHON lacks agent-example's requirements"),
]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def kit(tmp_path: Path) -> Path:
    root = tmp_path / "agent-example"
    ignore = shutil.ignore_patterns(".venv", "__pycache__", ".pytest_cache", "notes.json", ".env", ".env.local")
    shutil.copytree(KIT_SOURCE / "example-agent", root / "example-agent", ignore=ignore)
    for name in ("AGENTS.md", "README.md"):
        shutil.copy(KIT_SOURCE / name, root / name)
    git(root, "init", "-q", "-b", "main")
    git(root, "-c", "user.email=f@example.invalid", "-c", "user.name=F", "add", "-A")
    git(root, "-c", "user.email=f@example.invalid", "-c", "user.name=F", "commit", "-qm", "kit")
    return root


@pytest.fixture
def runs(tmp_path: Path) -> Path:
    return tmp_path / "runs"


@pytest.fixture
def factory(kit: Path, runs: Path):
    def run(*args: str, spec_file: Path = MEMO_SPEC, **fake: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "FACTORY_AGENT_RUNS": str(runs)}
        env.update({f"FACTORY_FAKE_{stage.upper()}": behaviour for stage, behaviour in fake.items()})
        command = [sys.executable, str(FACTORY), "--kit", str(kit), "--backend", "fake", "--python", AGENT_PYTHON]
        command += [] if "--idea" in args else ["--spec", str(spec_file)]
        return subprocess.run([*command, *args], cwd=REPO, env=env, capture_output=True, text=True, timeout=120)

    return run


def run_dir(runs: Path, run_id: str = "memo-agent") -> Path:
    return runs / run_id


def calls(runs: Path, run_id: str = "memo-agent") -> list:
    path = run_dir(runs, run_id) / "fake-calls"
    return path.read_text().split() if path.exists() else []


def assert_stopped(proc, runs: Path, stage: str, reason: str, run_id: str = "memo-agent") -> str:
    assert proc.returncode == 1, proc.stdout + proc.stderr
    stop = (run_dir(runs, run_id) / "stop.md").read_text()
    assert f"stage={stage}" in stop and reason in stop, stop
    assert "Decision needed:" in stop
    return stop


class TestHappyPath:
    def test_contract_becomes_a_tested_agent_in_the_kit(self, factory, kit, runs):
        proc = factory()
        assert proc.returncode == 0, proc.stdout + proc.stderr
        rd = run_dir(runs)
        assert calls(runs) == ["tests", "build", "review"]
        assert [line.split()[0] for line in (rd / "state").read_text().splitlines()] == \
            ["spec", "copy", "tests", "red", "review", "handoff"]
        log = (rd / "log").read_text()
        assert "RED gate: the suite fails before the build" in log
        assert "GREEN gate: 60 passed" in log
        assert "smoke: CLI, tools, API and UI start and answer" in log
        # The new agent is in the kit, uncommitted; nothing else in the kit changed.
        assert git(kit, "status", "--porcelain") == "?? memo-agent/"
        assert (kit / "memo-agent" / "memo_core.py").is_file()
        assert not (kit / "memo-agent" / "evals").exists()
        assert "Commit the folder in the agent kit" in (rd / "handoff.md").read_text()

    def test_an_idea_goes_through_the_spec_stage(self, factory, runs):
        proc = factory("--idea", "keep short memos", "--run-id", "memo-idea")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert calls(runs, "memo-idea") == ["spec", "tests", "build", "review"]

    def test_rerun_after_done_does_nothing_twice(self, factory, runs):
        factory()
        proc = factory()
        assert proc.returncode == 0 and "already done" in proc.stdout
        assert calls(runs) == ["tests", "build", "review"]


class TestContractAndTestGates:
    @pytest.mark.parametrize("behaviour, reason", [
        ("invalid", '"name" must be kebab case'),
        ("blocked", "BLOCKED: Should memos expire?"),
    ])
    def test_spec_gate(self, factory, runs, behaviour, reason):
        proc = factory("--idea", "keep short memos", "--run-id", "memo-idea", spec=behaviour)
        assert_stopped(proc, runs, "spec", reason, run_id="memo-idea")

    @pytest.mark.parametrize("behaviour, reason", [
        ("touches_code", "changed files outside tests/"),
        ("online", "does not force offline mode"),
        ("misses_action", "no test names the action(s) delete_memo"),
    ])
    def test_tests_gate(self, factory, runs, behaviour, reason):
        assert_stopped(factory(tests=behaviour), runs, "tests", reason)
        assert "build" not in calls(runs)

    def test_red_gate_stops_an_empty_suite(self, factory, runs):
        assert_stopped(factory(tests="no_tests"), runs, "red-gate", "pytest exited 5, which is not a test failure")

    def test_red_gate_stops_tests_that_already_pass(self, factory, runs):
        assert_stopped(factory(tests="passes"), runs, "red-gate", "passed before the agent was built")
        assert "build" not in calls(runs)

    def test_refuses_a_folder_that_already_exists(self, factory, kit, runs):
        (kit / "memo-agent").mkdir()
        # An empty folder is invisible to git, so the dirty-kit check passes; the copy gate still sees it.
        assert_stopped(factory(), runs, "copy", "already exists")


class TestScopeGatesStopTheRun:
    def test_build_may_not_touch_the_frozen_tests(self, factory, runs):
        stop = assert_stopped(factory(build="touches_tests"), runs, "build", "changed the frozen tests")
        assert "tests/test_core.py" in stop
        assert "review" not in calls(runs)

    def test_build_may_not_touch_the_kit(self, factory, runs):
        stop = assert_stopped(factory(build="touches_kit"), runs, "build", "changed files outside memo-agent/")
        assert "kit: AGENTS.md" in stop

    def test_refuses_to_start_on_a_dirty_kit(self, factory, kit, runs):
        (kit / "AGENTS.md").write_text("local edit\n")
        proc = factory()
        assert proc.returncode == 2 and "uncommitted changes" in proc.stderr
        assert not (kit / "memo-agent").exists()


class TestQualityGatesSendWorkBack:
    def test_a_failing_suite_gets_another_attempt(self, factory, runs):
        proc = factory(build="broken_once")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert calls(runs) == ["tests", "build", "build", "review"]
        assert "build attempt 1: 1 problem(s), sent back; first: GREEN gate: the suite fails" in (run_dir(runs) / "log").read_text()
        assert "The previous attempt was sent back" in (run_dir(runs) / "build.prompt.md").read_text()

    def test_attempts_are_bounded(self, factory, runs):
        assert_stopped(factory("--max-attempts", "2", build="broken"), runs, "build", "not done after 2 attempts")
        assert calls(runs) == ["tests", "build", "build"]
        assert "GREEN gate" in (run_dir(runs) / "feedback.md").read_text()

    def test_skipped_tests_are_not_green(self, factory, runs):
        assert_stopped(factory("--max-attempts", "1", build="skips"), runs, "build", "not done after 1 attempts")
        assert "deselected" in (run_dir(runs) / "feedback.md").read_text()

    def test_structure(self, factory, runs):
        assert_stopped(factory("--max-attempts", "1", build="missing_tool"), runs, "build", "not done after 1 attempts")
        assert "missing tools/delete_memo.py" in (run_dir(runs) / "feedback.md").read_text()

    def test_no_secrets_in_the_agent_folder(self, factory, runs):
        assert_stopped(factory("--max-attempts", "1", build="secrets"), runs, "build", "not done after 1 attempts")
        feedback = (run_dir(runs) / "feedback.md").read_text()
        assert ".env must not exist in the agent folder" in feedback
        assert "sets a value; keep names only" in feedback

    def test_ui_must_answer_where_it_was_asked_to_listen(self, factory, runs):
        assert_stopped(factory("--max-attempts", "1", build="ui_port"), runs, "build", "not done after 1 attempts")
        assert "UI did not answer GET /" in (run_dir(runs) / "feedback.md").read_text()

    def test_stubbed_reference_files_are_not_removed(self, factory, runs):
        assert_stopped(factory("--max-attempts", "1", build="stubs"), runs, "build", "not done after 1 attempts")
        assert "example_core.py is a reference file; remove it" in (run_dir(runs) / "feedback.md").read_text()

    def test_no_stray_files(self, factory, runs):
        assert_stopped(factory("--max-attempts", "1", build="junk"), runs, "build", "not done after 1 attempts")
        assert "_check.txt: unexpected file" in (run_dir(runs) / "feedback.md").read_text()

    def test_the_factory_deletes_what_the_build_lists(self, factory, kit, runs):
        proc = factory(build="removes")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "build: removed _scratch.txt as listed" in (run_dir(runs) / "log").read_text()
        assert not (kit / "memo-agent" / "_scratch.txt").exists()
        assert not (kit / "memo-agent" / ".factory-remove").exists()

    def test_the_factory_will_not_delete_tests(self, factory, kit, runs):
        stop = assert_stopped(factory(build="removes_tests"), runs, "build", "asked to remove files")
        assert "tests/test_core.py" in stop
        assert (kit / "memo-agent" / "tests" / "test_core.py").exists()

    def test_leftover_reference_names(self, factory, runs):
        assert_stopped(factory("--max-attempts", "1", build="leftovers"), runs, "build", "not done after 1 attempts")
        assert ".env.example" in (run_dir(runs) / "feedback.md").read_text()
        assert "reference name left over: # EXAMPLE_AGENT_MODEL=" in (run_dir(runs) / "feedback.md").read_text()


class TestReview:
    def test_changes_go_back_to_build(self, factory, runs):
        proc = factory(review="changes_once")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert calls(runs) == ["tests", "build", "review", "build", "review"]
        assert "- review: memo_service.py: delete skips the id check" in (run_dir(runs) / "build.prompt.md").read_text()

    def test_changes_within_the_last_attempt_stop(self, factory, runs):
        assert_stopped(factory("--max-attempts", "1", review="changes"), runs, "build", "not done after 1 attempts")

    def test_review_only_reads(self, factory, runs):
        stop = assert_stopped(factory(review="edits"), runs, "review", "the review changed files")
        assert "README.md" in stop

    def test_a_verdict_after_prose_with_braces_counts(self, factory, runs):
        proc = factory(review="prose")
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_review_must_return_a_valid_verdict(self, factory, runs):
        assert_stopped(factory(review="garbage"), runs, "review", "no valid verdict")


class TestBudgetsAndResume:
    def test_stage_timeout(self, factory, runs):
        assert_stopped(factory("--stage-timeout", "2", build="slow"), runs, "build", "timed out after 2s")

    def test_run_budget(self, factory, runs):
        assert_stopped(factory("--max-cost-usd", "5", tests="expensive"), runs, "build", "budget of $5 is used up")

    def test_a_failed_review_resumes_without_rebuilding(self, factory, runs):
        assert factory(review="fails").returncode == 1
        proc = factory()
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert calls(runs) == ["tests", "build", "review", "review"]
        assert "skip build attempt 1: it passed its gates" in (run_dir(runs) / "log").read_text()

    def test_failed_stage_resumes_without_redoing_finished_ones(self, factory, runs):
        assert factory(build="fails").returncode == 1
        assert calls(runs) == ["tests", "build"]
        proc = factory()
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert calls(runs) == ["tests", "build", "build", "review"]
        log = (run_dir(runs) / "log").read_text()
        assert "skip copy" in log and "skip tests" in log and "skip red" in log
        assert json.loads((run_dir(runs) / "review.json").read_text())["verdict"] == "approve"
