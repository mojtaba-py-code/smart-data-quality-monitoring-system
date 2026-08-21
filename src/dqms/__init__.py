"""Smart Data Quality Monitoring System (DQMS).

An enterprise-grade toolkit for loading, profiling, validating, cleaning,
scoring, and monitoring the quality of tabular datasets. The package is
organised following Clean Architecture: the :mod:`dqms.core` layer holds the
domain contracts and errors, :mod:`dqms.models` holds immutable result objects,
:mod:`dqms.services` holds the use cases, and the outer layers (CLI, dashboard,
reporting) depend inward only.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.3.0"
