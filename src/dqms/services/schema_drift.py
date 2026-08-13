"""Schema-drift detection service.

Compares the *structure* of two datasets - their columns and dtypes - and
reports what was added, removed, or changed. This is the first line of defence
in a monitoring pipeline: a renamed or retyped column usually breaks downstream
consumers before any statistical drift is even relevant.
"""

from __future__ import annotations

import pandas as pd

from dqms.core.exceptions import DuplicateColumnError
from dqms.models.drift import SchemaDriftReport, SchemaFieldChange
from dqms.utils.logging import get_logger

_logger = get_logger("dqms.schema_drift")


def ensure_unique_columns(frame: pd.DataFrame, role: str) -> None:
    """Raise :class:`DuplicateColumnError` if ``frame`` repeats a column label.

    Drift detection matches columns between two datasets *by name*, so repeated
    labels would make the comparison ambiguous. Failing loudly - and pointing at
    the ``clean`` command, which de-duplicates labels - is safer than silently
    comparing an arbitrary pair.
    """
    labels = [str(label) for label in frame.columns]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise DuplicateColumnError(
            f"the {role} dataset repeats one or more column labels, so columns cannot be "
            "matched unambiguously; run `dqms clean` on it first",
            details={"dataset": role, "duplicate_columns": duplicates},
        )


class SchemaDriftDetector:
    """Detect structural differences between a baseline and current dataset."""

    def compare(self, baseline: pd.DataFrame, current: pd.DataFrame) -> SchemaDriftReport:
        """Return a :class:`SchemaDriftReport` describing structural drift.

        Parameters
        ----------
        baseline:
            The reference dataset (for example, last known-good schema).
        current:
            The dataset being checked against the baseline.

        Raises
        ------
        DuplicateColumnError
            If either dataset repeats a column label.
        """
        ensure_unique_columns(baseline, "baseline")
        ensure_unique_columns(current, "current")

        baseline_cols = list(baseline.columns)
        current_cols = list(current.columns)
        baseline_set = set(baseline_cols)
        current_set = set(current_cols)

        added = [col for col in current_cols if col not in baseline_set]
        removed = [col for col in baseline_cols if col not in current_set]
        shared = [col for col in baseline_cols if col in current_set]

        dtype_changes: list[SchemaFieldChange] = []
        stable: list[str] = []
        for col in shared:
            baseline_dtype = str(baseline[col].dtype)
            current_dtype = str(current[col].dtype)
            if baseline_dtype != current_dtype:
                dtype_changes.append(
                    SchemaFieldChange(
                        column=str(col),
                        change_type="dtype_changed",
                        baseline_dtype=baseline_dtype,
                        current_dtype=current_dtype,
                    )
                )
            else:
                stable.append(str(col))

        report = SchemaDriftReport(
            added_columns=[str(c) for c in added],
            removed_columns=[str(c) for c in removed],
            dtype_changes=dtype_changes,
            stable_columns=stable,
        )
        _logger.info(
            "Schema comparison: +{} -{} ~{} columns",
            len(added),
            len(removed),
            len(dtype_changes),
        )
        return report
