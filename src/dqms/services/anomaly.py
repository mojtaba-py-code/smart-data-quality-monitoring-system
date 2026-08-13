"""Anomaly-detection service.

Three complementary strategies are offered:

* **Z-score** and **IQR** are univariate and interpretable - they flag values
  that sit far from the centre of a single column's distribution.
* **Isolation Forest** is multivariate - it flags rows that are unusual when all
  numeric columns are considered together, catching anomalies that no single
  column reveals.

Which strategies run is configuration-driven, so the service is trivial to tune
per dataset without code changes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dqms.config.settings import Settings, get_settings
from dqms.core.constants import AnomalyMethod
from dqms.models.anomaly import AnomalyReport, ColumnAnomaly
from dqms.utils.logging import get_logger

_logger = get_logger("dqms.anomaly")

# Minimum non-null observations before a statistical test is meaningful.
_MIN_OBSERVATIONS = 8
_MAX_ROW_INDICES = 100


class AnomalyDetector:
    """Detect anomalous values and rows in a dataset."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def detect(self, frame: pd.DataFrame) -> AnomalyReport:
        """Run the configured anomaly-detection methods over ``frame``."""
        cfg = self._settings.anomaly
        numeric = frame.select_dtypes(include=[np.number]).drop(
            columns=[c for c in frame.columns if pd.api.types.is_bool_dtype(frame[c])],
            errors="ignore",
        )
        _logger.info("Running anomaly detection on {} numeric column(s)", numeric.shape[1])

        column_results: list[ColumnAnomaly] = []
        multivariate_indices: list[int] = []

        for method in cfg.methods:
            if method is AnomalyMethod.ZSCORE:
                column_results.extend(self._zscore(numeric))
            elif method is AnomalyMethod.IQR:
                column_results.extend(self._iqr(numeric))
            elif method is AnomalyMethod.ISOLATION_FOREST:
                multivariate_indices = self._isolation_forest(numeric)

        return AnomalyReport(
            row_count=len(frame),
            methods=list(cfg.methods),
            column_results=column_results,
            multivariate_indices=multivariate_indices,
        )

    # -- strategies --------------------------------------------------------

    def _zscore(self, numeric: pd.DataFrame) -> list[ColumnAnomaly]:
        """Flag values whose absolute z-score exceeds the threshold."""
        threshold = self._settings.anomaly.zscore_threshold
        results: list[ColumnAnomaly] = []
        for column in numeric.columns:
            series = numeric[column].dropna()
            if len(series) < _MIN_OBSERVATIONS:
                continue
            mean = float(series.mean())
            std = float(series.std(ddof=0))
            if std == 0.0:
                continue
            z = (numeric[column] - mean) / std
            mask = z.abs() > threshold
            results.append(
                self._column_result(
                    column,
                    AnomalyMethod.ZSCORE,
                    mask,
                    len(numeric),
                    lower=mean - threshold * std,
                    upper=mean + threshold * std,
                )
            )
        return [r for r in results if r.anomaly_count > 0]

    def _iqr(self, numeric: pd.DataFrame) -> list[ColumnAnomaly]:
        """Flag values outside the Tukey fences defined by the IQR."""
        multiplier = self._settings.anomaly.iqr_multiplier
        results: list[ColumnAnomaly] = []
        for column in numeric.columns:
            series = numeric[column].dropna()
            if len(series) < _MIN_OBSERVATIONS:
                continue
            q1 = float(series.quantile(0.25))
            q3 = float(series.quantile(0.75))
            iqr = q3 - q1
            if iqr == 0.0:
                continue
            lower = q1 - multiplier * iqr
            upper = q3 + multiplier * iqr
            mask = (numeric[column] < lower) | (numeric[column] > upper)
            results.append(
                self._column_result(
                    column, AnomalyMethod.IQR, mask, len(numeric), lower=lower, upper=upper
                )
            )
        return [r for r in results if r.anomaly_count > 0]

    def _isolation_forest(self, numeric: pd.DataFrame) -> list[int]:
        """Flag multivariate outlier rows using an Isolation Forest."""
        if numeric.shape[1] == 0 or len(numeric) < _MIN_OBSERVATIONS:
            return []
        try:
            from sklearn.ensemble import IsolationForest
        except ImportError:  # pragma: no cover - optional dependency guard
            _logger.warning("scikit-learn is unavailable; skipping Isolation Forest")
            return []

        cfg = self._settings.anomaly
        # Impute with the column median so a single missing value does not drop
        # an entire row from the multivariate model.
        filled = numeric.fillna(numeric.median(numeric_only=True))
        filled = filled.dropna(axis=1, how="all")
        if filled.shape[1] == 0:
            return []

        model = IsolationForest(
            contamination=cfg.isolation_forest_contamination,
            random_state=cfg.random_state,
            n_estimators=200,
        )
        predictions = model.fit_predict(filled.to_numpy())
        # Positional row numbers, consistent with the univariate detectors.
        indices = [int(i) for i in np.flatnonzero(predictions == -1)]
        _logger.info("Isolation Forest flagged {} row(s)", len(indices))
        return indices

    # -- helpers -----------------------------------------------------------

    def _column_result(
        self,
        column: str,
        method: AnomalyMethod,
        mask: pd.Series,
        row_count: int,
        *,
        lower: float | None,
        upper: float | None,
    ) -> ColumnAnomaly:
        """Build a :class:`ColumnAnomaly` from an outlier mask.

        As in the validator, rows are recorded as zero-based positions so the
        result does not depend on the frame carrying an integer index.
        """
        positions = np.flatnonzero(mask.fillna(False).to_numpy(dtype=bool))
        count = int(positions.size)
        return ColumnAnomaly(
            column=str(column),
            method=method,
            anomaly_count=count,
            anomaly_ratio=count / row_count if row_count else 0.0,
            lower_bound=None if lower is None else round(float(lower), 6),
            upper_bound=None if upper is None else round(float(upper), 6),
            row_indices=[int(i) for i in positions[:_MAX_ROW_INDICES]],
        )
