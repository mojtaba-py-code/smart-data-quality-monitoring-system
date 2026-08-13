"""Tests for the Streamlit dashboard.

The dashboard is a presentation layer, but it is still code that can break, and
until now nothing exercised it. Streamlit's own AppTest harness runs the script
headlessly, which is enough to catch the failures that actually happen here: an
exception during rendering, or a view that silently shows nothing.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from dqms.config.settings import Settings
from dqms.services.history import RunHistory
from dqms.services.orchestrator import QualityPipeline

APP = Path("src/dqms/dashboard/app.py")
TIMEOUT = 60


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AppTest:
    """Run the dashboard against an isolated history database."""
    monkeypatch.setenv("DQMS_PATHS__HISTORY_DB", str(tmp_path / "history.db"))
    monkeypatch.setenv("DQMS_PATHS__LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DQMS_PATHS__OUTPUT_DIR", str(tmp_path / "output"))

    from dqms.config.settings import reset_settings_cache

    reset_settings_cache()
    return AppTest.from_file(str(APP.resolve()), default_timeout=TIMEOUT)


def _seed_history(settings: Settings, database: Path, name: str = "customers") -> None:
    """Record two runs so a timeline exists to render."""
    settings.paths.history_db = database
    history = RunHistory(settings)
    pipeline = QualityPipeline(settings)
    good = pd.DataFrame({"value": range(40)})
    poor = pd.DataFrame({"value": [None] * 15 + list(range(25))})
    for frame in (good, poor):
        history.record(
            pipeline.analyze(frame, dataset_name=name, detect_anomalies=False)
        )


def test_dashboard_starts_without_error(app: AppTest) -> None:
    app.run()
    assert not app.exception
    assert any("Smart Data Quality" in str(t.value) for t in app.title)


def test_the_three_modes_are_offered(app: AppTest) -> None:
    app.run()
    assert not app.exception
    assert list(app.sidebar.radio[0].options) == ["Analyse", "Compare", "History"]


def test_history_view_reports_an_empty_history(app: AppTest) -> None:
    app.run()
    app.sidebar.radio[0].set_value("History").run()
    assert not app.exception
    assert any("No runs recorded yet" in str(item.value) for item in app.info)


def test_history_view_renders_a_recorded_timeline(
    app: AppTest, settings: Settings, tmp_path: Path
) -> None:
    _seed_history(settings, tmp_path / "history.db")

    app.run()
    app.sidebar.radio[0].set_value("History").run()
    assert not app.exception

    assert "customers" in list(app.selectbox[0].options)
    labels = [metric.label for metric in app.metric]
    assert "Runs recorded" in labels
    assert "Since first run" in labels
    assert any(str(metric.value) == "2" for metric in app.metric)


def test_compare_view_renders_without_uploads(app: AppTest) -> None:
    app.run()
    app.sidebar.radio[0].set_value("Compare").run()
    assert not app.exception
