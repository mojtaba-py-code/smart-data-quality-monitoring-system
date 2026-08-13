"""Tests for the pipeline orchestrator."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from dqms.config.settings import Settings
from dqms.models.report import AnalysisReport
from dqms.services.orchestrator import QualityPipeline


def test_analyze_returns_full_report(messy_frame: pd.DataFrame, settings: Settings) -> None:
    report = QualityPipeline(settings).analyze(messy_frame, dataset_name="unit")
    assert isinstance(report, AnalysisReport)
    assert report.profile.row_count == len(messy_frame)
    assert report.quality.dimensions
    assert report.anomalies is not None
    assert report.recommendations


def test_analyze_without_anomalies(messy_frame: pd.DataFrame, settings: Settings) -> None:
    report = QualityPipeline(settings).analyze(
        messy_frame, dataset_name="unit", detect_anomalies=False
    )
    assert report.anomalies is None


def test_analyze_file(clean_frame: pd.DataFrame, settings: Settings, tmp_path: Path) -> None:
    path = tmp_path / "clean.csv"
    clean_frame.to_csv(path, index=False)
    report = QualityPipeline(settings).analyze_file(path)
    assert report.dataset_name == "clean"
    assert report.source_path is not None


def test_summary_dict(messy_frame: pd.DataFrame, settings: Settings) -> None:
    report = QualityPipeline(settings).analyze(messy_frame, dataset_name="unit")
    summary = report.to_summary_dict()
    assert summary["rows"] == len(messy_frame)
    assert "overall_score" in summary
    assert "grade" in summary


def test_recommendations_for_clean_data(clean_frame: pd.DataFrame, settings: Settings) -> None:
    report = QualityPipeline(settings).analyze(clean_frame, dataset_name="clean")
    titles = [rec.title for rec in report.recommendations]
    assert any("No critical issues" in title for title in titles)
