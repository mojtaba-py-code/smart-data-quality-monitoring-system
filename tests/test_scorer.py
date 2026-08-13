"""Tests for the quality-scoring service."""

from __future__ import annotations

import pandas as pd

from dqms.config.settings import Settings
from dqms.core.constants import QualityDimension
from dqms.services.profiler import DataProfiler
from dqms.services.scorer import QualityScorer
from dqms.services.validator import DataValidator


def _score(frame: pd.DataFrame, settings: Settings):  # type: ignore[no-untyped-def]
    profile = DataProfiler().analyze(frame)
    validation = DataValidator(settings).analyze(frame)
    return QualityScorer(settings).score(profile, validation)


def test_clean_scores_high(clean_frame: pd.DataFrame, settings: Settings) -> None:
    score = _score(clean_frame, settings)
    assert score.overall_score >= 95
    assert score.passed
    assert score.grade in {"A", "B"}


def test_messy_scores_lower(
    messy_frame: pd.DataFrame, clean_frame: pd.DataFrame, settings: Settings
) -> None:
    messy = _score(messy_frame, settings)
    clean = _score(clean_frame, settings)
    assert messy.overall_score < clean.overall_score


def test_all_dimensions_present(clean_frame: pd.DataFrame, settings: Settings) -> None:
    score = _score(clean_frame, settings)
    dims = {d.dimension for d in score.dimensions}
    assert dims == set(QualityDimension)


def test_weights_reflect_config(clean_frame: pd.DataFrame, settings: Settings) -> None:
    score = _score(clean_frame, settings)
    total_weight = sum(d.weight for d in score.dimensions)
    assert abs(total_weight - 1.0) < 1e-6


def test_completeness_reacts_to_missing(settings: Settings) -> None:
    frame = pd.DataFrame({"a": [1, None, None, None]})
    score = _score(frame, settings)
    completeness = score.dimension(QualityDimension.COMPLETENESS)
    assert completeness is not None
    assert completeness.score < 60


def test_summary_and_grade(clean_frame: pd.DataFrame, settings: Settings) -> None:
    score = _score(clean_frame, settings)
    assert score.summary
    assert score.grade in {"A", "B", "C", "D", "F"}
