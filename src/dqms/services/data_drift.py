"""Data-drift detection service.

Compares the *distributions* of two datasets column by column and quantifies how
far the current data has moved from a historical baseline. The headline metric
is the Population Stability Index (PSI); it is complemented by a
Kolmogorov-Smirnov test for numeric columns and simple moment comparisons
(mean, median, variance) plus pairwise correlation shifts.
"""

from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd

from dqms.config.settings import Settings, get_settings
from dqms.models.drift import ColumnDrift, DataDriftReport
from dqms.services.schema_drift import ensure_unique_columns
from dqms.utils.logging import get_logger

_logger = get_logger("dqms.data_drift")

# Small constant that keeps PSI finite when a bin is empty in one dataset.
_PSI_EPSILON = 1e-6
_MIN_OBSERVATIONS = 8


class DataDriftDetector:
    """Detect distributional drift between historical and current data."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def compare(self, baseline: pd.DataFrame, current: pd.DataFrame) -> DataDriftReport:
        """Return a :class:`DataDriftReport` comparing two datasets.

        Raises
        ------
        DuplicateColumnError
            If either dataset repeats a column label.
        """
        ensure_unique_columns(baseline, "baseline")
        ensure_unique_columns(current, "current")

        shared = [col for col in baseline.columns if col in set(current.columns)]
        _logger.info("Comparing distributions across {} shared column(s)", len(shared))

        column_drifts: list[ColumnDrift] = []
        for col in shared:
            base_series = baseline[col]
            curr_series = current[col]
            if pd.api.types.is_numeric_dtype(base_series) and pd.api.types.is_numeric_dtype(
                curr_series
            ):
                column_drifts.append(self._numeric_drift(str(col), base_series, curr_series))
            else:
                column_drifts.append(self._categorical_drift(str(col), base_series, curr_series))

        correlation_changes = self._correlation_changes(baseline, current, shared)

        return DataDriftReport(
            baseline_rows=len(baseline),
            current_rows=len(current),
            columns=column_drifts,
            correlation_changes=correlation_changes,
        )

    # -- numeric -----------------------------------------------------------

    def _numeric_drift(
        self, column: str, baseline: pd.Series, current: pd.Series
    ) -> ColumnDrift:
        """Compare two numeric distributions."""
        base = baseline.dropna().astype(float)
        curr = current.dropna().astype(float)

        if len(base) < _MIN_OBSERVATIONS or len(curr) < _MIN_OBSERVATIONS:
            return ColumnDrift(column=column, is_numeric=True)

        psi = self._numeric_psi(base, curr)
        ks_stat, ks_p = self._ks_test(base, curr)
        severity, drift_detected = self._grade_drift(psi, ks_p)

        return ColumnDrift(
            column=column,
            is_numeric=True,
            psi=psi,
            ks_statistic=ks_stat,
            ks_pvalue=ks_p,
            mean_change=round(float(curr.mean() - base.mean()), 6),
            median_change=round(float(curr.median() - base.median()), 6),
            variance_change=round(float(curr.var(ddof=1) - base.var(ddof=1)), 6),
            drift_detected=drift_detected,
            severity=severity,
        )

    def _numeric_psi(self, baseline: pd.Series, current: pd.Series) -> float:
        """Population Stability Index using quantile bins from the baseline."""
        bins = self._settings.drift.numeric_bins
        quantiles = np.linspace(0, 1, bins + 1)
        edges = np.unique(baseline.quantile(quantiles).to_numpy())
        if len(edges) < 2:
            return 0.0
        edges[0], edges[-1] = -np.inf, np.inf

        base_counts, _ = np.histogram(baseline, bins=edges)
        curr_counts, _ = np.histogram(current, bins=edges)
        base_ratio = base_counts / max(base_counts.sum(), 1)
        curr_ratio = curr_counts / max(curr_counts.sum(), 1)

        base_ratio = np.clip(base_ratio, _PSI_EPSILON, None)
        curr_ratio = np.clip(curr_ratio, _PSI_EPSILON, None)
        psi = float(np.sum((curr_ratio - base_ratio) * np.log(curr_ratio / base_ratio)))
        return round(psi, 6)

    def _ks_test(
        self, baseline: pd.Series, current: pd.Series
    ) -> tuple[float | None, float | None]:
        """Two-sample Kolmogorov-Smirnov test, if SciPy is available."""
        try:
            from scipy import stats
        except ImportError:  # pragma: no cover - optional dependency guard
            return None, None
        result = stats.ks_2samp(baseline.to_numpy(), current.to_numpy())
        return round(float(result.statistic), 6), round(float(result.pvalue), 6)

    # -- categorical -------------------------------------------------------

    def _categorical_drift(
        self, column: str, baseline: pd.Series, current: pd.Series
    ) -> ColumnDrift:
        """Compare two categorical distributions using PSI over categories."""
        base = baseline.dropna().astype(str)
        curr = current.dropna().astype(str)
        if base.empty or curr.empty:
            return ColumnDrift(column=column, is_numeric=False)

        categories = sorted(set(base.unique()) | set(curr.unique()))
        base_ratio = base.value_counts(normalize=True).reindex(categories, fill_value=0.0)
        curr_ratio = curr.value_counts(normalize=True).reindex(categories, fill_value=0.0)

        base_arr = np.clip(base_ratio.to_numpy(), _PSI_EPSILON, None)
        curr_arr = np.clip(curr_ratio.to_numpy(), _PSI_EPSILON, None)
        psi = round(float(np.sum((curr_arr - base_arr) * np.log(curr_arr / base_arr))), 6)
        severity, drift_detected = self._grade_drift(psi, None)

        return ColumnDrift(
            column=column,
            is_numeric=False,
            psi=psi,
            drift_detected=drift_detected,
            severity=severity,
        )

    # -- shared ------------------------------------------------------------

    def _grade_drift(self, psi: float | None, ks_pvalue: float | None) -> tuple[str, bool]:
        """Derive ``(severity, drift_detected)`` from PSI and the KS p-value."""
        cfg = self._settings.drift
        value = psi or 0.0
        if value >= cfg.psi_critical:
            severity, detected = "critical", True
        elif value >= cfg.psi_warning:
            severity, detected = "warning", True
        else:
            severity, detected = "none", False

        # A significant KS result is evidence of drift even when the binned PSI
        # stays inside its warning band.
        if ks_pvalue is not None and ks_pvalue < cfg.ks_pvalue_alpha:
            detected = True
            if severity == "none":
                severity = "warning"
        return severity, detected

    def _correlation_changes(
        self, baseline: pd.DataFrame, current: pd.DataFrame, shared: list[str]
    ) -> dict[str, float]:
        """Absolute change in pairwise Pearson correlation for numeric columns."""
        numeric_cols = [
            col
            for col in shared
            if pd.api.types.is_numeric_dtype(baseline[col])
            and pd.api.types.is_numeric_dtype(current[col])
        ]
        if len(numeric_cols) < 2:
            return {}

        base_corr = baseline[numeric_cols].corr()
        curr_corr = current[numeric_cols].corr()
        changes: dict[str, float] = {}
        for i, left in enumerate(numeric_cols):
            for right in numeric_cols[i + 1 :]:
                base_value = base_corr.loc[left, right]
                curr_value = curr_corr.loc[left, right]
                if pd.notna(base_value) and pd.notna(curr_value):
                    # Correlation coefficients are always floats; cast so the
                    # arithmetic is typed rather than pandas' scalar union.
                    delta = abs(cast(float, curr_value) - cast(float, base_value))
                    changes[f"{left}|{right}"] = round(delta, 6)
        return changes
