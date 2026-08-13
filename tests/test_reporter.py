"""Tests for the report generator."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from dqms.config.settings import Settings
from dqms.reports.generator import ReportGenerator
from dqms.services.orchestrator import QualityPipeline


def _report(frame: pd.DataFrame, settings: Settings):  # type: ignore[no-untyped-def]
    return QualityPipeline(settings).analyze(frame, dataset_name="report_test")


def test_summary_report(messy_frame: pd.DataFrame, settings: Settings) -> None:
    report = _report(messy_frame, settings)
    text = ReportGenerator(settings).render_summary(report)
    assert "Data Quality Summary" in text
    assert "report_test" in text


def test_generate_all_formats(
    messy_frame: pd.DataFrame, settings: Settings, tmp_path: Path
) -> None:
    report = _report(messy_frame, settings)
    outputs = ReportGenerator(settings).generate(
        report, frame=messy_frame, output_dir=tmp_path, formats=["html", "pdf", "summary"]
    )
    for fmt in ("html", "pdf", "summary"):
        assert fmt in outputs
        assert outputs[fmt].exists()
        assert outputs[fmt].stat().st_size > 0


def test_html_contains_dataset(
    messy_frame: pd.DataFrame, settings: Settings, tmp_path: Path
) -> None:
    report = _report(messy_frame, settings)
    outputs = ReportGenerator(settings).generate(
        report, frame=messy_frame, output_dir=tmp_path, formats=["html"]
    )
    html = outputs["html"].read_text(encoding="utf-8")
    assert "report_test" in html
    assert "Overall score" in html


def test_html_autoescapes_injection(settings: Settings, tmp_path: Path) -> None:
    frame = pd.DataFrame({"<script>alert(1)</script>": [1, 2, 3]})
    report = QualityPipeline(settings).analyze(frame, dataset_name="xss")
    outputs = ReportGenerator(settings).generate(
        report, frame=frame, output_dir=tmp_path, formats=["html"]
    )
    html = outputs["html"].read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_no_charts_without_frame(
    messy_frame: pd.DataFrame, settings: Settings, tmp_path: Path
) -> None:
    report = _report(messy_frame, settings)
    outputs = ReportGenerator(settings).generate(
        report, frame=None, output_dir=tmp_path, formats=["html"]
    )
    assert outputs["html"].exists()
