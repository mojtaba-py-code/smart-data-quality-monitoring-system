"""Data-quality scoring models."""

from __future__ import annotations

from pydantic import Field

from dqms.core.constants import QualityDimension
from dqms.models.base import ResultModel


class DimensionScore(ResultModel):
    """Score and rationale for one quality dimension."""

    dimension: QualityDimension
    score: float = Field(ge=0.0, le=100.0, description="Percentage, 0-100")
    weight: float = Field(ge=0.0, le=1.0)
    explanation: str

    @property
    def weighted_score(self) -> float:
        """Contribution of this dimension to the overall score."""
        return self.score * self.weight


class QualityScore(ResultModel):
    """Overall quality score composed of individual dimension scores."""

    overall_score: float = Field(ge=0.0, le=100.0)
    passed: bool
    pass_threshold: float = Field(ge=0.0, le=100.0)
    dimensions: list[DimensionScore] = Field(default_factory=list)
    summary: str = ""

    def dimension(self, dimension: QualityDimension) -> DimensionScore | None:
        """Return the score for a specific dimension, if present."""
        return next((d for d in self.dimensions if d.dimension is dimension), None)

    @property
    def grade(self) -> str:
        """Letter grade derived from the overall score."""
        score = self.overall_score
        if score >= 90:
            return "A"
        if score >= 80:
            return "B"
        if score >= 70:
            return "C"
        if score >= 60:
            return "D"
        return "F"
