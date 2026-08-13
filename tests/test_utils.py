"""Tests for IO, pattern, and timing utilities."""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import pytest

from dqms.core.constants import FileFormat
from dqms.core.exceptions import UnsupportedFormatError
from dqms.utils.io import export_dataframe
from dqms.utils.patterns import (
    column_matches_hint,
    is_valid_email,
    is_valid_phone,
    looks_like_identifier,
)
from dqms.utils.timing import Stopwatch, timed


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("user@example.com", True),
        ("first.last+tag@sub.example.co", True),
        ("no-at-sign", False),
        ("bad@", False),
        ("@nolocal.com", False),
        ("", False),
    ],
)
def test_is_valid_email(value: str, expected: bool) -> None:
    assert is_valid_email(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("+1 (555) 123-4567", True),
        ("5551234567", True),
        ("12", False),
        ("abcdef", False),
    ],
)
def test_is_valid_phone(value: str, expected: bool) -> None:
    assert is_valid_phone(value) is expected


def test_looks_like_identifier() -> None:
    assert looks_like_identifier("customer_id")
    assert looks_like_identifier("uuid")
    assert not looks_like_identifier("name")


def test_column_matches_hint() -> None:
    assert column_matches_hint("Customer_Email", ["email"])
    assert not column_matches_hint("age", ["email", "phone"])


@pytest.mark.parametrize("suffix", [".csv", ".json", ".parquet", ".xlsx"])
def test_export_roundtrip(tmp_path: Path, suffix: str) -> None:
    frame = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    out = export_dataframe(frame, tmp_path / f"out{suffix}")
    assert out.exists()
    assert out.stat().st_size > 0


def test_export_neutralises_formula(tmp_path: Path) -> None:
    frame = pd.DataFrame({"formula": ["=1+1", "safe"]})
    out = export_dataframe(frame, tmp_path / "f.csv", fmt=FileFormat.CSV)
    content = out.read_text(encoding="utf-8")
    assert "'=1+1" in content


def test_export_unknown_extension(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedFormatError):
        export_dataframe(pd.DataFrame({"a": [1]}), tmp_path / "x.unknown")


def test_stopwatch_measures_time() -> None:
    with Stopwatch("test", log=False) as sw:
        time.sleep(0.01)
    assert sw.elapsed_seconds >= 0.005


def test_timed_decorator_runs() -> None:
    @timed("adder")
    def add(a: int, b: int) -> int:
        return a + b

    assert add(2, 3) == 5
