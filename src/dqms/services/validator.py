"""Data-validation service.

Applies a battery of configurable rules to a dataset and returns a structured
:class:`ValidationReport`. Each rule is a small, self-contained method, which
keeps the class open for extension (add a method, register it) but closed for
modification of existing behaviour.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dqms.config.settings import Settings, get_settings
from dqms.core.constants import Severity
from dqms.core.interfaces import AnalysisComponent
from dqms.models.validation import ValidationIssue, ValidationReport
from dqms.utils.logging import get_logger
from dqms.utils.patterns import column_matches_hint, is_valid_email, is_valid_phone

_logger = get_logger("dqms.validator")

# Cap on the number of row indices stored per issue to bound memory usage.
_MAX_ROW_INDICES = 100


class DataValidator(AnalysisComponent):
    """Detect data-quality violations across a dataset."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def analyze(self, frame: pd.DataFrame) -> ValidationReport:
        """Run every rule against ``frame`` and aggregate the issues."""
        _logger.info("Validating dataset with shape {}", frame.shape)
        issues: list[ValidationIssue] = []

        # Columns are addressed positionally so that datasets carrying repeated
        # column labels (legal in pandas) yield one Series per column rather
        # than a DataFrame slice.
        for position, label in enumerate(frame.columns):
            column = str(label)
            series = frame.iloc[:, position]
            issues.extend(self._check_missing(column, series))
            issues.extend(self._check_empty_and_whitespace(column, series))
            issues.extend(self._check_wrong_type(column, series))
            issues.extend(self._check_range_and_sign(column, series))
            issues.extend(self._check_string_length(column, series))
            issues.extend(self._check_emails(column, series))
            issues.extend(self._check_phones(column, series))
            issues.extend(self._check_dates(column, series))

        issues.extend(self._check_duplicates(frame))

        total_affected = sum(issue.affected_count for issue in issues)
        _logger.success("Validation complete: {} issue groups", len(issues))
        return ValidationReport(
            row_count=len(frame),
            total_issues=total_affected,
            issues=issues,
        )

    # -- individual rules --------------------------------------------------

    def _check_missing(self, column: str, series: pd.Series) -> list[ValidationIssue]:
        """Flag null/NaN values."""
        mask = series.isna()
        if not mask.any():
            return []
        return [
            self._issue(
                column,
                "missing_values",
                Severity.WARNING,
                f"Column '{column}' contains missing values",
                mask,
            )
        ]

    def _check_empty_and_whitespace(
        self, column: str, series: pd.Series
    ) -> list[ValidationIssue]:
        """Flag empty strings and values with leading/trailing whitespace."""
        if not pd.api.types.is_object_dtype(series) and not pd.api.types.is_string_dtype(series):
            return []
        text = series.dropna().astype(str)
        if text.empty:
            return []

        issues: list[ValidationIssue] = []
        empty_mask = series.isin(["", " "]) | (
            series.notna() & series.astype(str).str.strip().eq("")
        )
        if empty_mask.any():
            issues.append(
                self._issue(
                    column,
                    "empty_strings",
                    Severity.WARNING,
                    f"Column '{column}' contains empty or blank strings",
                    empty_mask,
                )
            )

        stripped = series.astype(str)
        whitespace_mask = series.notna() & stripped.ne(stripped.str.strip())
        if whitespace_mask.any():
            issues.append(
                self._issue(
                    column,
                    "whitespace",
                    Severity.INFO,
                    f"Column '{column}' has values with leading/trailing whitespace",
                    whitespace_mask,
                )
            )
        return issues

    def _check_wrong_type(self, column: str, series: pd.Series) -> list[ValidationIssue]:
        """Flag text columns that are numeric except for a few bad values."""
        if not (
            pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)
        ):
            return []
        if pd.api.types.is_numeric_dtype(series):
            return []
        non_null = series.dropna()
        if non_null.empty:
            return []
        coerced = pd.to_numeric(non_null, errors="coerce")
        convertible = coerced.notna().mean()
        # If most values parse as numbers, the residual non-numeric ones are
        # very likely data-entry errors rather than a genuine text column.
        if convertible >= 0.9:
            bad_mask = series.notna() & pd.to_numeric(series, errors="coerce").isna()
            if bad_mask.any():
                return [
                    self._issue(
                        column,
                        "wrong_type",
                        Severity.ERROR,
                        f"Column '{column}' looks numeric but has non-numeric values",
                        bad_mask,
                    )
                ]
        return []

    def _check_range_and_sign(self, column: str, series: pd.Series) -> list[ValidationIssue]:
        """Flag negative values and values outside the configured range."""
        if not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
            return []
        cfg = self._settings.validation
        issues: list[ValidationIssue] = []

        if cfg.treat_negative_as_invalid:
            negative_mask = series < 0
            if negative_mask.any():
                issues.append(
                    self._issue(
                        column,
                        "negative_values",
                        Severity.ERROR,
                        f"Column '{column}' contains negative values",
                        negative_mask.fillna(False),
                    )
                )

        if cfg.numeric_min is not None:
            below = series < cfg.numeric_min
            if below.any():
                issues.append(
                    self._issue(
                        column,
                        "below_minimum",
                        Severity.ERROR,
                        f"Column '{column}' has values below {cfg.numeric_min}",
                        below.fillna(False),
                    )
                )
        if cfg.numeric_max is not None:
            above = series > cfg.numeric_max
            if above.any():
                issues.append(
                    self._issue(
                        column,
                        "above_maximum",
                        Severity.ERROR,
                        f"Column '{column}' has values above {cfg.numeric_max}",
                        above.fillna(False),
                    )
                )
        return issues

    def _check_string_length(self, column: str, series: pd.Series) -> list[ValidationIssue]:
        """Flag abnormally long strings, which often signal malformed data."""
        if not pd.api.types.is_object_dtype(series) and not pd.api.types.is_string_dtype(series):
            return []
        limit = self._settings.validation.max_string_length
        long_mask = series.notna() & series.astype(str).str.len().gt(limit)
        if long_mask.any():
            return [
                self._issue(
                    column,
                    "string_too_long",
                    Severity.WARNING,
                    f"Column '{column}' has strings longer than {limit} characters",
                    long_mask,
                )
            ]
        return []

    def _check_emails(self, column: str, series: pd.Series) -> list[ValidationIssue]:
        """Validate email-like columns."""
        if not column_matches_hint(column, self._settings.validation.email_column_hints):
            return []
        non_null = series.dropna()
        if non_null.empty:
            return []
        invalid_mask = series.notna() & ~series.astype(str).map(is_valid_email)
        if invalid_mask.any():
            return [
                self._issue(
                    column,
                    "invalid_email",
                    Severity.ERROR,
                    f"Column '{column}' contains invalid email addresses",
                    invalid_mask,
                )
            ]
        return []

    def _check_phones(self, column: str, series: pd.Series) -> list[ValidationIssue]:
        """Validate phone-like columns."""
        if not column_matches_hint(column, self._settings.validation.phone_column_hints):
            return []
        non_null = series.dropna()
        if non_null.empty:
            return []
        invalid_mask = series.notna() & ~series.astype(str).map(is_valid_phone)
        if invalid_mask.any():
            return [
                self._issue(
                    column,
                    "invalid_phone",
                    Severity.ERROR,
                    f"Column '{column}' contains invalid phone numbers",
                    invalid_mask,
                )
            ]
        return []

    def _check_dates(self, column: str, series: pd.Series) -> list[ValidationIssue]:
        """Validate date-like columns by attempting to parse them."""
        if not column_matches_hint(column, self._settings.validation.date_column_hints):
            return []
        if pd.api.types.is_datetime64_any_dtype(series):
            return []
        non_null = series.dropna()
        if non_null.empty:
            return []
        parsed = pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=False)
        invalid_mask = series.notna() & parsed.isna()
        if invalid_mask.any():
            return [
                self._issue(
                    column,
                    "invalid_date",
                    Severity.ERROR,
                    f"Column '{column}' contains unparseable dates",
                    invalid_mask,
                )
            ]
        return []

    def _check_duplicates(self, frame: pd.DataFrame) -> list[ValidationIssue]:
        """Flag fully duplicated rows."""
        mask = frame.duplicated(keep="first")
        if not mask.any():
            return []
        return [
            self._issue(
                None,
                "duplicate_rows",
                Severity.WARNING,
                "Dataset contains fully duplicated rows",
                mask,
            )
        ]

    # -- helpers -----------------------------------------------------------

    def _issue(
        self,
        column: str | None,
        rule: str,
        severity: Severity,
        message: str,
        mask: pd.Series,
    ) -> ValidationIssue:
        """Build a :class:`ValidationIssue` from a boolean mask.

        Row numbers are recorded as zero-based *positions* rather than index
        labels, so the issue stays meaningful (and JSON-serialisable) for frames
        with a string, datetime, or otherwise non-integer index.
        """
        positions = np.flatnonzero(mask.fillna(False).to_numpy(dtype=bool))
        return ValidationIssue(
            column=column,
            rule=rule,
            severity=severity,
            message=message,
            affected_count=int(positions.size),
            row_indices=[int(i) for i in positions[:_MAX_ROW_INDICES]],
        )
