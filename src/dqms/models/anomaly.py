"""Anomaly-detection result models."""

from __future__ import annotations

from pydantic import Field

from dqms.core.constants import AnomalyMethod
from dqms.models.base import ResultModel


class ColumnAnomaly(ResultModel):
    """Anomalies detected in a single column by a single method."""

    column: str
    method: AnomalyMethod
    anomaly_count: int = Field(ge=0)
    anomaly_ratio: float = Field(ge=0.0, le=1.0)
    lower_bound: float | None = None
    upper_bound: float | None = None
    row_indices: list[int] = Field(
        default_factory=list, description="Zero-based row positions, truncated to a sample"
    )


class AnomalyReport(ResultModel):
    """All anomalies detected across a dataset."""

    row_count: int = Field(ge=0)
    methods: list[AnomalyMethod] = Field(default_factory=list)
    column_results: list[ColumnAnomaly] = Field(default_factory=list)
    multivariate_indices: list[int] = Field(
        default_factory=list,
        description="Zero-based row positions flagged by multivariate detection (Isolation Forest)",
    )

    @property
    def total_flagged_rows(self) -> int:
        """Distinct rows flagged by any method."""
        flagged: set[int] = set(self.multivariate_indices)
        for result in self.column_results:
            flagged.update(result.row_indices)
        return len(flagged)

    def for_column(self, column: str) -> list[ColumnAnomaly]:
        """Return every anomaly result for a given column."""
        return [result for result in self.column_results if result.column == column]
