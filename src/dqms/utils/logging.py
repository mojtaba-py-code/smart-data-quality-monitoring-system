"""Centralised logging configuration built on Loguru.

The rest of the codebase never calls ``print``; it asks for a bound logger via
:func:`get_logger`. Configuration is idempotent so that importing modules in any
order - or reconfiguring from the CLI - never produces duplicate log lines.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from dqms.config.settings import Settings

_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{extra[component]}</cyan> - <level>{message}</level>"
)

# Guards against attaching duplicate sinks when configure_logging runs twice.
_CONFIGURED = False


def _patch_component(record: Any) -> None:
    """Ensure every record has a ``component`` field for the console format."""
    record["extra"].setdefault("component", record["name"])


def _console_sink(message: Any) -> None:
    """Write to the *current* stderr.

    Resolving ``sys.stderr`` at write time (rather than capturing it when the
    sink is registered) keeps logging robust when the stream is swapped out -
    for example by pytest's output capture between tests.
    """
    sys.stderr.write(str(message))


def configure_logging(settings: Settings | None = None, *, force: bool = False) -> None:
    """Initialise the global logger from the provided settings.

    Parameters
    ----------
    settings:
        Application settings. When ``None`` the cached settings are loaded.
    force:
        Re-apply configuration even if it was already applied once. Useful when
        the CLI switches configuration files mid-process.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    if settings is None:
        from dqms.config.settings import get_settings

        settings = get_settings()

    logger.remove()
    logger.configure(patcher=_patch_component)

    logger.add(
        _console_sink,
        level=settings.logging.level,
        format=_CONSOLE_FORMAT,
        colorize=True,
        backtrace=False,
        diagnose=False,
        enqueue=False,
    )

    log_dir: Path = settings.paths.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / "dqms.log",
        level=settings.logging.level,
        rotation=settings.logging.rotation,
        retention=settings.logging.retention,
        compression="zip",
        serialize=settings.logging.json_logs,
        enqueue=True,
        backtrace=False,
        # Never let secrets leak through tracebacks written to disk.
        diagnose=False,
    )

    _CONFIGURED = True
    logger.bind(component="dqms.logging").debug(
        "Logging configured at level {}", settings.logging.level
    )


def get_logger(component: str) -> Any:
    """Return a logger bound to a named component.

    Using a bound ``component`` keeps log lines attributable to the module that
    produced them regardless of Loguru's call-site detection.
    """
    return logger.bind(component=component)
