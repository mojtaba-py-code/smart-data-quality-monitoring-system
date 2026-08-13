"""Tests for the file loading engine."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from dqms.config.settings import Settings
from dqms.core.constants import FileFormat
from dqms.core.exceptions import SecurityError, UnsupportedFormatError
from dqms.services.loader import FileLoader


@pytest.fixture
def frame() -> pd.DataFrame:
    return pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})


def test_detect_format(settings: Settings) -> None:
    loader = FileLoader(settings)
    assert loader.detect_format(Path("f.csv")) is FileFormat.CSV
    assert loader.detect_format(Path("f.xlsx")) is FileFormat.EXCEL
    assert loader.detect_format(Path("f.json")) is FileFormat.JSON
    assert loader.detect_format(Path("f.parquet")) is FileFormat.PARQUET


def test_detect_format_unsupported(settings: Settings) -> None:
    loader = FileLoader(settings)
    with pytest.raises(UnsupportedFormatError):
        loader.detect_format(Path("f.bin"))


def test_load_csv(settings: Settings, frame: pd.DataFrame, tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    frame.to_csv(path, index=False)
    loaded = FileLoader(settings).load(path)
    assert list(loaded.columns) == ["a", "b"]
    assert len(loaded) == 3


def test_load_json(settings: Settings, frame: pd.DataFrame, tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    frame.to_json(path, orient="records")
    loaded = FileLoader(settings).load(path)
    assert len(loaded) == 3


def test_load_parquet(settings: Settings, frame: pd.DataFrame, tmp_path: Path) -> None:
    path = tmp_path / "data.parquet"
    frame.to_parquet(path, index=False)
    loaded = FileLoader(settings).load(path)
    assert len(loaded) == 3


def test_load_excel(settings: Settings, frame: pd.DataFrame, tmp_path: Path) -> None:
    path = tmp_path / "data.xlsx"
    frame.to_excel(path, index=False)
    loaded = FileLoader(settings).load(path)
    assert len(loaded) == 3


def test_disallowed_extension(settings: Settings, tmp_path: Path) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(b"binary")
    with pytest.raises(SecurityError):
        FileLoader(settings).load(path)


def test_row_sampling(settings: Settings, tmp_path: Path) -> None:
    settings.loader.sample_rows = 5
    frame = pd.DataFrame({"a": range(100)})
    path = tmp_path / "big.csv"
    frame.to_csv(path, index=False)
    loaded = FileLoader(settings).load(path)
    assert len(loaded) == 5
