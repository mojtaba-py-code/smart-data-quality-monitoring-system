"""Tests for the data-cleaning service."""

from __future__ import annotations

import numpy as np
import pandas as pd

from dqms.config.settings import Settings
from dqms.services.cleaner import DataCleaner


def test_removes_duplicates(messy_frame: pd.DataFrame, settings: Settings) -> None:
    result = DataCleaner(settings).clean(messy_frame)
    assert result.rows_after < result.rows_before
    assert not result.frame.duplicated().any()


def test_fills_missing_numeric(messy_frame: pd.DataFrame, settings: Settings) -> None:
    settings.cleaning.missing_numeric_strategy = "median"
    result = DataCleaner(settings).clean(messy_frame)
    assert result.frame["amount"].isna().sum() == 0


def test_trims_whitespace(settings: Settings) -> None:
    frame = pd.DataFrame({"note": ["  hello  ", "world  "]})
    result = DataCleaner(settings).clean(frame)
    assert result.frame["note"].tolist() == ["hello", "world"]


def test_standardizes_column_names(settings: Settings) -> None:
    frame = pd.DataFrame({"Customer ID": [1], "First-Name": ["a"]})
    result = DataCleaner(settings).clean(frame)
    assert "customer_id" in result.frame.columns
    assert "first_name" in result.frame.columns


def test_normalizes_dates(settings: Settings) -> None:
    frame = pd.DataFrame({"created": ["2024-01-01", "2024-02-01", "2024-03-01"]})
    result = DataCleaner(settings).clean(frame)
    assert pd.api.types.is_datetime64_any_dtype(result.frame["created"])


def test_normalizes_currency(settings: Settings) -> None:
    frame = pd.DataFrame({"price": ["$1,000.00", "$2,500.50", "$300.00"]})
    result = DataCleaner(settings).clean(frame)
    assert pd.api.types.is_numeric_dtype(result.frame["price"])
    assert result.frame["price"].iloc[0] == 1000.0


def test_input_not_mutated(settings: Settings) -> None:
    frame = pd.DataFrame({"a": [1, np.nan, 3]})
    original = frame.copy()
    DataCleaner(settings).clean(frame)
    pd.testing.assert_frame_equal(frame, original)


def test_actions_recorded(messy_frame: pd.DataFrame, settings: Settings) -> None:
    result = DataCleaner(settings).clean(messy_frame)
    assert len(result.actions) > 0
