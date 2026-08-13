"""Pipeline orchestration.

:class:`QualityPipeline` is the single façade the outer layers (CLI, dashboard,
reports) call. It wires the individual services together in the correct order,
derives actionable recommendations, and returns one self-contained
:class:`AnalysisReport`. Keeping this composition in one place means the CLI and
dashboard never duplicate orchestration logic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from dqms.config.settings import Settings, get_settings
from dqms.core.constants import Severity
from dqms.models.profile import DatasetProfile
from dqms.models.quality import QualityScore
from dqms.models.report import AnalysisReport, Recommendation
from dqms.models.validation import ValidationReport
from dqms.services.anomaly import AnomalyDetector
from dqms.services.cleaner import CleaningResult, DataCleaner
from dqms.services.loader import FileLoader
from dqms.services.profiler import DataProfiler
from dqms.services.scorer import QualityScorer
from dqms.services.validator import DataValidator
from dqms.utils.logging import get_logger
from dqms.utils.timing import Stopwatch

_logger = get_logger("dqms.pipeline")


class QualityPipeline:
    """Coordinate loading, profiling, validation, scoring, and anomaly detection."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._loader = FileLoader(self._settings)
        self._profiler = DataProfiler()
        self._validator = DataValidator(self._settings)
        self._scorer = QualityScorer(self._settings)
        self._anomaly = AnomalyDetector(self._settings)
        self._cleaner = DataCleaner(self._settings)

    # -- public API --------------------------------------------------------

    def load(self, path: str | Path) -> pd.DataFrame:
        """Load a dataset file through the secure loader."""
        return self._loader.load(path)

    def clean(self, frame: pd.DataFrame) -> CleaningResult:
        """Run the cleaning service against a DataFrame."""
        return self._cleaner.clean(frame)

    def analyze_file(self, path: str | Path, *, detect_anomalies: bool = True) -> AnalysisReport:
        """Load a file and run the full analysis pipeline over it."""
        resolved = Path(path)
        frame = self._loader.load(resolved)
        return self.analyze(
            frame,
            dataset_name=resolved.stem,
            source_path=str(resolved),
            detect_anomalies=detect_anomalies,
        )

    def analyze(
        self,
        frame: pd.DataFrame,
        *,
        dataset_name: str,
        source_path: str | None = None,
        detect_anomalies: bool = True,
    ) -> AnalysisReport:
        """Run the full analysis pipeline over an in-memory DataFrame.

        Parameters
        ----------
        frame:
            The dataset to analyse.
        dataset_name:
            Logical name used in reports and output file names.
        source_path:
            Optional original file path, recorded in the report.
        detect_anomalies:
            Whether to run (potentially slower) anomaly detection.
        """
        _logger.info("Starting analysis of '{}'", dataset_name)
        with Stopwatch(f"analyze[{dataset_name}]"):
            profile = self._profiler.analyze(frame)
            validation = self._validator.analyze(frame)
            anomalies = self._anomaly.detect(frame) if detect_anomalies else None
            quality = self._scorer.score(profile, validation, anomalies)

        report = AnalysisReport(
            dataset_name=dataset_name,
            source_path=source_path,
            generated_at=datetime.now(UTC),
            row_count=profile.row_count,
            column_count=profile.column_count,
            profile=profile,
            validation=validation,
            quality=quality,
            anomalies=anomalies,
            recommendations=self._build_recommendations(profile, validation, quality),
        )
        _logger.success(
            "Analysis of '{}' complete (score {:.1f})", dataset_name, quality.overall_score
        )
        return report

    # -- recommendations ---------------------------------------------------

    def _build_recommendations(
        self,
        profile: DatasetProfile,
        validation: ValidationReport,
        quality: QualityScore,
    ) -> list[Recommendation]:
        """Translate the numeric results into prioritised, actionable advice."""
        recommendations: list[Recommendation] = []

        if profile.missing_ratio > 0.05:
            recommendations.append(
                Recommendation(
                    severity=Severity.WARNING,
                    title="Address missing values",
                    detail=(
                        f"{profile.missing_ratio:.1%} of cells are missing. Run the "
                        "cleaning command to impute or drop them before downstream use."
                    ),
                )
            )
        if profile.duplicate_row_count > 0:
            recommendations.append(
                Recommendation(
                    severity=Severity.WARNING,
                    title="Remove duplicate rows",
                    detail=(
                        f"{profile.duplicate_row_count} duplicate row(s) were found. "
                        "De-duplication is recommended to avoid double counting."
                    ),
                )
            )

        rule_counts: dict[str, int] = {}
        for issue in validation.issues:
            rule_counts[issue.rule] = rule_counts.get(issue.rule, 0) + issue.affected_count
        for rule in ("invalid_email", "invalid_phone", "invalid_date", "wrong_type"):
            if rule_counts.get(rule):
                recommendations.append(
                    Recommendation(
                        severity=Severity.ERROR,
                        title=f"Fix {rule.replace('_', ' ')} values",
                        detail=(
                            f"{rule_counts[rule]} value(s) failed the '{rule}' rule. "
                            "Correct at source or quarantine the affected records."
                        ),
                    )
                )

        for dimension in quality.dimensions:
            if dimension.score < 70:
                recommendations.append(
                    Recommendation(
                        severity=Severity.WARNING,
                        title=f"Improve {dimension.dimension.value}",
                        detail=(
                            f"The {dimension.dimension.value} score is "
                            f"{dimension.score:.1f}%. {dimension.explanation}"
                        ),
                    )
                )

        if not recommendations:
            recommendations.append(
                Recommendation(
                    severity=Severity.INFO,
                    title="No critical issues detected",
                    detail="The dataset meets the configured quality expectations.",
                )
            )
        return recommendations
