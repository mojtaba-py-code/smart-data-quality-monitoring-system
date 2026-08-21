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
from dqms.services.alerting import AlertDispatcher
from dqms.services.data_drift import DataDriftDetector
from dqms.services.history import RunHistory
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
    record: bool = typer.Option(
        True, "--record/--no-record", help="Record this run in the history database."
    ),
    output: Path | None = typer.Option(None, "--output", "-o", help="Report output directory."),
) -> None:
    """Run the full quality pipeline on a dataset and print a summary."""
    settings: Settings = ctx.obj
    pipeline = _pipeline(ctx)
    try:
        result = pipeline.analyze_file(path, detect_anomalies=anomalies)
    except DataQualityError as exc:
        _fail("analysis failed", exc)
        return

    # Compare against this dataset's own past before recording the new run, so
    # the comparison is against the previous state rather than against itself.
    previous = None
    if settings.history.enabled:
        try:
            history = RunHistory(settings)
            previous = history.previous(result.dataset_name, before=result.generated_at)
            if record:
                history.record(result)
        except DataQualityError as exc:
            console.print(f"[yellow]Run history unavailable:[/yellow] {exc}")

    _print_analysis(result)
    _report_regression(settings, result, previous)

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
def history(
    ctx: typer.Context,
    dataset: str | None = typer.Option(
        None, "--dataset", "-d", help="Restrict to one dataset name."
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="How many runs to show."),
) -> None:
    """List previously recorded analysis runs, newest first."""
    settings: Settings = ctx.obj
    try:
        records = RunHistory(settings).recent(dataset, limit=limit)
    except DataQualityError as exc:
        _fail("could not read the run history", exc)
        return

    if not records:
        console.print(
            "[yellow]No runs recorded yet.[/yellow] Run 'dqms analyze <file>' to start a history."
        )
        return

    table = Table(title="Run history")
    for column in ("When (UTC)", "Dataset", "Score", "Grade", "Status", "Rows", "Issues"):
        table.add_column(column, overflow="fold")
    for item in records:
        table.add_row(
            item.run_at.strftime("%Y-%m-%d %H:%M"),
            item.dataset_name,
            f"{item.overall_score:.1f}%",
            item.grade,
            "PASS" if item.passed else "FAIL",
            f"{item.row_count:,}",
            f"{item.validation_issues:,}",
        )
    console.print(table)


@app.command()
def trend(
    ctx: typer.Context,
    dataset: str = typer.Argument(..., help="Dataset name, as shown by 'dqms history'."),
    limit: int = typer.Option(30, "--limit", "-n", help="How many runs to plot."),
) -> None:
    """Plot how a dataset's quality score has moved over time."""
    settings: Settings = ctx.obj
    try:
        timeline = RunHistory(settings).trend(dataset, limit=limit)
    except DataQualityError as exc:
        _fail("could not read the run history", exc)
        return

    if not timeline.points:
        console.print(f"[yellow]No recorded runs for '{dataset}'.[/yellow]")
        raise typer.Exit(code=1)

    table = Table(title=f"Quality trend: {dataset}")
    table.add_column("When (UTC)")
    table.add_column("Score")
    table.add_column("Status")
    table.add_column("Chart", overflow="crop")
    for point in timeline.points:
        # Plain ASCII: the bar must render on a legacy Windows code page.
        filled = round(point.overall_score / 2.5)
        colour = "green" if point.passed else "red"
        table.add_row(
            point.run_at.strftime("%Y-%m-%d %H:%M"),
            f"{point.overall_score:.1f}%",
            "PASS" if point.passed else "FAIL",
            f"[{colour}]{'#' * filled}{'.' * (40 - filled)}[/{colour}]",
        )
    console.print(table)

    change = timeline.change
    if change is None:
        console.print("Only one run recorded so far; no movement to report.")
        return
    direction = "improved" if change > 0 else "declined" if change < 0 else "held steady"
    colour = "green" if change > 0 else "red" if change < 0 else "white"
    console.print(
        f"Across {len(timeline.points)} runs the score has "
        f"[{colour}]{direction} by {abs(change):.1f} points[/{colour}]."
    )


@app.command()
def dashboard(
    ctx: typer.Context,
    port: int = typer.Option(8501, "--port", "-p", help="Port for the Streamlit server."),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Interface to bind. Defaults to loopback; use 0.0.0.0 to expose on the network.",
    ),
    open_browser: bool = typer.Option(
        True, "--open/--no-open", help="Open the dashboard in the default browser once it starts."
    ),
) -> None:
    """Launch the interactive Streamlit dashboard.

    The server binds to loopback by default: the dashboard reads whatever
    dataset the operator uploads, so it is not exposed to the local network
    unless --host is set explicitly.
    """
    import importlib.util
    import subprocess
    import sys
    import threading
    import webbrowser

    settings: Settings = ctx.obj
    app_path = Path(__file__).resolve().parent / "dashboard" / "app.py"
    if not app_path.is_file():
        _fail("dashboard application not found")
    # Streamlit ships in the optional `dashboard` extra so the base install
    # stays small; say so plainly instead of failing inside the subprocess.
    if importlib.util.find_spec("streamlit") is None:
        _fail("the dashboard needs Streamlit - install it with: pip install 'dqms[dashboard]'")

    url = f"http://{host}:{port}"
    console.print(f"Starting dashboard at {url} ...")
    if open_browser:
        # Streamlit's own browser launcher is tied to its interactive mode, which
        # also triggers a first-run e-mail prompt on stdin. That prompt hangs any
        # non-interactive caller (a scheduled job, a container, a CI step), so the
        # server is always started headless and the browser is opened from here.
        threading.Timer(2.5, webbrowser.open, args=[url]).start()
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
            # Headless: never block on Streamlit's interactive first-run prompt.
            "--server.headless",
            "true",
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


def _report_regression(settings: Settings, result, previous) -> None:  # type: ignore[no-untyped-def]
    """Show how this run compares with the last one, and alert if configured.

    The comparison is printed whether or not alerting is switched on, so the
    information is never hidden behind a webhook the operator has not set up.
    """
    if previous is not None:
        delta = result.quality.overall_score - previous.overall_score
        arrow = "up" if delta > 0 else "down" if delta < 0 else "level"
        colour = "green" if delta > 0 else "red" if delta < 0 else "white"
        console.print(
            f"Previous run {previous.run_at:%Y-%m-%d %H:%M} UTC scored "
            f"{previous.overall_score:.1f}% - now [{colour}]{arrow} {abs(delta):.1f} points[/"
            f"{colour}]."
        )

    dispatcher = AlertDispatcher(settings)
    alerts = dispatcher.evaluate(result, previous)
    if not alerts:
        return
    console.print("[bold red]Regression detected:[/bold red]")
    for alert in alerts:
        console.print(f"  [{alert.reason}] {alert.detail}")
    try:
        if dispatcher.send(result, alerts):
            console.print("  [green]Alert delivered to the configured webhook.[/green]")
    except DataQualityError as exc:
        # A refused endpoint is a configuration error the operator must see.
        console.print(f"  [yellow]Alert not sent:[/yellow] {exc}")


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
