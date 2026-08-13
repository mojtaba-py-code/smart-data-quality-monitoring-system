"""Tests for configuration loading and validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dqms.config.settings import (
    ScoringConfig,
    SecurityConfig,
    Settings,
    load_settings,
)
from dqms.core.exceptions import ConfigurationError


def test_defaults_load() -> None:
    cfg = load_settings()
    assert isinstance(cfg, Settings)
    assert 0 < cfg.scoring.pass_threshold <= 100
    assert cfg.security.max_file_size_mb > 0


def test_scoring_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError):
        ScoringConfig(weights={"completeness": 0.5, "validity": 0.2})


def test_scoring_rejects_unknown_dimension() -> None:
    with pytest.raises(ValidationError):
        ScoringConfig(
            weights={
                "completeness": 0.5,
                "validity": 0.2,
                "uniqueness": 0.1,
                "consistency": 0.1,
                "made_up": 0.1,
            }
        )


def test_security_extensions_are_normalised() -> None:
    cfg = SecurityConfig(allowed_extensions=["CSV", ".JSON", "parquet"])
    assert ".csv" in cfg.allowed_extensions
    assert ".json" in cfg.allowed_extensions
    assert ".parquet" in cfg.allowed_extensions


def test_security_max_bytes_property() -> None:
    cfg = SecurityConfig(max_file_size_mb=2)
    assert cfg.max_file_size_bytes == 2 * 1024 * 1024


def test_invalid_log_level_rejected() -> None:
    from dqms.config.settings import LoggingConfig

    with pytest.raises(ValidationError):
        LoggingConfig(level="verbose")


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DQMS_LOGGING__LEVEL", "DEBUG")
    monkeypatch.setenv("DQMS_SECURITY__MAX_FILE_SIZE_MB", "17")
    cfg = load_settings()
    assert cfg.logging.level == "DEBUG"
    assert cfg.security.max_file_size_mb == 17


def test_missing_config_file_raises() -> None:
    with pytest.raises(ConfigurationError):
        load_settings("does/not/exist.yaml")


def test_dashboard_theme_is_validated() -> None:
    from dqms.config.settings import DashboardConfig

    # The value is forwarded to Streamlit's --theme.base flag.
    assert DashboardConfig(theme="DARK").theme == "dark"
    with pytest.raises(ValidationError):
        DashboardConfig(theme="neon")
