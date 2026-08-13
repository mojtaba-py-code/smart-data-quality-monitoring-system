"""Immutable result objects returned by the analysis services.

These Pydantic models are the stable contract between the service layer and the
outer layers (CLI, dashboard, reports). They are fully serialisable, which is
what makes JSON/HTML/PDF report generation and dashboard rendering trivial, and
they all derive from the frozen :class:`~dqms.models.base.ResultModel`, so a
result cannot be edited after the service that produced it has returned.
"""

from __future__ import annotations

from dqms.models.anomaly import AnomalyReport, ColumnAnomaly
from dqms.models.base import ResultModel
from dqms.models.drift import (
    ColumnDrift,
    DataDriftReport,
    SchemaDriftReport,
    SchemaFieldChange,
)
from dqms.models.profile import ColumnProfile, DatasetProfile
from dqms.models.quality import DimensionScore, QualityScore
from dqms.models.report import AnalysisReport, Recommendation
from dqms.models.validation import ColumnValidation, ValidationIssue, ValidationReport

__all__ = [
    "AnalysisReport",
    "AnomalyReport",
    "ColumnAnomaly",
    "ColumnDrift",
    "ColumnProfile",
    "ColumnValidation",
    "DataDriftReport",
    "DatasetProfile",
    "DimensionScore",
    "QualityScore",
    "Recommendation",
    "ResultModel",
    "SchemaDriftReport",
    "SchemaFieldChange",
    "ValidationIssue",
    "ValidationReport",
]
