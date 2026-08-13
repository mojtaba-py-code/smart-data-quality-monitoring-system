"""Report generation.

Turns an :class:`~dqms.models.report.AnalysisReport` into shareable artefacts:

* **HTML** - a self-contained page (charts embedded as base64) rendered from a
  Jinja2 template with autoescaping enabled to prevent injection.
* **PDF** - a paginated document built with fpdf2 (pure Python, no system
  dependencies), suitable for archival and email.
* **Summary** - a compact plain-text digest for terminals and chat.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from dqms.config.settings import Settings, get_settings
from dqms.core.exceptions import ReportGenerationError
from dqms.models.report import AnalysisReport
from dqms.services.visualizer import ChartFactory, encode_png_base64
from dqms.utils.logging import get_logger
from dqms.utils.security import sanitize_filename

_logger = get_logger("dqms.reports")

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_TEMPLATE_NAME = "report.html"


class ReportGenerator:
    """Render analysis reports to HTML, PDF, and plain text."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate(
        self,
        report: AnalysisReport,
        *,
        frame: pd.DataFrame | None = None,
        output_dir: str | Path | None = None,
        formats: list[str] | None = None,
    ) -> dict[str, Path]:
        """Generate the requested report formats.

        Parameters
        ----------
        report:
            The analysis result to render.
        frame:
            Optional source DataFrame, required to render charts.
        output_dir:
            Destination directory. Defaults to the configured output directory.
        formats:
            Subset of ``{"html", "pdf", "summary"}``. Defaults to configuration.

        Returns
        -------
        dict[str, pathlib.Path]
            Mapping of format name to the file that was written.
        """
        formats = formats or self._settings.report.formats
        out_dir = Path(output_dir or self._settings.paths.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = sanitize_filename(report.dataset_name, default="report")

        charts = self._build_charts(report, frame, out_dir, stem)

        outputs: dict[str, Path] = {}
        try:
            if "html" in formats:
                outputs["html"] = self._render_html(report, charts, out_dir / f"{stem}_report.html")
            if "pdf" in formats:
                outputs["pdf"] = self._render_pdf(report, charts, out_dir / f"{stem}_report.pdf")
            if "summary" in formats:
                summary_path = out_dir / f"{stem}_summary.txt"
                summary_path.write_text(self.render_summary(report), encoding="utf-8")
                outputs["summary"] = summary_path
        except ReportGenerationError:
            raise
        except Exception as exc:
            raise ReportGenerationError(
                "failed to generate report", details={"error": str(exc)}
            ) from exc

        _logger.success("Generated report formats: {}", ", ".join(outputs))
        return outputs

    # -- charts ------------------------------------------------------------

    def _build_charts(
        self,
        report: AnalysisReport,
        frame: pd.DataFrame | None,
        out_dir: Path,
        stem: str,
    ) -> dict[str, Path]:
        """Render the chart PNGs if charts are enabled and data is available."""
        if not self._settings.report.include_charts or frame is None:
            return {}
        chart_dir = out_dir / f"{stem}_charts"
        factory = ChartFactory(chart_dir)
        return factory.generate_all(frame, report.quality)

    # -- HTML --------------------------------------------------------------

    def _render_html(
        self, report: AnalysisReport, charts: dict[str, Path], destination: Path
    ) -> Path:
        """Render the HTML report with charts embedded as base64 data URIs."""
        template = self._env.get_template(_TEMPLATE_NAME)
        embedded = {name: encode_png_base64(path) for name, path in charts.items()}
        html = template.render(
            report=report,
            charts=embedded,
            company_name=self._settings.report.company_name,
        )
        destination.write_text(html, encoding="utf-8")
        return destination

    # -- PDF ---------------------------------------------------------------

    def _render_pdf(
        self, report: AnalysisReport, charts: dict[str, Path], destination: Path
    ) -> Path:
        """Render a paginated PDF report using fpdf2."""
        from fpdf import FPDF

        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        def latin1(value: str) -> str:
            # fpdf2's core fonts are latin-1; replace anything outside it safely.
            return value.encode("latin-1", "replace").decode("latin-1")

        def line(text: str, *, height: float = 6.0) -> None:
            """Write a single left-aligned line spanning the full text width."""
            pdf.set_x(pdf.l_margin)
            pdf.cell(pdf.epw, height, latin1(text), new_x="LMARGIN", new_y="NEXT")

        def wrapped(text: str, *, height: float = 6.0) -> None:
            """Write a wrapping paragraph spanning the full effective page width."""
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(pdf.epw, height, latin1(text), new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "B", 18)
        line("Data Quality Report", height=10)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(90, 90, 90)
        line(
            f"{report.dataset_name} | generated "
            f"{report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

        pdf.set_font("Helvetica", "B", 12)
        line("Summary", height=8)
        pdf.set_font("Helvetica", "", 10)
        for text in (
            f"Overall score: {report.quality.overall_score:.1f}%  (grade {report.quality.grade})",
            f"Status: {'PASS' if report.quality.passed else 'FAIL'}",
            f"Rows: {report.row_count:,}   Columns: {report.column_count}",
            f"Validation issues: {report.validation.total_issues:,}",
            f"Duplicate rows: {report.profile.duplicate_row_count:,}",
            f"Missing ratio: {report.profile.missing_ratio:.2%}",
        ):
            line(text)
        pdf.ln(2)

        pdf.set_font("Helvetica", "B", 12)
        line("Quality dimensions", height=8)
        pdf.set_font("Helvetica", "", 10)
        for dim in report.quality.dimensions:
            line(f"  - {dim.dimension.value.title()}: {dim.score:.1f}%")
        pdf.ln(2)

        pdf.set_font("Helvetica", "B", 12)
        line("Recommendations", height=8)
        pdf.set_font("Helvetica", "", 10)
        for rec in report.recommendations:
            wrapped(f"[{rec.severity.value.upper()}] {rec.title}: {rec.detail}")
        pdf.ln(2)

        for name, path in charts.items():
            if pdf.get_y() > 210:
                pdf.add_page()
            pdf.set_font("Helvetica", "B", 11)
            line(name.replace("_", " ").title(), height=8)
            try:
                pdf.image(str(path), w=min(180, pdf.epw))
            except Exception as exc:
                _logger.warning("Could not embed chart {} in PDF: {}", name, exc)
            pdf.ln(2)

        pdf.output(str(destination))
        return destination

    # -- summary -----------------------------------------------------------

    def render_summary(self, report: AnalysisReport) -> str:
        """Return a compact plain-text summary of the analysis."""
        lines = [
            "=" * 60,
            f" Data Quality Summary: {report.dataset_name}",
            "=" * 60,
            f" Generated : {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
            f" Rows      : {report.row_count:,}",
            f" Columns   : {report.column_count}",
            f" Score     : {report.quality.overall_score:.1f}%  (grade {report.quality.grade})",
            f" Status    : {'PASS' if report.quality.passed else 'FAIL'}",
            "-" * 60,
            " Dimensions:",
        ]
        for dim in report.quality.dimensions:
            lines.append(f"   {dim.dimension.value:<13}: {dim.score:6.1f}%")
        lines.append("-" * 60)
        lines.append(" Recommendations:")
        for rec in report.recommendations:
            lines.append(f"   [{rec.severity.value.upper():<8}] {rec.title}")
        lines.append("=" * 60)
        return "\n".join(lines)
