from datetime import date

import pytest

from app.tasks import Task, ValidationError, create_task, summary


def test_creates_a_task_with_a_cleaned_title():
    task = create_task("  Call Bob  ", due=date(2026, 10, 9))
    assert task == Task(title="Call Bob", due=date(2026, 10, 9))


def test_sr_1_1_title_is_required():
    with pytest.raises(ValidationError, match="Title is required"):
        create_task("   ")


def test_sr_1_2_due_date_must_be_a_date():
    with pytest.raises(ValidationError, match="Due date"):
        create_task("Call Bob", due="tomorrow")


def test_summary_counts_open_done_and_overdue():
    tasks = [
        Task("a", due=date(2026, 10, 1)),
        Task("b", due=date(2026, 10, 20)),
        Task("c", done=True, due=date(2026, 9, 1)),
    ]
    assert summary(tasks, today=date(2026, 10, 8)) == {"total": 3, "done": 1, "open": 2, "overdue": 1}
