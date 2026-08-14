"""Persistence of analysis runs.

This is what makes the system a *monitor* rather than a one-shot analyser. Every
run can be recorded, so a dataset's quality can be compared against its own past
and a regression can be detected the moment it appears.

SQLite is used deliberately: the store is a single file, needs no server, and is
trivial to back up or inspect with any tool the operator already has. Every
statement is parameterised - dataset names arrive from file names and are treated
as hostile input like everything else that enters the system.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from dqms import __version__
from dqms.config.settings import Settings, get_settings
from dqms.core.exceptions import DataQualityError
from dqms.models.history import DatasetTrend, RunRecord, TrendPoint
from dqms.models.report import AnalysisReport
from dqms.utils.logging import get_logger

_logger = get_logger("dqms.history")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_name      TEXT    NOT NULL,
    source_path       TEXT,
    run_at            TEXT    NOT NULL,
    dqms_version      TEXT    NOT NULL,
    row_count         INTEGER NOT NULL,
    column_count      INTEGER NOT NULL,
    overall_score     REAL    NOT NULL,
    grade             TEXT    NOT NULL,
    passed            INTEGER NOT NULL,
    missing_ratio     REAL    NOT NULL,
    duplicate_rows    INTEGER NOT NULL,
    validation_issues INTEGER NOT NULL,
    anomaly_rows      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_dataset_time ON runs (dataset_name, run_at);
"""

_COLUMNS = (
    "id, dataset_name, source_path, run_at, dqms_version, row_count, column_count, "
    "overall_score, grade, passed, missing_ratio, duplicate_rows, validation_issues, anomaly_rows"
)


class HistoryError(DataQualityError):
    """Raised when the run history cannot be read or written."""


class RunHistory:
    """A durable record of past analysis runs, backed by SQLite."""

    def __init__(self, settings: Settings | None = None, *, database: Path | None = None) -> None:
        self._settings = settings or get_settings()
        self._database = Path(database or self._settings.paths.history_db)

    @property
    def database_path(self) -> Path:
        """Location of the SQLite file backing this history."""
        return self._database

    # -- connection --------------------------------------------------------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection, applying the schema, and always close it."""
        self._database.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(self._database, timeout=10.0)
        except sqlite3.Error as exc:
            raise HistoryError(
                "could not open the run history database",
                details={"path": str(self._database), "error": str(exc)},
            ) from exc
        try:
            with closing(connection):
                connection.row_factory = sqlite3.Row
                connection.executescript(_SCHEMA)
                yield connection
        except sqlite3.Error as exc:
            raise HistoryError(
                "run history operation failed",
                details={"path": str(self._database), "error": str(exc)},
            ) from exc

    # -- writing -----------------------------------------------------------

    def record(self, report: AnalysisReport) -> RunRecord:
        """Persist ``report`` as a new run and return the stored record."""
        anomaly_rows = report.anomalies.total_flagged_rows if report.anomalies else 0
        run_at = report.generated_at
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=UTC)

        values = (
            report.dataset_name,
            report.source_path,
            run_at.isoformat(),
            __version__,
            report.row_count,
            report.column_count,
            report.quality.overall_score,
            report.quality.grade,
            int(report.quality.passed),
            report.profile.missing_ratio,
            report.profile.duplicate_row_count,
            report.validation.total_issues,
            anomaly_rows,
        )
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO runs (dataset_name, source_path, run_at, dqms_version, row_count, "
                "column_count, overall_score, grade, passed, missing_ratio, duplicate_rows, "
                "validation_issues, anomaly_rows) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            connection.commit()
            run_id = int(cursor.lastrowid or 0)

        _logger.info(
            "Recorded run {} for '{}' (score {:.1f})",
            run_id,
            report.dataset_name,
            report.quality.overall_score,
        )
        self._prune(report.dataset_name)
        return RunRecord(
            id=run_id,
            dataset_name=report.dataset_name,
            source_path=report.source_path,
            run_at=run_at,
            dqms_version=__version__,
            row_count=report.row_count,
            column_count=report.column_count,
            overall_score=report.quality.overall_score,
            grade=report.quality.grade,
            passed=report.quality.passed,
            missing_ratio=report.profile.missing_ratio,
            duplicate_rows=report.profile.duplicate_row_count,
            validation_issues=report.validation.total_issues,
            anomaly_rows=anomaly_rows,
        )

    def _prune(self, dataset_name: str) -> None:
        """Drop the oldest runs beyond the configured retention for one dataset."""
        keep = self._settings.history.retention_runs
        if keep is None:
            return
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM runs WHERE dataset_name = ? AND id NOT IN "
                "(SELECT id FROM runs WHERE dataset_name = ? ORDER BY run_at DESC, id DESC "
                "LIMIT ?)",
                (dataset_name, dataset_name, keep),
            )
            connection.commit()

    # -- reading -----------------------------------------------------------

    def recent(self, dataset_name: str | None = None, *, limit: int = 20) -> list[RunRecord]:
        """Return the most recent runs, newest first."""
        # _COLUMNS is a fixed literal; every value is bound as a parameter below.
        query = f"SELECT {_COLUMNS} FROM runs"  # nosec B608 - fixed column list
        parameters: tuple[object, ...] = ()
        if dataset_name is not None:
            query += " WHERE dataset_name = ?"
            parameters = (dataset_name,)
        query += " ORDER BY run_at DESC, id DESC LIMIT ?"
        parameters += (max(1, limit),)

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._to_record(row) for row in rows]

    def previous(self, dataset_name: str, *, before: datetime | None = None) -> RunRecord | None:
        """Return the latest run for ``dataset_name`` strictly before ``before``."""
        cutoff = (before or datetime.now(UTC)).isoformat()
        with self._connect() as connection:
            # _COLUMNS is a fixed literal; dataset_name and cutoff are bound.
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM runs WHERE dataset_name = ? AND run_at < ? "  # nosec B608
                "ORDER BY run_at DESC, id DESC LIMIT 1",
                (dataset_name, cutoff),
            ).fetchone()
        return self._to_record(row) if row else None

    def datasets(self) -> list[str]:
        """Return every dataset name that has at least one recorded run."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT dataset_name FROM runs ORDER BY dataset_name"
            ).fetchall()
        return [str(row["dataset_name"]) for row in rows]

    def trend(self, dataset_name: str, *, limit: int = 50) -> DatasetTrend:
        """Return the score timeline for ``dataset_name``, oldest point first."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT run_at, overall_score, passed FROM runs WHERE dataset_name = ? "
                "ORDER BY run_at DESC, id DESC LIMIT ?",
                (dataset_name, max(1, limit)),
            ).fetchall()
        points = [
            TrendPoint(
                run_at=datetime.fromisoformat(str(row["run_at"])),
                overall_score=float(row["overall_score"]),
                passed=bool(row["passed"]),
            )
            for row in reversed(rows)
        ]
        return DatasetTrend(dataset_name=dataset_name, points=points)

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _to_record(row: sqlite3.Row) -> RunRecord:
        """Map a database row onto a :class:`RunRecord`."""
        return RunRecord(
            id=int(row["id"]),
            dataset_name=str(row["dataset_name"]),
            source_path=row["source_path"],
            run_at=datetime.fromisoformat(str(row["run_at"])),
            dqms_version=str(row["dqms_version"]),
            row_count=int(row["row_count"]),
            column_count=int(row["column_count"]),
            overall_score=float(row["overall_score"]),
            grade=str(row["grade"]),
            passed=bool(row["passed"]),
            missing_ratio=float(row["missing_ratio"]),
            duplicate_rows=int(row["duplicate_rows"]),
            validation_issues=int(row["validation_issues"]),
            anomaly_rows=int(row["anomaly_rows"]),
        )
