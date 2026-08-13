"""Tests for the Typer command-line interface."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from dqms.cli import app

runner = CliRunner()


@pytest.fixture
def clean_csv(clean_frame: pd.DataFrame, tmp_path: Path) -> Path:
    path = tmp_path / "clean.csv"
    clean_frame.to_csv(path, index=False)
    return path


@pytest.fixture
def messy_csv(messy_frame: pd.DataFrame, tmp_path: Path) -> Path:
    path = tmp_path / "messy.csv"
    messy_frame.to_csv(path, index=False)
    return path


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "dqms" in result.stdout


def test_profile_command(clean_csv: Path) -> None:
    result = runner.invoke(app, ["profile", str(clean_csv)])
    assert result.exit_code == 0
    assert "Profile" in result.stdout


def test_validate_clean(clean_csv: Path) -> None:
    result = runner.invoke(app, ["validate", str(clean_csv)])
    assert result.exit_code == 0
    assert "No validation issues" in result.stdout


def test_validate_strict_gates_on_errors(messy_csv: Path) -> None:
    """--strict turns error-severity issues into a non-zero exit for CI."""
    lenient = runner.invoke(app, ["validate", str(messy_csv)])
    assert lenient.exit_code == 0

    strict = runner.invoke(app, ["validate", str(messy_csv), "--strict"])
    assert strict.exit_code == 2
    assert "--strict" in strict.stdout


def test_validate_strict_passes_on_clean_data(clean_csv: Path) -> None:
    result = runner.invoke(app, ["validate", str(clean_csv), "--strict"])
    assert result.exit_code == 0


def test_analyze_clean_passes(clean_csv: Path) -> None:
    result = runner.invoke(app, ["analyze", str(clean_csv), "--no-report", "--no-anomalies"])
    assert result.exit_code == 0
    assert "Analysis summary" in result.stdout


def test_clean_command(messy_csv: Path, tmp_path: Path) -> None:
    out = tmp_path / "cleaned.csv"
    result = runner.invoke(app, ["clean", str(messy_csv), "--output", str(out)])
    assert result.exit_code == 0
    assert out.exists()


def test_report_command(clean_csv: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "reports"
    result = runner.invoke(
        app, ["report", str(clean_csv), "--output", str(out_dir), "--format", "summary"]
    )
    assert result.exit_code == 0
    assert any(out_dir.glob("*_summary.txt"))


def test_compare_command(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.csv"
    current = tmp_path / "current.csv"
    pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]}).to_csv(baseline, index=False)
    pd.DataFrame({"a": [1, 2, 3], "c": [7, 8, 9]}).to_csv(current, index=False)
    result = runner.invoke(app, ["compare", str(baseline), str(current)])
    # Drift present -> exit code 2, but output must still render.
    assert result.exit_code in {0, 2}
    assert "Schema drift" in result.stdout


def test_unknown_file_errors(tmp_path: Path) -> None:
    result = runner.invoke(app, ["profile", str(tmp_path / "missing.csv")])
    assert result.exit_code == 1
