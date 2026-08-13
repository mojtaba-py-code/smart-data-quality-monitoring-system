"""Abstract contracts shared across the application.

These Protocols and abstract base classes express the *dependency inversion*
part of SOLID: outer layers depend on these abstractions, not on concrete
implementations. New file formats, exporters, or anomaly strategies can be
added by implementing the relevant contract without touching existing code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol, runtime_checkable

import pandas as pd

from dqms.core.constants import FileFormat


@runtime_checkable
class DataLoader(Protocol):
    """A component that turns a file on disk into a :class:`pandas.DataFrame`."""

    def supports(self, fmt: FileFormat) -> bool:
        """Return ``True`` if this loader can read the given format."""
        ...

    def load(self, path: Path, **options: object) -> pd.DataFrame:
        """Read ``path`` and return a DataFrame, raising on failure."""
        ...


@runtime_checkable
class DataExporter(Protocol):
    """A component that writes a :class:`pandas.DataFrame` to disk."""

    def export(self, frame: pd.DataFrame, path: Path, **options: object) -> Path:
        """Write ``frame`` to ``path`` and return the path actually written."""
        ...


class AnalysisComponent(ABC):
    """Base class for stateless analysis services.

    Concrete services (profiler, validator, scorer, ...) implement
    :meth:`analyze`. Keeping a common base makes them interchangeable in the
    orchestrator and simplifies testing.
    """

    @property
    def name(self) -> str:
        """Human readable component name, defaults to the class name."""
        return type(self).__name__

    @abstractmethod
    def analyze(self, frame: pd.DataFrame) -> object:
        """Run the component against ``frame`` and return its result object."""
        raise NotImplementedError
