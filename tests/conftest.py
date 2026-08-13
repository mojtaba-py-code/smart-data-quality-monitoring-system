"""Shared pytest fixtures.

Fixtures build small, deterministic datasets in memory (and on disk) so the test
suite is fully self-contained and never depends on the sample-data generator or
any external files.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dqms.config.settings import Settings, load_settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Return default settings with output/log directories redirected to tmp."""
    cfg = load_settings()
    cfg.paths.output_dir = tmp_path / "output"
    cfg.paths.log_dir = tmp_path / "logs"
    cfg.paths.input_dir = tmp_path / "input"
    return cfg


@pytest.fixture
def messy_frame() -> pd.DataFrame:
    """A small dataset that triggers many validation and cleaning rules."""
    frame = pd.DataFrame(
        {
            "id": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "email": [
                "a@example.com",
                "b@example.com",
                "invalid-email",
                "d@example.com",
                "e@example.com",
                "f@example.com",
                "g@example.com",
                "h@example.com",
                "i@example.com",
                "j@example.com",
            ],
            "phone": ["+1 555-000-1111"] * 9 + ["not-a-phone"],
            "amount": [10.0, 20.0, 30.0, np.nan, 50.0, 60.0, 70.0, 80.0, 90.0, 100000.0],
            "created": [
                "2024-01-01",
                "2024-01-02",
                "bad-date",
                "2024-01-04",
                "2024-01-05",
                "2024-01-06",
                "2024-01-07",
                "2024-01-08",
                "2024-01-09",
                "2024-01-10",
            ],
            "note": ["  hello ", "world", "", "  ", "text", "text", "text", "text", "x", "y"],
        }
    )
    # Append a duplicate of the first row.
    return pd.concat([frame, frame.iloc[[0]]], ignore_index=True)


@pytest.fixture
def clean_frame() -> pd.DataFrame:
    """A dataset with no quality problems."""
    rng = np.random.default_rng(7)
    return pd.DataFrame(
        {
            "id": range(1, 51),
            "value": rng.normal(100, 10, 50).round(2),
            "category": rng.choice(["x", "y", "z"], 50),
        }
    )


@pytest.fixture
def numeric_frame() -> pd.DataFrame:
    """A numeric dataset with one obvious outlier per column."""
    rng = np.random.default_rng(3)
    frame = pd.DataFrame(
        {
            "a": rng.normal(0, 1, 60),
            "b": rng.normal(50, 5, 60),
        }
    )
    frame.loc[0, "a"] = 25.0
    frame.loc[1, "b"] = 500.0
    return frame


def write_frame(frame: pd.DataFrame, path: Path) -> Path:
    """Persist a frame to disk in the format implied by ``path`` suffix."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        frame.to_csv(path, index=False)
    elif suffix in {".xlsx", ".xls"}:
        frame.to_excel(path, index=False)
    elif suffix == ".json":
        frame.to_json(path, orient="records")
    elif suffix == ".parquet":
        frame.to_parquet(path, index=False)
    else:  # pragma: no cover - guard
        raise ValueError(f"unsupported suffix {suffix}")
    return path
