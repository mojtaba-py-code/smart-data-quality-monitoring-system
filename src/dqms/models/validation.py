"""Validation result models."""

from __future__ import annotations

from pydantic import Field

from dqms.core.constants import Severity
from dqms.models.base import ResultModel


class ValidationIssue(ResultModel):
    """A single detected data-quality problem.

    ``row_indices`` holds zero-based row *positions* (not index labels, which
    need not be integers) and is capped by the validator to avoid unbounded
    memory use on very dirty datasets; ``affected_count`` always reflects the
    true total.
    """

    column: str | None
    rule: str
    severity: Severity
    message: str
    affected_count: int = Field(ge=0)
    row_indices: list[int] = Field(
        default_factory=list, description="Zero-based row positions, truncated to a sample"
    )


class ColumnValidation(ResultModel):
    """Roll-up of all issues detected for one column."""

    column: str
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def error_count(self) -> int:
        """Number of issues at ERROR or CRITICAL severity."""
        return sum(
            issue.affected_count
            for issue in self.issues
            if issue.severity in (Severity.ERROR, Severity.CRITICAL)
        )


class ValidationReport(ResultModel):
    """Complete validation outcome for a dataset."""

    row_count: int = Field(ge=0)
    total_issues: int = Field(ge=0)
    issues: list[ValidationIssue] = Field(default_factory=list)

    def by_severity(self, severity: Severity) -> list[ValidationIssue]:
        """Return all issues at a given severity level."""
        return [issue for issue in self.issues if issue.severity == severity]

    def by_column(self, column: str) -> list[ValidationIssue]:
        """Return all issues affecting a specific column."""
        return [issue for issue in self.issues if issue.column == column]

    @property
    def has_blocking_issues(self) -> bool:
        """Whether any CRITICAL issue was detected."""
        return any(issue.severity is Severity.CRITICAL for issue in self.issues)
