"""Outbound alerting when a dataset's quality regresses.

This is the only component in the system that opens an outbound connection, so
it is treated as a security-sensitive boundary in its own right and is disabled
by default.

The destination is operator-supplied configuration, which makes it a classic
server-side request forgery (SSRF) vector: a webhook pointed at
``http://169.254.169.254/`` or ``http://127.0.0.1:6379/`` would turn a scheduled
quality check into a probe of the host's own network. Every URL is therefore
validated before a byte is sent - scheme, credentials, and *every address the
host name resolves to*.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from dqms import __version__
from dqms.config.settings import Settings, get_settings
from dqms.core.exceptions import SecurityError
from dqms.models.history import RunRecord
from dqms.models.report import AnalysisReport
from dqms.utils.logging import get_logger

_logger = get_logger("dqms.alerts")

# Alert payloads are small; a hostile endpoint must not be able to stream an
# unbounded response back at us.
_MAX_RESPONSE_BYTES = 64 * 1024


@dataclass(frozen=True)
class Alert:
    """One reason a run is considered a regression."""

    reason: str
    detail: str


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse redirects.

    A validated public endpoint could otherwise redirect to a private address,
    defeating the pre-flight check entirely.
    """

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise SecurityError("the alert endpoint attempted a redirect, which is not followed")


def redact_url(url: str) -> str:
    """Return a loggable form of ``url`` with any secret path or query removed.

    Webhook URLs routinely *are* the credential - a Slack or Teams endpoint
    carries its token in the path - so the full URL must never reach a log file.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable url>"
    host = parts.hostname or "<no host>"
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}/<redacted>"


def assert_safe_url(url: str, *, allow_private: bool = False) -> None:
    """Validate an outbound webhook URL, raising :class:`SecurityError` if unsafe.

    Checks, in order:

    * the scheme is HTTP(S), and plain HTTP is refused unless private targets
      were explicitly permitted - an alert can carry dataset names and scores
    * no credentials are embedded in the URL, which would leak them into
      proxies and logs
    * a host name is present
    * **every** address the host resolves to is globally routable

    The last check is the important one, and it is written as an allow-list.
    Validating the host name alone is not enough, because ``localtest.me`` and
    friends resolve to loopback; and denying a list of "private" ranges misses
    space that is not private yet still unroutable, such as carrier-grade NAT.

    A caveat stated plainly: resolution here and connection later are separate
    lookups, so a deliberately hostile DNS server could still rebind between the
    two. Defending against that requires pinning the connection to the validated
    address, which the standard library's opener does not expose. For a webhook
    the operator configures themselves, this check is the proportionate control.
    """
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise SecurityError("alert webhook URL could not be parsed") from exc

    if parts.scheme not in {"http", "https"}:
        raise SecurityError(
            "alert webhook must use http or https", details={"scheme": parts.scheme}
        )
    if parts.scheme == "http" and not allow_private:
        raise SecurityError(
            "alert webhook must use https; set alerts.allow_private_targets to permit plain http",
            details={"url": redact_url(url)},
        )
    if parts.username or parts.password:
        raise SecurityError("alert webhook URL must not embed credentials")

    host = parts.hostname
    if not host:
        raise SecurityError("alert webhook URL has no host")

    if allow_private:
        return

    try:
        resolved = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
    except OSError as exc:
        raise SecurityError(
            "alert webhook host could not be resolved", details={"host": host}
        ) from exc

    for family, _type, _proto, _canon, sockaddr in resolved:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        address = ipaddress.ip_address(str(sockaddr[0]))
        # Allow-list rather than deny-list. Enumerating the bad ranges is a game
        # that is always one range behind - carrier-grade NAT (100.64.0.0/10),
        # the benchmarking range, and the documentation ranges are all neither
        # "private" nor routable. `is_global` is true only for addresses that
        # are actually reachable on the public internet, which is precisely the
        # property a webhook destination must have. Multicast is excluded
        # explicitly: `is_global` considers 224.0.0.0/4 global, but a multicast
        # destination is never a legitimate webhook and reaches the local
        # segment rather than a single host.
        if not address.is_global or address.is_multicast:
            raise SecurityError(
                "alert webhook resolves to an address that is not globally routable",
                details={"host": host, "address": str(address)},
            )


class AlertDispatcher:
    """Decide whether a run warrants an alert, and deliver it."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    # -- decision ----------------------------------------------------------

    def evaluate(
        self, report: AnalysisReport, previous: RunRecord | None = None
    ) -> list[Alert]:
        """Return the reasons ``report`` is a regression, newest state first.

        Evaluation is independent of delivery, so a caller can show the reasons
        on the console whether or not alerting is switched on.
        """
        cfg = self._settings.alerts
        alerts: list[Alert] = []
        score = report.quality.overall_score

        if not report.quality.passed:
            alerts.append(
                Alert(
                    reason="quality_gate_failed",
                    detail=(
                        f"Score {score:.1f}% is below the pass threshold "
                        f"{report.quality.pass_threshold:.1f}%."
                    ),
                )
            )
        elif score < cfg.min_score:
            alerts.append(
                Alert(
                    reason="below_minimum_score",
                    detail=f"Score {score:.1f}% is below the alert floor {cfg.min_score:.1f}%.",
                )
            )

        if previous is not None:
            drop = previous.overall_score - score
            if drop > cfg.max_score_drop:
                alerts.append(
                    Alert(
                        reason="score_dropped",
                        detail=(
                            f"Score fell {drop:.1f} points, from "
                            f"{previous.overall_score:.1f}% to {score:.1f}%, since the run on "
                            f"{previous.run_at:%Y-%m-%d %H:%M} UTC."
                        ),
                    )
                )
        return alerts

    # -- delivery ----------------------------------------------------------

    def build_payload(self, report: AnalysisReport, alerts: list[Alert]) -> dict[str, Any]:
        """Build the JSON body sent to the webhook.

        Only summary statistics are included - never cell values, column names,
        or a file path. An alert crosses a network boundary, so it must not be a
        channel through which the dataset itself leaks.
        """
        return {
            "source": "dqms",
            "version": __version__,
            "dataset": report.dataset_name,
            "generated_at": report.generated_at.isoformat(),
            "overall_score": report.quality.overall_score,
            "grade": report.quality.grade,
            "passed": report.quality.passed,
            "row_count": report.row_count,
            "column_count": report.column_count,
            "validation_issues": report.validation.total_issues,
            "alerts": [{"reason": a.reason, "detail": a.detail} for a in alerts],
        }

    def send(self, report: AnalysisReport, alerts: list[Alert]) -> bool:
        """Deliver ``alerts`` to the configured webhook.

        Returns ``True`` when a request was made and accepted. A misconfigured
        or unreachable endpoint is logged and reported as ``False`` rather than
        raised: a monitoring run should not fail because the notifier is down.
        A *refused* endpoint - one that fails the safety check - is a
        configuration error the operator must see, and is raised.
        """
        cfg = self._settings.alerts
        if not alerts or not cfg.enabled:
            return False
        if not cfg.webhook_url:
            _logger.warning("Alerts are enabled but no webhook URL is configured")
            return False

        assert_safe_url(cfg.webhook_url, allow_private=cfg.allow_private_targets)

        body = json.dumps(self.build_payload(report, alerts)).encode("utf-8")
        # The scheme and destination are validated by assert_safe_url above.
        request = urllib.request.Request(
            cfg.webhook_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "dqms"},
        )
        opener = urllib.request.build_opener(_NoRedirects)
        try:
            with opener.open(request, timeout=cfg.timeout_seconds) as response:
                response.read(_MAX_RESPONSE_BYTES)
                status = int(getattr(response, "status", 0) or 0)
        except urllib.error.HTTPError as exc:
            _logger.warning(
                "Alert webhook {} returned HTTP {}", redact_url(cfg.webhook_url), exc.code
            )
            return False
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            _logger.warning(
                "Alert webhook {} is unreachable: {}", redact_url(cfg.webhook_url), exc
            )
            return False

        _logger.success(
            "Delivered {} alert(s) for '{}' to {} (HTTP {})",
            len(alerts),
            report.dataset_name,
            redact_url(cfg.webhook_url),
            status,
        )
        return True
