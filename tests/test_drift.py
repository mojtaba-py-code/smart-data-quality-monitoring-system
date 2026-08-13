"""Tests for schema-drift and data-drift detection."""

from __future__ import annotations

import numpy as np
import pandas as pd

from dqms.config.settings import Settings
from dqms.services.data_drift import DataDriftDetector
from dqms.services.schema_drift import SchemaDriftDetector


def test_schema_added_and_removed() -> None:
    baseline = pd.DataFrame({"a": [1], "b": [2]})
    current = pd.DataFrame({"a": [1], "c": [3]})
    report = SchemaDriftDetector().compare(baseline, current)
    assert report.added_columns == ["c"]
    assert report.removed_columns == ["b"]
    assert report.has_drift


def test_schema_dtype_change() -> None:
    baseline = pd.DataFrame({"a": [1, 2, 3]})
    current = pd.DataFrame({"a": ["1", "2", "3"]})
    report = SchemaDriftDetector().compare(baseline, current)
    assert len(report.dtype_changes) == 1
    assert report.dtype_changes[0].column == "a"


def test_schema_stable() -> None:
    frame = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    report = SchemaDriftDetector().compare(frame, frame.copy())
    assert not report.has_drift
    assert set(report.stable_columns) == {"a", "b"}


def test_data_drift_detects_shift(settings: Settings) -> None:
    rng = np.random.default_rng(0)
    baseline = pd.DataFrame({"x": rng.normal(0, 1, 500)})
    current = pd.DataFrame({"x": rng.normal(5, 1, 500)})
    report = DataDriftDetector(settings).compare(baseline, current)
    assert report.has_drift
    col = report.columns[0]
    assert col.psi is not None and col.psi > settings.drift.psi_warning


def test_data_drift_stable(settings: Settings) -> None:
    rng = np.random.default_rng(1)
    data = pd.DataFrame({"x": rng.normal(0, 1, 500)})
    report = DataDriftDetector(settings).compare(data, data.copy())
    assert not report.has_drift


def test_correlation_changes(settings: Settings) -> None:
    rng = np.random.default_rng(2)
    n = 400
    a = rng.normal(0, 1, n)
    baseline = pd.DataFrame({"a": a, "b": a + rng.normal(0, 0.1, n)})
    current = pd.DataFrame({"a": a, "b": rng.normal(0, 1, n)})
    report = DataDriftDetector(settings).compare(baseline, current)
    assert report.correlation_changes
    assert any(v > 0.3 for v in report.correlation_changes.values())
