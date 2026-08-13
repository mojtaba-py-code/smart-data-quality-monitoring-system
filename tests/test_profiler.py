"""Tests for the data-profiling service."""

from __future__ import annotations

import numpy as np
import pandas as pd

from dqms.services.profiler import DataProfiler


def test_profile_shape(messy_frame: pd.DataFrame) -> None:
    profile = DataProfiler().analyze(messy_frame)
    assert profile.row_count == len(messy_frame)
    assert profile.column_count == messy_frame.shape[1]
    assert len(profile.columns) == messy_frame.shape[1]


def test_duplicate_detection(messy_frame: pd.DataFrame) -> None:
    profile = DataProfiler().analyze(messy_frame)
    assert profile.duplicate_row_count >= 1


def test_missing_ratio() -> None:
    frame = pd.DataFrame({"a": [1.0, np.nan, 3.0, np.nan]})
    profile = DataProfiler().analyze(frame)
    assert profile.missing_cells == 2
    assert profile.missing_ratio == 0.5


def test_numeric_stats() -> None:
    frame = pd.DataFrame({"n": [1, 2, 3, 4, 5]})
    profile = DataProfiler().analyze(frame)
    col = profile.column("n")
    assert col is not None
    assert col.is_numeric
    assert col.minimum == 1
    assert col.maximum == 5
    assert col.mean == 3
    assert col.median == 3


def test_non_numeric_has_no_stats() -> None:
    frame = pd.DataFrame({"s": ["a", "b", "c"]})
    profile = DataProfiler().analyze(frame)
    col = profile.column("s")
    assert col is not None
    assert not col.is_numeric
    assert col.mean is None
    assert col.mode in {"a", "b", "c"}


def test_empty_frame() -> None:
    profile = DataProfiler().analyze(pd.DataFrame())
    assert profile.row_count == 0
    assert profile.column_count == 0
