"""Command-line interface built with Typer.

The CLI is a thin adapter over the service layer: it parses arguments, invokes
:class:`~dqms.services.orchestrator.QualityPipeline` (and friends), and renders
the results with Rich. All heavy lifting lives in the services, which keeps the
CLI easy to test and mirrors the dashboard's behaviour exactly.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dqms import __version__
from dqms.config.settings import Settings, load_settings
from dqms.core.constants import Severity
from dqms.core.exceptions import DataQualityError
from dqms.services.data_drift import DataDriftDetector
from dqms.services.orchestrator import QualityPipeline
from dqms.services.profiler import DataProfiler
from dqms.services.schema_drift import SchemaDriftDetector
from dqms.services.validator import DataValidator
from dqms.utils.io import export_dataframe
from dqms.utils.logging import configure_logging

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Smart Data Quality Monitoring System - analyse, validate, clean, and monitor datasets.",
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"dqms {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Path to a YAML configuration file."
    ),
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """Initialise settings and logging for every command."""
    settings = load_settings(config)
    configure_logging(settings, force=True)
    ctx.obj = settings


def _pipeline(ctx: typer.Context) -> QualityPipeline:
    settings: Settings = ctx.obj
    return QualityPipeline(settings)


def _fail(message: str, error: DataQualityError | None = None) -> None:
    detail = f": {error}" if error else ""
    console.print(f"[bold red]Error[/bold red] {message}{detail}")
    raise typer.Exit(code=1)


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


@app.command()
def analyze(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="Dataset file to analyse."),
    report: bool = typer.Option(False, "--report/--no-report", help="Also write report files."),
    anomalies: bool = typer.Option(
        True, "--anomalies/--no-anomalies", help="Run anomaly detection."
    ),
    output: Path | None = typer.Option(None, "--output", "-o", help="Report output directory."),
) -> None:
    """Run the full quality pipeline on a dataset and print a summary."""
    pipeline = _pipeline(ctx)
    try:
        result = pipeline.analyze_file(path, detect_anomalies=anomalies)
    except DataQualityError as exc:
        _fail("analysis failed", exc)
        return

    _print_analysis(result)

    if report:
        from dqms.reports.generator import ReportGenerator

        frame = pipeline.load(path)
        outputs = ReportGenerator(ctx.obj).generate(result, frame=frame, output_dir=output)
        for fmt, file_path in outputs.items():
            console.print(f"  [green]{fmt}[/green] -> {file_path}")

    if not result.quality.passed:
        raise typer.Exit(code=2)


@app.command()
def profile(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="Dataset file to profile."),
) -> None:
    """Print per-column descriptive statistics for a dataset."""
    pipeline = _pipeline(ctx)
    try:
        frame = pipeline.load(path)
    except DataQualityError as exc:
        _fail("could not load dataset", exc)
        return
    dataset_profile = DataProfiler().analyze(frame)

    table = Table(title=f"Profile: {path.name}", show_lines=False)
    for column in ("Column", "Type", "Nulls", "Unique", "Min", "Max", "Mean"):
        table.add_column(column, overflow="fold")
    for col in dataset_profile.columns:
        table.add_row(
            col.name,
            col.dtype,
            f"{col.null_ratio:.1%}",
            f"{col.unique_count:,}",
            _fmt(col.minimum),
            _fmt(col.maximum),
            _fmt(col.mean),
        )
    console.print(table)
    console.print(
        f"Rows: {dataset_profile.row_count:,}  Columns: {dataset_profile.column_count}  "
        f"Duplicates: {dataset_profile.duplicate_row_count:,}  "
        f"Missing: {dataset_profile.missing_ratio:.2%}"
    )


@app.command()
def validate(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="Dataset file to validate."),
    strict: bool = typer.Option(
        False,
        "--strict/--no-strict",
        help="Exit with code 2 when any ERROR-severity issue is found, not only CRITICAL ones.",
    ),
) -> None:
    """Validate a dataset and list the detected issues."""
    pipeline = _pipeline(ctx)
    try:
        frame = pipeline.load(path)
    except DataQualityError as exc:
        _fail("could not load dataset", exc)
        return
    report = DataValidator(ctx.obj).analyze(frame)

    if not report.issues:
        console.print("[green]No validation issues detected.[/green]")
        return

    table = Table(title=f"Validation: {path.name}")
    for column in ("Column", "Rule", "Severity", "Affected", "Message"):
        table.add_column(column, overflow="fold")
    for issue in report.issues:
        table.add_row(
            issue.column or "(dataset)",
            issue.rule,
            issue.severity.value,
            f"{issue.affected_count:,}",
            issue.message,
        )
    console.print(table)
    console.print(f"Total affected values: {report.total_issues:,}")

    error_issues = report.by_severity(Severity.ERROR)
    if strict and error_issues:
        console.print(
            f"[red]{len(error_issues)} error-severity issue group(s) found (--strict).[/red]"
        )
        raise typer.Exit(code=2)
    if report.has_blocking_issues:
        raise typer.Exit(code=2)


@app.command()
def clean(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="Dataset file to clean."),
    output: Path = typer.Option(..., "--output", "-o", help="Destination file for cleaned data."),
) -> None:
    """Clean a dataset and export the result."""
    settings: Settings = ctx.obj
    pipeline = _pipeline(ctx)
    try:
        frame = pipeline.load(path)
        result = pipeline.clean(frame)
        written = export_dataframe(
            result.frame, output, sanitize=settings.security.sanitize_exports
        )
    except DataQualityError as exc:
        _fail("cleaning failed", exc)
        return

    console.print(Panel.fit("\n".join(f"- {action}" for action in result.actions) or "No changes.",
                            title="Cleaning actions"))
    console.print(
        f"[green]Cleaned[/green] {result.rows_before:,} -> {result.rows_after:,} rows, "
        f"written to {written}"
    )


@app.command()
def compare(
    ctx: typer.Context,
    baseline: Path = typer.Argument(..., help="Baseline (reference) dataset."),
    current: Path = typer.Argument(..., help="Current dataset to compare."),
) -> None:
    """Compare two datasets for schema and data drift."""
    pipeline = _pipeline(ctx)
    try:
        base_df = pipeline.load(baseline)
        curr_df = pipeline.load(current)
    except DataQualityError as exc:
        _fail("could not load datasets", exc)
        return

    schema = SchemaDriftDetector().compare(base_df, curr_df)
    data = DataDriftDetector(ctx.obj).compare(base_df, curr_df)

    schema_table = Table(title="Schema drift")
    schema_table.add_column("Change")
    schema_table.add_column("Columns", overflow="fold")
    schema_table.add_row("Added", ", ".join(schema.added_columns) or "-")
    schema_table.add_row("Removed", ", ".join(schema.removed_columns) or "-")
    schema_table.add_row(
        "Type changed",
        ", ".join(
            f"{c.column} ({c.baseline_dtype}->{c.current_dtype})"
            for c in schema.dtype_changes
        )
        or "-",
    )
    console.print(schema_table)

    data_table = Table(title="Data drift")
    # Header labels stay ASCII: Windows consoles default to cp1252, which cannot
    # encode symbols such as the Greek delta and would abort rendering.
    for column in ("Column", "PSI", "KS p-value", "Mean change", "Severity"):
        data_table.add_column(column, overflow="fold")
    for col in data.columns:
        data_table.add_row(
            col.column,
            _fmt(col.psi),
            _fmt(col.ks_pvalue),
            _fmt(col.mean_change),
            col.severity,
        )
    console.print(data_table)
    if schema.has_drift or data.has_drift:
        console.print("[yellow]Drift detected.[/yellow]")
        raise typer.Exit(code=2)
    console.print("[green]No significant drift detected.[/green]")


@app.command()
def report(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="Dataset file to report on."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Report output directory."),
    fmt: list[str] | None = typer.Option(
        None, "--format", "-f", help="Report formats (html, pdf, summary). Repeatable."
    ),
) -> None:
    """Generate HTML/PDF/summary reports for a dataset."""
    from dqms.reports.generator import ReportGenerator

    pipeline = _pipeline(ctx)
    try:
        frame = pipeline.load(path)
        result = pipeline.analyze(frame, dataset_name=path.stem, source_path=str(path))
        outputs = ReportGenerator(ctx.obj).generate(
            result, frame=frame, output_dir=output, formats=fmt or None
        )
    except DataQualityError as exc:
        _fail("report generation failed", exc)
        return

    console.print("[green]Reports written:[/green]")
    for fmt_name, file_path in outputs.items():
        console.print(f"  {fmt_name} -> {file_path}")


@app.command()
def dashboard(
    ctx: typer.Context,
    port: int = typer.Option(8501, "--port", "-p", help="Port for the Streamlit server."),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Interface to bind. Defaults to loopback; use 0.0.0.0 to expose on the network.",
    ),
) -> None:
    """Launch the interactive Streamlit dashboard.

    The server binds to loopback by default: the dashboard reads whatever
    dataset the operator uploads, so it is not exposed to the local network
    unless --host is set explicitly.
    """
    import subprocess
    import sys

    settings: Settings = ctx.obj
    app_path = Path(__file__).resolve().parent / "dashboard" / "app.py"
    if not app_path.is_file():
        _fail("dashboard application not found")
    console.print(f"Starting dashboard at http://{host}:{port} ...")
    # nosec B603 - fixed argument vector, no shell, no untrusted input.
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.port",
            str(port),
            # Loopback by default: uploaded datasets stay on this machine.
            "--server.address",
            host,
            # Do not phone home from a tool that handles the operator's data.
            "--browser.gatherUsageStats",
            "false",
            # Propagate the dashboard section of the configuration so the
            # documented options actually take effect in the Streamlit process.
            "--server.maxUploadSize",
            str(settings.dashboard.max_upload_mb),
            "--theme.base",
            settings.dashboard.theme,
        ],
        check=False,
    )


# --------------------------------------------------------------------------
# Rendering helpers
# --------------------------------------------------------------------------


def _print_analysis(result) -> None:  # type: ignore[no-untyped-def]
    """Render the headline analysis summary and top recommendations."""
    quality = result.quality
    colour = "green" if quality.passed else "red"
    console.print(
        Panel.fit(
            f"[bold]{result.dataset_name}[/bold]\n"
            f"Score: [bold {colour}]{quality.overall_score:.1f}%[/bold {colour}] "
            f"(grade {quality.grade})  Status: {'PASS' if quality.passed else 'FAIL'}\n"
            f"Rows: {result.row_count:,}  Columns: {result.column_count}  "
            f"Issues: {result.validation.total_issues:,}",
            title="Analysis summary",
        )
    )
    table = Table(title="Quality dimensions")
    table.add_column("Dimension")
    table.add_column("Score")
    table.add_column("Explanation", overflow="fold")
    for dim in quality.dimensions:
        table.add_row(dim.dimension.value.title(), f"{dim.score:.1f}%", dim.explanation)
    console.print(table)
    if result.recommendations:
        console.print("[bold]Recommendations:[/bold]")
        for rec in result.recommendations:
            console.print(f"  [{rec.severity.value}] {rec.title} - {rec.detail}")


def _fmt(value: object) -> str:
    """Format an optional numeric value for tabular display."""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


__all__ = ["app"]


if __name__ == "__main__":  # pragma: no cover
    app()
