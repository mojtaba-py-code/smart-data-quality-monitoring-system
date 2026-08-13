"""Data-profiling service.

Produces a :class:`DatasetProfile` describing the shape and per-column
statistics of a dataset. The profile feeds the scorer, the report generators,
and the dashboard, so it is computed once and reused everywhere.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dqms.core.interfaces import AnalysisComponent
from dqms.models.profile import ColumnProfile, DatasetProfile
from dqms.utils.logging import get_logger

_logger = get_logger("dqms.profiler")


def _to_float(value: object) -> float | None:
    """Convert a numpy/pandas scalar to a plain float, or ``None`` if invalid."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if np.isnan(result) or np.isinf(result) else result


class DataProfiler(AnalysisComponent):
    """Compute descriptive statistics for a dataset."""

    def analyze(self, frame: pd.DataFrame) -> DatasetProfile:
        """Profile ``frame`` and return a :class:`DatasetProfile`."""
        _logger.info("Profiling dataset with shape {}", frame.shape)
        row_count = len(frame)
        # Positional access keeps one Series per column even when a dataset
        # carries repeated column labels.
        column_profiles = [
            self._profile_column(frame.iloc[:, position], row_count)
            for position in range(frame.shape[1])
        ]

        duplicate_count = int(frame.duplicated().sum())
        total_cells = int(frame.size)
        missing_cells = int(frame.isna().sum().sum())

        profile = DatasetProfile(
            row_count=row_count,
            column_count=int(frame.shape[1]),
            total_memory_bytes=int(frame.memory_usage(deep=True).sum()),
            duplicate_row_count=duplicate_count,
            duplicate_row_ratio=duplicate_count / row_count if row_count else 0.0,
            total_cells=total_cells,
            missing_cells=missing_cells,
            missing_ratio=missing_cells / total_cells if total_cells else 0.0,
            columns=column_profiles,
        )
        _logger.success("Profiled {} columns", len(column_profiles))
        return profile

    def _profile_column(self, series: pd.Series, row_count: int) -> ColumnProfile:
        """Build a :class:`ColumnProfile` for a single column."""
        non_null = series.dropna()
        null_count = int(series.isna().sum())
        unique_count = int(series.nunique(dropna=True))
        is_numeric = bool(pd.api.types.is_numeric_dtype(series)) and not pd.api.types.is_bool_dtype(
            series
        )

        mode_value, top_frequency = self._mode_and_frequency(non_null)

        numeric_stats: dict[str, float | None] = {
            "minimum": None,
            "maximum": None,
            "mean": None,
            "median": None,
            "std_dev": None,
        }
        if is_numeric and not non_null.empty:
            numeric = pd.to_numeric(non_null, errors="coerce").dropna()
            if not numeric.empty:
                numeric_stats = {
                    "minimum": _to_float(numeric.min()),
                    "maximum": _to_float(numeric.max()),
                    "mean": _to_float(numeric.mean()),
                    "median": _to_float(numeric.median()),
                    "std_dev": _to_float(numeric.std(ddof=1)) if len(numeric) > 1 else 0.0,
                }

        return ColumnProfile(
            name=str(series.name),
            dtype=str(series.dtype),
            count=int(non_null.shape[0]),
            null_count=null_count,
            null_ratio=null_count / row_count if row_count else 0.0,
            unique_count=unique_count,
            cardinality_ratio=unique_count / row_count if row_count else 0.0,
            memory_bytes=int(series.memory_usage(deep=True)),
            is_numeric=is_numeric,
            mode=mode_value,
            top_frequency=top_frequency,
            **numeric_stats,
        )

    def _mode_and_frequency(self, non_null: pd.Series) -> tuple[str | None, int | None]:
        """Return the most frequent value (as text) and its frequency."""
        if non_null.empty:
            return None, None
        counts = non_null.value_counts()
        if counts.empty:
            return None, None
        top_value = counts.index[0]
        return str(top_value), int(counts.iloc[0])
