"""Models describing past analysis runs."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from dqms.models.base import ResultModel


class RunRecord(ResultModel):
    """One recorded analysis of one dataset.

    A deliberately flat, scalar summary rather than a serialised report: history
    is queried and charted far more often than it is replayed, and keeping the
    row small means years of runs stay cheap to store and fast to scan.
    """

    id: int | None = None
    dataset_name: str
    source_path: str | None = None
    run_at: datetime
    dqms_version: str

    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    overall_score: float = Field(ge=0.0, le=100.0)
    grade: str
    passed: bool

    missing_ratio: float = Field(ge=0.0, le=1.0)
    duplicate_rows: int = Field(ge=0)
    validation_issues: int = Field(ge=0)
    anomaly_rows: int = Field(ge=0)


class TrendPoint(ResultModel):
    """A single point on a dataset's quality timeline."""

    run_at: datetime
    overall_score: float = Field(ge=0.0, le=100.0)
    passed: bool


class DatasetTrend(ResultModel):
    """The quality timeline for one dataset."""

    dataset_name: str
    points: list[TrendPoint] = Field(default_factory=list)

    @property
    def latest(self) -> TrendPoint | None:
        """The most recent point, or ``None`` when the dataset has no history."""
        return self.points[-1] if self.points else None

    @property
    def first(self) -> TrendPoint | None:
        """The oldest point, or ``None`` when the dataset has no history."""
        return self.points[0] if self.points else None

    @property
    def change(self) -> float | None:
        """Score movement from the first recorded run to the latest."""
        if len(self.points) < 2:
            return None
        return round(self.points[-1].overall_score - self.points[0].overall_score, 2)
