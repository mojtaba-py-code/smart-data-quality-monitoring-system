"""Tests for outbound alerting, and for the SSRF guard protecting it.

The webhook destination is operator-supplied configuration, which makes it the
one place where this tool can be talked into making a request on someone else's
behalf. The guard is therefore tested as an allow-list: everything that is not
globally routable must be refused.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from dqms.config.settings import Settings
from dqms.core.exceptions import SecurityError
from dqms.models.history import RunRecord
from dqms.services.alerting import AlertDispatcher, assert_safe_url, redact_url
from dqms.services.orchestrator import QualityPipeline

BLOCKED_TARGETS = [
    pytest.param("https://169.254.169.254/latest/meta-data/", id="cloud-metadata"),
    pytest.param("https://127.0.0.1/hook", id="loopback"),
    pytest.param("https://localhost/hook", id="loopback-by-name"),
    pytest.param("https://[::1]/hook", id="ipv6-loopback"),
    pytest.param("https://10.1.2.3/hook", id="rfc1918-10"),
    pytest.param("https://172.20.3.4/hook", id="rfc1918-172"),
    pytest.param("https://192.168.1.1/hook", id="rfc1918-192"),
    pytest.param("https://100.64.0.1/hook", id="carrier-grade-nat"),
    pytest.param("https://198.18.0.1/hook", id="benchmarking-range"),
    pytest.param("https://192.0.2.5/hook", id="test-net-1"),
    pytest.param("https://[fd00::1]/hook", id="ipv6-unique-local"),
    pytest.param("https://224.0.0.1/hook", id="ipv4-multicast"),
    pytest.param("https://[ff02::1]/hook", id="ipv6-multicast"),
    pytest.param("https://0.0.0.0/hook", id="unspecified"),
]


@pytest.mark.parametrize("url", BLOCKED_TARGETS)
def test_non_routable_targets_are_refused(url: str) -> None:
    with pytest.raises(SecurityError):
        assert_safe_url(url)


@pytest.mark.parametrize(
    "url",
    ["file:///C:/Windows/win.ini", "gopher://example.com/x", "ftp://example.com/x"],
)
def test_non_http_schemes_are_refused(url: str) -> None:
    with pytest.raises(SecurityError, match="http or https"):
        assert_safe_url(url)


def test_plain_http_is_refused_without_explicit_opt_in() -> None:
    with pytest.raises(SecurityError, match="https"):
        assert_safe_url("http://example.com/hook")


def test_credentials_in_the_url_are_refused() -> None:
    with pytest.raises(SecurityError, match="credentials"):
        assert_safe_url("https://user:secret@example.com/hook")


def test_missing_host_is_refused() -> None:
    with pytest.raises(SecurityError, match="host"):
        assert_safe_url("https:///nohost")


def test_a_public_https_endpoint_is_permitted() -> None:
    assert_safe_url("https://example.com/services/T000/B000/token")


def test_opt_in_permits_a_local_endpoint() -> None:
    """Operators running their own receiver on localhost must be able to say so."""
    assert_safe_url("http://127.0.0.1:9000/hook", allow_private=True)


def test_redaction_keeps_the_secret_out_of_logs() -> None:
    redacted = redact_url("https://hooks.example.com/services/T00/B00/SUPERSECRET")
    assert "SUPERSECRET" not in redacted
    assert "hooks.example.com" in redacted


# -- alert decisions --------------------------------------------------------


def _record(score: float) -> RunRecord:
    return RunRecord(
        dataset_name="sales",
        run_at=datetime(2026, 1, 1, tzinfo=UTC),
        dqms_version="1.0.0",
        row_count=100,
        column_count=5,
        overall_score=score,
        grade="A",
        passed=True,
        missing_ratio=0.0,
        duplicate_rows=0,
        validation_issues=0,
        anomaly_rows=0,
    )


def _analyse(settings: Settings, frame: pd.DataFrame):  # type: ignore[no-untyped-def]
    return QualityPipeline(settings).analyze(
        frame, dataset_name="sales", detect_anomalies=False
    )


def test_clean_data_with_no_history_raises_no_alert(
    settings: Settings, clean_frame: pd.DataFrame
) -> None:
    report = _analyse(settings, clean_frame)
    assert AlertDispatcher(settings).evaluate(report) == []


def test_a_failing_gate_raises_an_alert(settings: Settings) -> None:
    settings.scoring.pass_threshold = 99.9
    report = _analyse(settings, pd.DataFrame({"a": [1, None, 1]}))
    reasons = {alert.reason for alert in AlertDispatcher(settings).evaluate(report)}
    assert "quality_gate_failed" in reasons


def test_a_score_drop_raises_an_alert(settings: Settings, messy_frame: pd.DataFrame) -> None:
    report = _analyse(settings, messy_frame)
    assert report.quality.overall_score < 100.0  # the drop must be representable
    settings.alerts.max_score_drop = 1.0
    previous = _record(100.0)
    reasons = {a.reason for a in AlertDispatcher(settings).evaluate(report, previous)}
    assert "score_dropped" in reasons


def test_a_small_movement_does_not_raise_an_alert(
    settings: Settings, clean_frame: pd.DataFrame
) -> None:
    report = _analyse(settings, clean_frame)
    settings.alerts.max_score_drop = 5.0
    previous = _record(min(100.0, report.quality.overall_score + 0.5))
    assert AlertDispatcher(settings).evaluate(report, previous) == []


def test_payload_carries_only_summary_statistics(
    settings: Settings, messy_frame: pd.DataFrame
) -> None:
    """An alert crosses a network boundary; the dataset must not ride along."""
    report = QualityPipeline(settings).analyze(
        messy_frame, dataset_name="sales", source_path="/srv/private/customers.csv"
    )
    dispatcher = AlertDispatcher(settings)
    payload = dispatcher.build_payload(report, dispatcher.evaluate(report))

    serialised = str(payload)
    assert "a@example.com" not in serialised  # no cell values
    assert "/srv/private" not in serialised  # no source path
    assert payload["dataset"] == "sales"
    assert set(payload) >= {"overall_score", "grade", "passed", "alerts"}


def test_nothing_is_sent_while_alerting_is_disabled(
    settings: Settings, messy_frame: pd.DataFrame
) -> None:
    """Disabled means no outbound request, even with alerts and a URL present."""
    settings.scoring.pass_threshold = 100.0
    settings.alerts.enabled = False
    settings.alerts.webhook_url = "https://example.com/hook"
    report = _analyse(settings, messy_frame)
    dispatcher = AlertDispatcher(settings)
    alerts = dispatcher.evaluate(report)
    assert alerts  # there is something to send...
    assert dispatcher.send(report, alerts) is False  # ...and it is not sent


def test_enabled_alerting_refuses_an_unsafe_webhook(
    settings: Settings, messy_frame: pd.DataFrame
) -> None:
    settings.scoring.pass_threshold = 100.0
    settings.alerts.enabled = True
    settings.alerts.webhook_url = "https://169.254.169.254/hook"
    report = _analyse(settings, messy_frame)
    dispatcher = AlertDispatcher(settings)
    alerts = dispatcher.evaluate(report)
    assert alerts
    with pytest.raises(SecurityError):
        dispatcher.send(report, alerts)


def test_enabled_alerting_without_a_url_is_a_no_op(
    settings: Settings, messy_frame: pd.DataFrame
) -> None:
    settings.scoring.pass_threshold = 100.0
    settings.alerts.enabled = True
    settings.alerts.webhook_url = None
    report = _analyse(settings, messy_frame)
    dispatcher = AlertDispatcher(settings)
    assert dispatcher.send(report, dispatcher.evaluate(report)) is False
