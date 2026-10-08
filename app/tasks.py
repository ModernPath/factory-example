"""A small task list: the application the factory changes.

Deliberately tiny, so the factory's work is easy to read. The recurring
development task here is "add a validation rule to task creation": each rule
lives in `validate_new_task` and has its own test in `app/tests/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional


class ValidationError(ValueError):
    """A new task breaks one of the creation rules. The message says which."""


@dataclass(frozen=True)
class Task:
    title: str
    due: Optional[date] = None
    done: bool = False


def validate_new_task(title: str, due: Optional[date]) -> str:
    """Apply every creation rule and return the cleaned title."""
    cleaned = (title or "").strip()
    # SR-1.1: a task needs a title.
    if not cleaned:
        raise ValidationError("Title is required.")
    # SR-1.2: the due date, when given, is a date.
    if due is not None and not isinstance(due, date):
        raise ValidationError("Due date must be a date.")
    return cleaned


def create_task(title: str, due: Optional[date] = None) -> Task:
    return Task(title=validate_new_task(title, due), due=due)


def summary(tasks: Iterable[Task], today: date) -> dict:
    """Counts for the task list header."""
    items = list(tasks)
    return {
        "total": len(items),
        "done": sum(1 for t in items if t.done),
        "open": sum(1 for t in items if not t.done),
        "overdue": sum(1 for t in items if not t.done and t.due is not None and t.due < today),
    }
