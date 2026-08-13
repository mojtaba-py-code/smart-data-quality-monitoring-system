"""Streamlit dashboard for the Smart Data Quality Monitoring System.

Run with ``dqms dashboard`` or ``streamlit run src/dqms/dashboard/app.py``.

The dashboard is a presentation layer only: it uploads a file to a private
temporary location, hands it to the same :class:`QualityPipeline` the CLI uses,
and renders the returned report. No analysis logic lives here, which guarantees
the dashboard and CLI always agree.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from dqms.config.settings import get_settings
from dqms.core.exceptions import DataQualityError
from dqms.reports.generator import ReportGenerator
from dqms.services.data_drift import DataDriftDetector
from dqms.services.loader import FileLoader
from dqms.services.orchestrator import QualityPipeline
from dqms.services.schema_drift import SchemaDriftDetector
from dqms.utils.logging import configure_logging
from dqms.utils.security import sanitize_filename

settings = get_settings()
configure_logging(settings)


def _persist_upload(uploaded: st.runtime.uploaded_file_manager.UploadedFile) -> Path:
    """Write an uploaded file to a private temp directory and return its path."""
    temp_dir = Path(tempfile.mkdtemp(prefix="dqms_"))
    safe_name = sanitize_filename(uploaded.name, default="upload")
    destination = temp_dir / safe_name
    destination.write_bytes(uploaded.getbuffer())
    return destination


@st.cache_data(show_spinner=False)
def _load_dataframe(path_str: str) -> pd.DataFrame:
    """Load a dataset (cached by path) through the secure loader."""
    return FileLoader(settings).load(Path(path_str))


def _render_analysis(frame: pd.DataFrame, name: str, source: str | None) -> None:
    """Run the pipeline and render the full analysis view."""
    pipeline = QualityPipeline(settings)
    with st.spinner("Analysing dataset..."):
        report = pipeline.analyze(frame, dataset_name=name, source_path=source)

    quality = report.quality
    top = st.columns(5)
    top[0].metric("Overall score", f"{quality.overall_score:.1f}%", delta=quality.grade)
    top[1].metric("Status", "PASS" if quality.passed else "FAIL")
    top[2].metric("Rows", f"{report.row_count:,}")
    top[3].metric("Columns", f"{report.column_count}")
    top[4].metric("Issues", f"{report.validation.total_issues:,}")

    st.subheader("Quality dimensions")
    dim_df = pd.DataFrame(
        {
            "Dimension": [d.dimension.value.title() for d in quality.dimensions],
            "Score": [d.score for d in quality.dimensions],
        }
    )
    fig = px.bar(
        dim_df, x="Score", y="Dimension", orientation="h", range_x=[0, 100], text="Score"
    )
    fig.update_traces(texttemplate="%{text:.1f}", marker_color="#1565c0")
    st.plotly_chart(fig, use_container_width=True)

    tabs = st.tabs(["Recommendations", "Validation", "Profile", "Charts", "Report"])

    with tabs[0]:
        for rec in report.recommendations:
            st.markdown(f"**[{rec.severity.value.upper()}] {rec.title}** — {rec.detail}")

    with tabs[1]:
        if report.validation.issues:
            issues_df = pd.DataFrame(
                [
                    {
                        "Column": issue.column or "(dataset)",
                        "Rule": issue.rule,
                        "Severity": issue.severity.value,
                        "Affected": issue.affected_count,
                        "Message": issue.message,
                    }
                    for issue in report.validation.issues
                ]
            )
            st.dataframe(issues_df, use_container_width=True, hide_index=True)
        else:
            st.success("No validation issues detected.")

    with tabs[2]:
        profile_df = pd.DataFrame([col.model_dump() for col in report.profile.columns])
        st.dataframe(profile_df, use_container_width=True, hide_index=True)

    with tabs[3]:
        _render_charts(frame)

    with tabs[4]:
        _render_report_download(report, frame)


def _render_charts(frame: pd.DataFrame) -> None:
    """Render interactive charts for the numeric columns."""
    numeric = frame.select_dtypes("number")
    if numeric.empty:
        st.info("No numeric columns to chart.")
        return
    column = st.selectbox("Column", list(numeric.columns))
    st.plotly_chart(px.histogram(numeric, x=column, nbins=30), use_container_width=True)
    st.plotly_chart(px.box(numeric, y=column), use_container_width=True)
    if numeric.shape[1] >= 2:
        st.plotly_chart(
            px.imshow(numeric.corr(numeric_only=True), text_auto=".2f", aspect="auto",
                      color_continuous_scale="RdBu", zmin=-1, zmax=1),
            use_container_width=True,
        )


def _render_report_download(report, frame: pd.DataFrame) -> None:  # type: ignore[no-untyped-def]
    """Offer the HTML report as a download."""
    if st.button("Generate HTML report"):
        with st.spinner("Rendering report..."):
            outputs = ReportGenerator(settings).generate(
                report, frame=frame, formats=["html", "summary"]
            )
        html_path = outputs.get("html")
        if html_path:
            st.download_button(
                "Download HTML report",
                data=Path(html_path).read_bytes(),
                file_name=Path(html_path).name,
                mime="text/html",
            )
        st.code(ReportGenerator(settings).render_summary(report))


def _render_compare(baseline: pd.DataFrame, current: pd.DataFrame) -> None:
    """Render schema and data drift between two datasets."""
    schema = SchemaDriftDetector().compare(baseline, current)
    data = DataDriftDetector(settings).compare(baseline, current)

    st.subheader("Schema drift")
    st.write(
        {
            "Added": schema.added_columns,
            "Removed": schema.removed_columns,
            "Type changed": [f"{c.column}: {c.baseline_dtype}->{c.current_dtype}"
                             for c in schema.dtype_changes],
        }
    )
    st.subheader("Data drift")
    drift_df = pd.DataFrame([col.model_dump() for col in data.columns])
    if not drift_df.empty:
        st.dataframe(drift_df, use_container_width=True, hide_index=True)


def render() -> None:
    """Top-level dashboard entry point."""
    st.set_page_config(page_title=settings.dashboard.title, page_icon="", layout="wide")
    st.title(settings.dashboard.title)
    st.caption("Upload a dataset to analyse its quality, or compare two datasets for drift.")

    mode = st.sidebar.radio("Mode", ["Analyse", "Compare"])
    st.sidebar.markdown("---")
    st.sidebar.write(f"Pass threshold: **{settings.scoring.pass_threshold:.0f}%**")

    if mode == "Analyse":
        uploaded = st.file_uploader("Dataset", type=["csv", "xlsx", "xls", "json", "parquet"])
        if uploaded is not None:
            try:
                path = _persist_upload(uploaded)
                frame = _load_dataframe(str(path))
            except DataQualityError as exc:
                st.error(f"Could not load dataset: {exc}")
                return
            _render_analysis(frame, name=Path(uploaded.name).stem, source=uploaded.name)
    else:
        col1, col2 = st.columns(2)
        baseline_file = col1.file_uploader("Baseline", type=["csv", "xlsx", "json", "parquet"])
        current_file = col2.file_uploader("Current", type=["csv", "xlsx", "json", "parquet"])
        if baseline_file is not None and current_file is not None:
            try:
                baseline = _load_dataframe(str(_persist_upload(baseline_file)))
                current = _load_dataframe(str(_persist_upload(current_file)))
            except DataQualityError as exc:
                st.error(f"Could not load datasets: {exc}")
                return
            _render_compare(baseline, current)


render()
