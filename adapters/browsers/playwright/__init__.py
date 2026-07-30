"""Safe, read-only Playwright runtime adapter."""

from .domain_policy import DomainPolicy, DomainPolicyError
from .runner import ReadOnlyTaskError, run_read_only_task, validate_read_only_task

__all__ = [
    "DomainPolicy",
    "DomainPolicyError",
    "ReadOnlyTaskError",
    "run_read_only_task",
    "validate_read_only_task",
]
