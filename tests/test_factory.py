"""The factory's gates, tested against a fake agent.

Each test copies the app and the factory into a fresh git repository and runs
`bash factory/run.sh` with FACTORY_BACKEND=fake. The fake agent behaves well
unless a test asks one stage to misbehave; the test then checks that the right
gate stopped the run, that stop.md says why, and that nothing leaked onto main.
A gate proves itself only by being seen to fire.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

import pytest

REPO = Path(__file__).resolve().parent.parent
FAKE_AGENT = REPO / "tests" / "fake_agent.py"
ISSUE_001 = "factory/issues/001-title-max-length.md"
ISSUE_002 = "factory/issues/002-blank-title-rejected.md"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(REPO / "app", root / "app", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO / "factory", root / "factory", ignore=shutil.ignore_patterns("runs", "example-runs"))
    shutil.copy(REPO / ".gitignore", root / ".gitignore")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "factory@example.invalid")
    git(root, "config", "user.name", "Factory Test")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "initial")
    return root


def run(project: Path, issue: str = ISSUE_001, **fake: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "FACTORY_BACKEND": "fake", "FACTORY_FAKE_AGENT": str(FAKE_AGENT),
           "FACTORY_TEST_CMD": f"{sys.executable} -m pytest -q -p no:cacheprovider app/tests"}
    for key, value in fake.items():
        env[key if key.startswith("FACTORY_") else f"FACTORY_FAKE_{key.upper()}"] = value
    return subprocess.run(["bash", "factory/run.sh", issue], cwd=project, env=env, capture_output=True, text=True, timeout=120)


def run_dir(project: Path, run_id: str = "001-title-max-length") -> Path:
    return project / "factory" / "runs" / run_id


def calls(project: Path, run_id: str = "001-title-max-length") -> list:
    path = run_dir(project, run_id) / "fake-calls"
    return path.read_text().split() if path.exists() else []


def assert_stopped(proc, project: Path, stage: str, reason: str, run_id: str = "001-title-max-length") -> str:
    assert proc.returncode == 1, proc.stdout + proc.stderr
    stop = (run_dir(project, run_id) / "stop.md").read_text()
    assert f"stage={stage}" in stop and reason in stop, stop
    assert "Decision needed:" in stop
    # Nothing follows the person back: we are on main, main is untouched, the tree is clean.
    assert git(project, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git(project, "log", "--oneline", "main").count("\n") == 0
    assert git(project, "status", "--porcelain") == ""
    return stop


class TestHappyPath:
    def test_issue_becomes_a_reviewed_change_with_pr_text(self, project):
        proc = run(project)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        rd = run_dir(project)
        assert calls(project) == ["spec", "test", "implement", "review"]
        assert [line.split()[0] for line in (rd / "state").read_text().splitlines()] == ["spec", "test", "red", "implement", "review", "pr"]
        assert "Draft: a person decides whether to merge" in (rd / "pr.md").read_text()
        # Two commits on the factory branch, none on main, and we are back on main.
        assert git(project, "rev-list", "--count", "main..factory/001-title-max-length") == "2"
        assert git(project, "rev-parse", "--abbrev-ref", "HEAD") == "main"
        assert "RED gate: test_sr_1_3_title_at_most_80_characters fails as expected" in (rd / "log").read_text()

    def test_rerun_after_done_does_nothing_twice(self, project):
        run(project)
        pr_before = (run_dir(project) / "pr.md").read_text()
        proc = run(project)
        assert proc.returncode == 0
        assert calls(project) == ["spec", "test", "implement", "review"]  # no new agent calls
        assert (run_dir(project) / "pr.md").read_text() == pr_before
        assert git(project, "rev-list", "--count", "main..factory/001-title-max-length") == "2"


class TestGatesStopTheRun:
    def test_red_gate_stops_when_the_behaviour_already_exists(self, project):
        proc = run(project, ISSUE_002, test="existing")
        stop = assert_stopped(proc, project, "red-gate", "passed before implementation", run_id="002-blank-title-rejected")
        assert "Close the issue" in stop
        assert "implement" not in calls(project, "002-blank-title-rejected")
        assert not (run_dir(project, "002-blank-title-rejected") / "pr.md").exists()

    def test_red_gate_stops_when_something_else_is_broken(self, project):
        tests = project / "app/tests/test_tasks.py"
        tests.write_text(tests.read_text().replace('"total": 3', '"total": 99'))
        git(project, "commit", "-qam", "break an existing test")
        proc = run(project, ISSUE_002, test="existing")
        assert proc.returncode == 1
        assert "not because of test_sr_1_1_blank_title_is_rejected" in (run_dir(project, "002-blank-title-rejected") / "stop.md").read_text()

    @pytest.mark.parametrize("behaviour, reason", [
        ("missing", "spec.md is missing"),
        ("blocked", "BLOCKED: Should the limit count characters or bytes?"),
        ("touches_repo", "the spec stage changed repository files"),
    ])
    def test_spec_gate(self, project, behaviour, reason):
        assert_stopped(run(project, spec=behaviour), project, "spec", reason)

    @pytest.mark.parametrize("behaviour, reason", [
        ("two_tests", "expected exactly one new test, found 2"),
        ("touches_app", "changed files outside app/tests/"),
        ("edits_existing", "changed or deleted existing test lines"),
    ])
    def test_test_gate(self, project, behaviour, reason):
        assert_stopped(run(project, test=behaviour), project, "test", reason)

    def test_implementer_may_not_touch_tests(self, project):
        stop = assert_stopped(run(project, implement="touches_tests"), project, "implement", "touched files it may not change")
        assert "app/tests/test_tasks.py" in stop
        rejected = (run_dir(project) / "rejected-implement.patch").read_text()
        assert 'create_task("x" * 80)' in rejected  # the evidence is kept for a person
        # The branch holds only the test commit; the rejected work is not on it.
        assert git(project, "rev-list", "--count", "main..factory/001-title-max-length") == "1"

    def test_green_gate(self, project):
        assert_stopped(run(project, implement="broken"), project, "green-gate", "the suite fails after implementation")

    def test_verdict_gate(self, project):
        stop = assert_stopped(run(project, review="changes"), project, "verdict-gate", "error message differs from the issue")
        assert not (run_dir(project) / "pr.md").exists()

    def test_review_must_return_a_valid_verdict(self, project):
        assert_stopped(run(project, review="garbage"), project, "review", "no valid verdict")


class TestBudgetsAndResume:
    def test_stage_timeout(self, project):
        proc = run(project, implement="slow", FACTORY_STAGE_TIMEOUT="2")
        assert_stopped(proc, project, "implement", "timed out after 2s")

    def test_run_budget(self, project):
        proc = run(project, spec="expensive", test="expensive", FACTORY_MAX_COST_USD="3")
        assert_stopped(proc, project, "implement", "budget of $3 is used up")

    def test_failed_stage_resumes_without_redoing_finished_ones(self, project):
        assert run(project, implement="fails").returncode == 1
        assert calls(project) == ["spec", "test", "implement"]
        proc = run(project)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert calls(project) == ["spec", "test", "implement", "implement", "review"]
        log = (run_dir(project) / "log").read_text()
        assert "skip spec" in log and "skip test" in log and "skip red" in log

    def test_a_new_run_id_starts_fresh(self, project):
        run(project)
        proc = run(project, FACTORY_RUN_ID="001-second-try")
        assert proc.returncode == 0
        assert calls(project, "001-second-try") == ["spec", "test", "implement", "review"]

    def test_refuses_to_start_on_a_dirty_tree(self, project):
        (project / "app/tasks.py").write_text("# local edit\n")
        proc = run(project)
        assert proc.returncode == 2 and "uncommitted changes" in proc.stderr
        assert not (run_dir(project) / "fake-calls").exists()
