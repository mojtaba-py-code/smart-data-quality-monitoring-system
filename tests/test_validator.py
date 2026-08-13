"""Tests for the data-validation service."""

from __future__ import annotations

import pandas as pd

from dqms.config.settings import Settings
from dqms.core.constants import Severity
from dqms.services.validator import DataValidator


def _rules(frame: pd.DataFrame, settings: Settings) -> set[str]:
    report = DataValidator(settings).analyze(frame)
    return {issue.rule for issue in report.issues}


def test_detects_core_rules(messy_frame: pd.DataFrame, settings: Settings) -> None:
    rules = _rules(messy_frame, settings)
    assert "invalid_email" in rules
    assert "invalid_phone" in rules
    assert "invalid_date" in rules
    assert "missing_values" in rules
    assert "duplicate_rows" in rules


def test_empty_and_whitespace(messy_frame: pd.DataFrame, settings: Settings) -> None:
    rules = _rules(messy_frame, settings)
    assert "empty_strings" in rules or "whitespace" in rules


def test_clean_frame_has_few_issues(clean_frame: pd.DataFrame, settings: Settings) -> None:
    report = DataValidator(settings).analyze(clean_frame)
    assert report.total_issues == 0


def test_negative_values_flagged(settings: Settings) -> None:
    settings.validation.treat_negative_as_invalid = True
    frame = pd.DataFrame({"balance": [10, -5, 3, -1]})
    rules = _rules(frame, settings)
    assert "negative_values" in rules


def test_out_of_range(settings: Settings) -> None:
    settings.validation.numeric_max = 100
    frame = pd.DataFrame({"score": [10, 50, 150, 90]})
    report = DataValidator(settings).analyze(frame)
    rules = {issue.rule for issue in report.issues}
    assert "above_maximum" in rules


def test_wrong_type(settings: Settings) -> None:
    frame = pd.DataFrame({"amount": ["1", "2", "three", "4", "5", "6", "7", "8", "9", "10"]})
    rules = _rules(frame, settings)
    assert "wrong_type" in rules


def test_severity_present(messy_frame: pd.DataFrame, settings: Settings) -> None:
    report = DataValidator(settings).analyze(messy_frame)
    severities = {issue.severity for issue in report.issues}
    assert Severity.ERROR in severities
