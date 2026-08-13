"""Exception hierarchy for the Data Quality Monitoring System.

A single, well-defined hierarchy lets callers catch broad categories
(:class:`DataQualityError`) or specific failures without depending on the
underlying libraries (pandas, pyarrow, ...). Every error carries a human
readable message and, optionally, a machine-friendly ``details`` mapping that
higher layers (CLI, dashboard, API) can render without re-parsing strings.
"""

from __future__ import annotations

from typing import Any


class DataQualityError(Exception):
    """Base class for every error raised inside the DQMS package.

    Parameters
    ----------
    message:
        Human readable description of what went wrong.
    details:
        Optional structured context (file name, column, rule id, ...). It is
        kept separate from the message so it can be logged or serialised
        without string parsing.
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.details:
            return f"{self.message} | context={self.details}"
        return self.message


class ConfigurationError(DataQualityError):
    """Raised when configuration is missing, malformed, or internally invalid."""


class FileAccessError(DataQualityError):
    """Raised when a dataset file cannot be located, opened, or read."""


class FileTooLargeError(FileAccessError):
    """Raised when a file exceeds the configured maximum size."""


class UnsupportedFormatError(DataQualityError):
    """Raised when a file extension / content type is not supported."""


class ValidationRuleError(DataQualityError):
    """Raised when a validation rule is misconfigured or cannot be applied."""


class DuplicateColumnError(DataQualityError):
    """Raised when an operation cannot be performed on repeated column labels.

    pandas permits a DataFrame to carry the same column label more than once.
    Analysis that reports per-column results copes with this by addressing
    columns positionally, but operations that *match* columns across two
    datasets (schema and data drift) become ambiguous, so they refuse instead of
    silently comparing an arbitrary pair.
    """


class ReportGenerationError(DataQualityError):
    """Raised when an HTML/PDF/summary report cannot be produced."""


class SecurityError(DataQualityError):
    """Raised when an operation would violate a security boundary.

    Examples include path-traversal attempts, disallowed file extensions,
    symlink escapes, and formula-injection detection during export.
    """
