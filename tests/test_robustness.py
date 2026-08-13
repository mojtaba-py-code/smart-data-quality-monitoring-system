"""Regression tests for awkward-but-legal datasets and platform quirks.

Every test here corresponds to an input that pandas accepts happily but that
naive code mishandles: non-integer indexes, repeated column labels, empty
files, and non-ASCII terminal output on Windows code pages.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from dqms.cli import app
from dqms.config.settings import Settings
from dqms.core.exceptions import DuplicateColumnError, FileAccessError
from dqms.services.anomaly import AnomalyDetector
from dqms.services.cleaner import DataCleaner
from dqms.services.data_drift import DataDriftDetector
from dqms.services.loader import FileLoader
from dqms.services.orchestrator import QualityPipeline
from dqms.services.profiler import DataProfiler
from dqms.services.schema_drift import SchemaDriftDetector
from dqms.services.validator import DataValidator

runner = CliRunner()


# -- non-integer index -----------------------------------------------------


def test_validator_handles_non_integer_index(settings: Settings) -> None:
    """Row positions must be reported even when index labels are strings."""
    frame = pd.DataFrame({"email": ["a@b.com", "nope"]}, index=["first", "second"])
    report = DataValidator(settings).analyze(frame)
    issue = next(issue for issue in report.issues if issue.rule == "invalid_email")
    assert issue.affected_count == 1
    assert issue.row_indices == [1]


def test_anomaly_handles_non_integer_index(settings: Settings) -> None:
    values = [1.0] * 20 + [500.0]
    frame = pd.DataFrame({"v": values}, index=[f"r{i}" for i in range(21)])
    report = AnomalyDetector(settings).detect(frame)
    assert report.total_flagged_rows == 1
    assert report.column_results[0].row_indices == [20]


def test_pipeline_analyzes_datetime_indexed_frame(settings: Settings) -> None:
    frame = pd.DataFrame(
        {"amount": [1.0, 2.0, None]},
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )
    report = QualityPipeline(settings).analyze(frame, dataset_name="ts")
    assert report.row_count == 3
    assert 0 <= report.quality.overall_score <= 100


# -- repeated column labels ------------------------------------------------


def _duplicated_frame() -> pd.DataFrame:
    return pd.DataFrame([[1, "a", 2], [3, "b", 4]], columns=["x", "label", "x"])


def test_profiler_handles_duplicate_column_labels() -> None:
    profile = DataProfiler().analyze(_duplicated_frame())
    assert profile.column_count == 3
    assert len(profile.columns) == 3


def test_validator_handles_duplicate_column_labels(settings: Settings) -> None:
    report = DataValidator(settings).analyze(_duplicated_frame())
    assert report.row_count == 2


def test_cleaner_makes_duplicate_labels_unique(settings: Settings) -> None:
    result = DataCleaner(settings).clean(_duplicated_frame())
    assert list(result.frame.columns) == ["x", "label", "x_1"]
    assert any("duplicate column label" in action for action in result.actions)


def test_cleaner_avoids_collision_with_existing_label(settings: Settings) -> None:
    frame = pd.DataFrame([[1, 2, 3]], columns=["a", "a", "a_1"])
    result = DataCleaner(settings).clean(frame)
    assert len(set(result.frame.columns)) == 3


@pytest.mark.parametrize("detector", ["schema", "data"])
def test_drift_rejects_duplicate_labels(settings: Settings, detector: str) -> None:
    baseline = _duplicated_frame()
    current = pd.DataFrame({"x": [1, 2], "label": ["a", "b"]})
    with pytest.raises(DuplicateColumnError):
        if detector == "schema":
            SchemaDriftDetector().compare(baseline, current)
        else:
            DataDriftDetector(settings).compare(baseline, current)


# -- loader guards ---------------------------------------------------------


def test_empty_file_is_rejected_clearly(settings: Settings, tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("")
    with pytest.raises(FileAccessError, match="empty"):
        FileLoader(settings).load(path)


def test_header_only_file_loads(settings: Settings, tmp_path: Path) -> None:
    path = tmp_path / "header.csv"
    path.write_text("a,b\n")
    assert FileLoader(settings).load(path).empty


# -- result immutability ---------------------------------------------------


def test_result_models_are_frozen(settings: Settings, clean_frame: pd.DataFrame) -> None:
    """Results are values: a consumer must not be able to edit a score in place."""
    from pydantic import ValidationError as PydanticValidationError

    report = QualityPipeline(settings).analyze(clean_frame, dataset_name="frozen")
    with pytest.raises(PydanticValidationError):
        report.quality.overall_score = 0.0  # type: ignore[misc]
    with pytest.raises(PydanticValidationError):
        report.profile.columns[0].null_count = 99  # type: ignore[misc]


def test_drift_results_are_frozen(settings: Settings) -> None:
    from pydantic import ValidationError as PydanticValidationError

    baseline = pd.DataFrame({"a": list(range(30))})
    current = pd.DataFrame({"a": list(range(20, 50))})
    report = DataDriftDetector(settings).compare(baseline, current)
    assert report.columns[0].severity in {"none", "warning", "critical"}
    with pytest.raises(PydanticValidationError):
        report.columns[0].psi = 0.0  # type: ignore[misc]


# -- CLI / platform --------------------------------------------------------


def test_cli_source_is_ascii() -> None:
    """CLI literals must be ASCII.

    Rich substitutes its own box-drawing characters on legacy code pages, but it
    cannot rescue text we supply: a non-ASCII label (such as a Greek delta in a
    column header) aborts rendering with UnicodeEncodeError on a cp1252 console.
    """
    import dqms.cli

    source = Path(dqms.cli.__file__).read_text(encoding="utf-8")
    offenders = [line for line in source.splitlines() if not line.isascii()]
    assert offenders == []


def test_compare_command_renders_drift_table(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.csv"
    current = tmp_path / "current.csv"
    pd.DataFrame({"a": list(range(20))}).to_csv(baseline, index=False)
    pd.DataFrame({"a": list(range(10, 30))}).to_csv(current, index=False)

    result = runner.invoke(app, ["compare", str(baseline), str(current)])
    assert result.exit_code in {0, 2}
    assert "Data drift" in result.stdout


def test_clean_respects_sanitize_exports_setting(tmp_path: Path) -> None:
    """The security.sanitize_exports switch must reach the exporter."""
    source = tmp_path / "inject.csv"
    pd.DataFrame({"note": ["=SUM(A1:A2)", "safe"]}).to_csv(source, index=False)

    config = tmp_path / "off.yaml"
    config.write_text("security:\n  sanitize_exports: false\n", encoding="utf-8")

    protected = tmp_path / "protected.csv"
    assert runner.invoke(app, ["clean", str(source), "-o", str(protected)]).exit_code == 0
    assert "'=SUM(A1:A2)" in protected.read_text(encoding="utf-8")

    raw = tmp_path / "raw.csv"
    result = runner.invoke(
        app, ["--config", str(config), "clean", str(source), "-o", str(raw)]
    )
    assert result.exit_code == 0
    assert "'=SUM" not in raw.read_text(encoding="utf-8")
