"""Tests for run history: the record that turns analysis into monitoring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from dqms.config.settings import Settings
from dqms.models.report import AnalysisReport
from dqms.services.history import HistoryError, RunHistory
from dqms.services.orchestrator import QualityPipeline


@pytest.fixture
def history(settings: Settings, tmp_path: Path) -> RunHistory:
    settings.paths.history_db = tmp_path / "history.db"
    return RunHistory(settings)


def _report(settings: Settings, frame: pd.DataFrame, name: str = "sales") -> AnalysisReport:
    return QualityPipeline(settings).analyze(frame, dataset_name=name, detect_anomalies=False)


def test_database_is_created_on_first_use(history: RunHistory, settings: Settings) -> None:
    assert not history.database_path.exists()
    history.record(_report(settings, pd.DataFrame({"a": [1, 2, 3]})))
    assert history.database_path.is_file()


def test_record_round_trips(history: RunHistory, settings: Settings, clean_frame) -> None:  # type: ignore[no-untyped-def]
    stored = history.record(_report(settings, clean_frame))
    assert stored.id is not None

    [loaded] = history.recent()
    assert loaded.dataset_name == "sales"
    assert loaded.overall_score == stored.overall_score
    assert loaded.row_count == len(clean_frame)
    assert loaded.run_at.tzinfo is not None


def test_recent_is_newest_first_and_respects_limit(
    history: RunHistory, settings: Settings
) -> None:
    for size in (3, 4, 5):
        history.record(_report(settings, pd.DataFrame({"a": range(size)})))
    records = history.recent(limit=2)
    assert len(records) == 2
    assert records[0].run_at >= records[1].run_at


def test_recent_filters_by_dataset(history: RunHistory, settings: Settings) -> None:
    history.record(_report(settings, pd.DataFrame({"a": [1]}), name="alpha"))
    history.record(_report(settings, pd.DataFrame({"a": [1]}), name="beta"))
    assert {r.dataset_name for r in history.recent("alpha")} == {"alpha"}
    assert sorted(history.datasets()) == ["alpha", "beta"]


def test_previous_returns_the_run_before_a_moment(
    history: RunHistory, settings: Settings
) -> None:
    first = history.record(_report(settings, pd.DataFrame({"a": [1, 2]})))
    later = first.run_at + timedelta(hours=1)
    assert history.previous("sales", before=later) is not None
    assert history.previous("sales", before=first.run_at) is None


def test_previous_is_none_for_an_unknown_dataset(history: RunHistory) -> None:
    assert history.previous("never-seen") is None


def test_trend_is_oldest_first_and_reports_movement(
    history: RunHistory, settings: Settings
) -> None:
    good = pd.DataFrame({"value": range(40)})
    poor = pd.DataFrame({"value": [None] * 20 + list(range(20))})
    history.record(_report(settings, good, name="trending"))
    history.record(_report(settings, poor, name="trending"))

    timeline = history.trend("trending")
    assert len(timeline.points) == 2
    assert timeline.points[0].run_at <= timeline.points[1].run_at
    assert timeline.change is not None and timeline.change < 0
    assert timeline.first is not None and timeline.latest is not None


def test_trend_of_a_single_run_reports_no_change(
    history: RunHistory, settings: Settings
) -> None:
    history.record(_report(settings, pd.DataFrame({"a": [1, 2, 3]}), name="solo"))
    assert history.trend("solo").change is None


def test_retention_prunes_the_oldest_runs(
    history: RunHistory, settings: Settings
) -> None:
    settings.history.retention_runs = 3
    for size in range(2, 8):
        history.record(_report(settings, pd.DataFrame({"a": range(size)}), name="capped"))
    assert len(history.recent("capped", limit=100)) == 3


def test_hostile_dataset_name_is_bound_not_interpolated(
    history: RunHistory, settings: Settings
) -> None:
    """A dataset name is derived from a file name, so it is untrusted input."""
    injection = "sales'; DROP TABLE runs; --"
    history.record(_report(settings, pd.DataFrame({"a": [1, 2]}), name=injection))
    # The table survived and the name was stored verbatim rather than executed.
    [record] = history.recent(injection)
    assert record.dataset_name == injection
    assert history.datasets() == [injection]


def test_unusable_database_path_raises_a_domain_error(
    settings: Settings, tmp_path: Path
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    settings.paths.history_db = blocker / "nested" / "history.db"
    with pytest.raises((HistoryError, OSError)):
        RunHistory(settings).record(
            _report(settings, pd.DataFrame({"a": [1]}))
        )


def test_naive_timestamp_is_stored_as_utc(
    history: RunHistory, settings: Settings, clean_frame
) -> None:  # type: ignore[no-untyped-def]
    report = _report(settings, clean_frame)
    naive = report.model_copy(update={"generated_at": datetime(2026, 1, 1, 12, 0)})
    stored = history.record(naive)
    assert stored.run_at.tzinfo is UTC
