"""Data-quality scoring service.

Combines the outputs of profiling, validation, and (optionally) anomaly
detection into a single, explainable 0-100 score across five dimensions.
Each dimension is normalised to a percentage and then weighted according to
configuration, so the overall score is a transparent weighted average rather
than an opaque black box.
"""

from __future__ import annotations

from dqms.config.settings import Settings, get_settings
from dqms.core.constants import QualityDimension
from dqms.models.anomaly import AnomalyReport
from dqms.models.profile import DatasetProfile
from dqms.models.quality import DimensionScore, QualityScore
from dqms.models.validation import ValidationReport
from dqms.utils.logging import get_logger

_logger = get_logger("dqms.scorer")

# Which validation rules count against which quality dimension.
_VALIDITY_RULES = {"invalid_email", "invalid_phone", "invalid_date", "wrong_type"}
_CONSISTENCY_RULES = {"whitespace", "empty_strings", "string_too_long"}
_ACCURACY_RULES = {"below_minimum", "above_maximum", "negative_values"}


class QualityScorer:
    """Compute a weighted, explainable data-quality score."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def score(
        self,
        profile: DatasetProfile,
        validation: ValidationReport,
        anomalies: AnomalyReport | None = None,
    ) -> QualityScore:
        """Return the overall quality score for a dataset.

        Parameters
        ----------
        profile:
            Output of :class:`~dqms.services.profiler.DataProfiler`.
        validation:
            Output of :class:`~dqms.services.validator.DataValidator`.
        anomalies:
            Optional anomaly report; when present it informs the accuracy score.
        """
        total_cells = max(profile.total_cells, 1)
        row_count = max(profile.row_count, 1)

        affected_by_rule = self._affected_by_rule(validation)

        completeness = (1.0 - profile.missing_ratio) * 100.0
        uniqueness = (1.0 - profile.duplicate_row_ratio) * 100.0
        validity = self._penalised_score(affected_by_rule, _VALIDITY_RULES, total_cells)
        consistency = self._penalised_score(affected_by_rule, _CONSISTENCY_RULES, total_cells)
        accuracy = self._accuracy_score(affected_by_rule, anomalies, total_cells, row_count)

        dimension_values = {
            QualityDimension.COMPLETENESS: completeness,
            QualityDimension.UNIQUENESS: uniqueness,
            QualityDimension.VALIDITY: validity,
            QualityDimension.CONSISTENCY: consistency,
            QualityDimension.ACCURACY: accuracy,
        }

        dimensions = self._build_dimension_scores(dimension_values, profile, validation)
        overall = round(sum(dim.weighted_score for dim in dimensions), 2)
        threshold = self._settings.scoring.pass_threshold
        passed = overall >= threshold

        _logger.success("Overall quality score: {:.2f} ({})", overall, "pass" if passed else "fail")
        return QualityScore(
            overall_score=overall,
            passed=passed,
            pass_threshold=threshold,
            dimensions=dimensions,
            summary=self._build_summary(overall, passed, dimensions),
        )

    # -- dimension calculations -------------------------------------------

    def _affected_by_rule(self, validation: ValidationReport) -> dict[str, int]:
        """Sum affected-row counts grouped by validation rule."""
        totals: dict[str, int] = {}
        for issue in validation.issues:
            totals[issue.rule] = totals.get(issue.rule, 0) + issue.affected_count
        return totals

    def _penalised_score(
        self, affected: dict[str, int], rules: set[str], total_cells: int
    ) -> float:
        """Score a dimension as ``100 * (1 - penalty)`` clamped to [0, 100]."""
        penalty_cells = sum(affected.get(rule, 0) for rule in rules)
        penalty_ratio = min(penalty_cells / total_cells, 1.0)
        return round(max(0.0, (1.0 - penalty_ratio) * 100.0), 2)

    def _accuracy_score(
        self,
        affected: dict[str, int],
        anomalies: AnomalyReport | None,
        total_cells: int,
        row_count: int,
    ) -> float:
        """Blend range violations and anomaly density into an accuracy score."""
        range_penalty = min(
            sum(affected.get(rule, 0) for rule in _ACCURACY_RULES) / total_cells, 1.0
        )
        anomaly_penalty = 0.0
        if anomalies is not None and row_count:
            anomaly_penalty = min(anomalies.total_flagged_rows / row_count, 1.0)
        # Weight range violations more heavily than statistical outliers, which
        # can be legitimate extreme values rather than errors.
        combined = min(range_penalty + 0.5 * anomaly_penalty, 1.0)
        return round(max(0.0, (1.0 - combined) * 100.0), 2)

    def _build_dimension_scores(
        self,
        values: dict[QualityDimension, float],
        profile: DatasetProfile,
        validation: ValidationReport,
    ) -> list[DimensionScore]:
        """Assemble :class:`DimensionScore` objects with explanations."""
        weights = self._settings.scoring.weights
        explanations = {
            QualityDimension.COMPLETENESS: (
                f"{profile.missing_cells} of {profile.total_cells} cells are missing "
                f"({profile.missing_ratio:.1%})."
            ),
            QualityDimension.UNIQUENESS: (
                f"{profile.duplicate_row_count} duplicate row(s) detected "
                f"({profile.duplicate_row_ratio:.1%})."
            ),
            QualityDimension.VALIDITY: (
                "Based on invalid emails, phones, dates, and type mismatches."
            ),
            QualityDimension.CONSISTENCY: (
                "Based on whitespace, blank strings, and formatting irregularities."
            ),
            QualityDimension.ACCURACY: (
                "Based on out-of-range values and statistical anomaly density."
            ),
        }
        scores: list[DimensionScore] = []
        for dimension, value in values.items():
            scores.append(
                DimensionScore(
                    dimension=dimension,
                    score=round(value, 2),
                    weight=weights.get(dimension.value, 0.0),
                    explanation=explanations[dimension],
                )
            )
        return scores

    def _build_summary(
        self, overall: float, passed: bool, dimensions: list[DimensionScore]
    ) -> str:
        """Produce a one-line natural-language summary of the score."""
        weakest = min(dimensions, key=lambda d: d.score)
        status = "meets" if passed else "falls below"
        return (
            f"Overall quality is {overall:.1f}%, which {status} the configured "
            f"threshold. Weakest dimension: {weakest.dimension.value} "
            f"({weakest.score:.1f}%)."
        )
