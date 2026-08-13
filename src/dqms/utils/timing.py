"""Lightweight timing and memory-measurement helpers.

The system logs execution time and memory for expensive operations. These
helpers deliberately avoid heavy third-party dependencies: memory is read from
the standard library where possible so the package stays portable.
"""

from __future__ import annotations

import functools
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, TypeVar

from dqms.utils.logging import get_logger

_F = TypeVar("_F", bound=Callable[..., Any])
_logger = get_logger("dqms.timing")


def current_memory_mb() -> float:
    """Return the current process's resident memory in megabytes.

    Uses :mod:`resource` on POSIX and falls back to :mod:`tracemalloc` on
    platforms (such as Windows) where ``resource`` is unavailable. The value is
    best-effort and intended for logging, not for precise accounting.
    """
    try:
        import resource

        # resource is POSIX-only; on Windows this branch raises ImportError.
        usage = resource.getrusage(  # type: ignore[attr-defined, unused-ignore]
            resource.RUSAGE_SELF  # type: ignore[attr-defined, unused-ignore]
        ).ru_maxrss
        # ru_maxrss is kilobytes on Linux and bytes on macOS.
        import sys

        divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
        return round(float(usage) / divisor, 2)
    except (ImportError, ValueError):  # pragma: no cover - platform dependent
        if tracemalloc.is_tracing():
            current, _ = tracemalloc.get_traced_memory()
            return round(current / (1024 * 1024), 2)
        return 0.0


@dataclass
class Stopwatch:
    """A context manager that measures wall-clock time and memory delta.

    Example
    -------
    >>> with Stopwatch("load") as sw:
    ...     ...
    >>> sw.elapsed_seconds >= 0
    True
    """

    label: str
    log: bool = True
    elapsed_seconds: float = field(default=0.0, init=False)
    memory_before_mb: float = field(default=0.0, init=False)
    memory_after_mb: float = field(default=0.0, init=False)
    _start: float = field(default=0.0, init=False, repr=False)

    def __enter__(self) -> Stopwatch:
        self.memory_before_mb = current_memory_mb()
        self._start = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.elapsed_seconds = round(time.perf_counter() - self._start, 4)
        self.memory_after_mb = current_memory_mb()
        if self.log:
            _logger.info(
                "{} finished in {:.4f}s (memory {:.2f} MB)",
                self.label,
                self.elapsed_seconds,
                self.memory_after_mb,
            )


def timed(label: str | None = None) -> Callable[[_F], _F]:
    """Decorator that logs the execution time of the wrapped callable.

    Parameters
    ----------
    label:
        Optional human-readable label. Defaults to the function's qualified name.
    """

    def decorator(func: _F) -> _F:
        name = label or func.__qualname__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - start
                _logger.debug("{} took {:.4f}s", name, elapsed)

        return wrapper  # type: ignore[return-value]

    return decorator
