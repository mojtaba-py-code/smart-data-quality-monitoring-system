"""Aggregate analysis report model.

:class:`AnalysisReport` is the single object handed to the report generators and
the dashboard. It bundles every individual result so downstream consumers never
have to re-run analysis to render a view.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from dqms.core.constants import Severity
from dqms.models.anomaly import AnomalyReport
from dqms.models.base import ResultModel
from dqms.models.profile import DatasetProfile
from dqms.models.quality import QualityScore
from dqms.models.validation import ValidationReport


class Recommendation(ResultModel):
    """An actionable suggestion derived from the analysis."""

    severity: Severity
    title: str
    detail: str


class AnalysisReport(ResultModel):
    """The complete quality assessment for one dataset."""

    dataset_name: str
    source_path: str | None = None
    generated_at: datetime
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)

    profile: DatasetProfile
    validation: ValidationReport
    quality: QualityScore
    anomalies: AnomalyReport | None = None
    recommendations: list[Recommendation] = Field(default_factory=list)

    def to_summary_dict(self) -> dict[str, object]:
        """Return a compact, human-friendly summary mapping.

        Used by the CLI table view and the plain-text summary report.
        """
        return {
            "dataset": self.dataset_name,
            "generated_at": self.generated_at.isoformat(timespec="seconds"),
            "rows": self.row_count,
            "columns": self.column_count,
            "overall_score": round(self.quality.overall_score, 2),
            "grade": self.quality.grade,
            "passed": self.quality.passed,
            "validation_issues": self.validation.total_issues,
            "duplicate_rows": self.profile.duplicate_row_count,
            "missing_ratio": round(self.profile.missing_ratio, 4),
        }
