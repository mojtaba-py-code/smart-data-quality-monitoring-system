"""Tests for the anomaly-detection service."""

from __future__ import annotations

import pandas as pd

from dqms.config.settings import Settings
from dqms.core.constants import AnomalyMethod
from dqms.services.anomaly import AnomalyDetector


def test_zscore_flags_outlier(numeric_frame: pd.DataFrame, settings: Settings) -> None:
    settings.anomaly.methods = [AnomalyMethod.ZSCORE]
    report = AnomalyDetector(settings).detect(numeric_frame)
    assert report.total_flagged_rows >= 1
    flagged = {idx for result in report.column_results for idx in result.row_indices}
    assert 0 in flagged or 1 in flagged


def test_iqr_flags_outlier(numeric_frame: pd.DataFrame, settings: Settings) -> None:
    settings.anomaly.methods = [AnomalyMethod.IQR]
    report = AnomalyDetector(settings).detect(numeric_frame)
    assert report.total_flagged_rows >= 1


def test_isolation_forest(numeric_frame: pd.DataFrame, settings: Settings) -> None:
    settings.anomaly.methods = [AnomalyMethod.ISOLATION_FOREST]
    report = AnomalyDetector(settings).detect(numeric_frame)
    assert len(report.multivariate_indices) >= 1


def test_no_numeric_columns(settings: Settings) -> None:
    frame = pd.DataFrame({"s": ["a", "b", "c", "d", "e", "f", "g", "h"]})
    report = AnomalyDetector(settings).detect(frame)
    assert report.total_flagged_rows == 0


def test_reports_bounds(numeric_frame: pd.DataFrame, settings: Settings) -> None:
    settings.anomaly.methods = [AnomalyMethod.IQR]
    report = AnomalyDetector(settings).detect(numeric_frame)
    for result in report.column_results:
        assert result.lower_bound is not None
        assert result.upper_bound is not None
