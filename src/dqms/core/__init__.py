"""Domain core: framework-independent contracts, constants, and errors."""

from __future__ import annotations

from dqms.core.exceptions import (
    ConfigurationError,
    DataQualityError,
    DuplicateColumnError,
    FileAccessError,
    FileTooLargeError,
    ReportGenerationError,
    SecurityError,
    UnsupportedFormatError,
    ValidationRuleError,
)

__all__ = [
    "ConfigurationError",
    "DataQualityError",
    "DuplicateColumnError",
    "FileAccessError",
    "FileTooLargeError",
    "ReportGenerationError",
    "SecurityError",
    "UnsupportedFormatError",
    "ValidationRuleError",
]
