"""Strongly-typed application settings.

The configuration is layered so that operators can rely on sensible defaults
while still overriding anything per environment:

1. Hard-coded defaults in the model definitions below.
2. Values from a YAML file (``config/config.yaml`` by default).
3. Environment variables (prefix ``DQMS_``, nesting delimiter ``__``).
4. A local ``.env`` file (same naming as environment variables).

Environment variables always take precedence over the YAML file, which makes
the system twelve-factor friendly and keeps secrets out of version control.
Everything is validated by Pydantic at load time, so an invalid configuration
fails fast with a clear error instead of surfacing deep inside a pipeline.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from dqms.core.constants import AnomalyMethod, QualityDimension
from dqms.core.exceptions import ConfigurationError

_DEFAULT_CONFIG_FILENAME = "config.yaml"


def _default_config_path() -> Path:
    """Locate the default YAML config, preferring one next to the project root.

    Resolution order: the ``config/config.yaml`` under the current working
    directory (typical when running from a checkout), otherwise the copy
    bundled two levels above this file. A missing file is not an error - the
    built-in defaults are used instead.
    """
    cwd_candidate = Path.cwd() / "config" / _DEFAULT_CONFIG_FILENAME
    if cwd_candidate.is_file():
        return cwd_candidate
    packaged = Path(__file__).resolve().parents[3] / "config" / _DEFAULT_CONFIG_FILENAME
    return packaged


# Holds the YAML path used by the settings source. It is a module-level holder
# so that ``load_settings`` can point the source at a custom file before the
# Settings object is instantiated.
_CONFIG_FILE_HOLDER: dict[str, Path] = {"path": _default_config_path()}


class PathsConfig(BaseModel):
    """Filesystem locations used across the system."""

    input_dir: Path = Path("./data/input")
    output_dir: Path = Path("./output")
    log_dir: Path = Path("./logs")


class LoggingConfig(BaseModel):
    """Logging behaviour (see :mod:`dqms.utils.logging`)."""

    level: str = "INFO"
    json_logs: bool = False
    rotation: str = "10 MB"
    retention: str = "14 days"

    @field_validator("level")
    @classmethod
    def _normalise_level(cls, value: str) -> str:
        allowed = {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"log level must be one of {sorted(allowed)}, got {value!r}")
        return upper


class SecurityConfig(BaseModel):
    """Security boundaries enforced by the loader and exporters."""

    max_file_size_mb: int = Field(default=512, ge=1, le=1_000_000)
    allow_symlinks: bool = False
    allowed_extensions: list[str] = Field(
        default_factory=lambda: [
            ".csv",
            ".tsv",
            ".txt",
            ".xlsx",
            ".xlsm",
            ".xls",
            ".json",
            ".parquet",
            ".pq",
        ]
    )
    restrict_to_input_dir: bool = False
    sanitize_exports: bool = True

    @field_validator("allowed_extensions")
    @classmethod
    def _normalise_extensions(cls, value: list[str]) -> list[str]:
        normalised = []
        for ext in value:
            ext = ext.strip().lower()
            if not ext.startswith("."):
                ext = f".{ext}"
            normalised.append(ext)
        if not normalised:
            raise ValueError("allowed_extensions must not be empty")
        return normalised

    @property
    def max_file_size_bytes(self) -> int:
        """Maximum accepted file size expressed in bytes."""
        return self.max_file_size_mb * 1024 * 1024


class LoaderConfig(BaseModel):
    """Tuning knobs for the file loader."""

    chunk_size: int = Field(default=100_000, ge=1_000)
    large_file_threshold_mb: int = Field(default=100, ge=1)
    sample_rows: int | None = Field(default=None, ge=1)
    csv_delimiter: str | None = None
    encoding: str | None = None

    @property
    def large_file_threshold_bytes(self) -> int:
        """Size at which chunked reading kicks in, in bytes."""
        return self.large_file_threshold_mb * 1024 * 1024


class ValidationConfig(BaseModel):
    """Rules that drive the validation service."""

    email_column_hints: list[str] = Field(default_factory=lambda: ["email", "e_mail", "mail"])
    phone_column_hints: list[str] = Field(
        default_factory=lambda: ["phone", "mobile", "tel", "telephone", "cell"]
    )
    date_column_hints: list[str] = Field(
        default_factory=lambda: ["date", "dob", "created", "updated", "timestamp", "time"]
    )
    max_string_length: int = Field(default=10_000, ge=1)
    numeric_min: float | None = None
    numeric_max: float | None = None
    treat_negative_as_invalid: bool = False


class CleaningConfig(BaseModel):
    """Behaviour of the automatic cleaning service."""

    trim_whitespace: bool = True
    collapse_internal_whitespace: bool = True
    standardize_column_names: bool = True
    drop_duplicate_rows: bool = True
    missing_numeric_strategy: str = "median"
    missing_categorical_strategy: str = "mode"
    missing_fill_constant: str = "UNKNOWN"
    normalize_text_case: str = "none"

    @field_validator("missing_numeric_strategy")
    @classmethod
    def _check_numeric_strategy(cls, value: str) -> str:
        allowed = {"mean", "median", "zero", "drop", "none"}
        if value not in allowed:
            raise ValueError(f"missing_numeric_strategy must be one of {sorted(allowed)}")
        return value

    @field_validator("missing_categorical_strategy")
    @classmethod
    def _check_categorical_strategy(cls, value: str) -> str:
        allowed = {"mode", "constant", "drop", "none"}
        if value not in allowed:
            raise ValueError(f"missing_categorical_strategy must be one of {sorted(allowed)}")
        return value

    @field_validator("normalize_text_case")
    @classmethod
    def _check_case(cls, value: str) -> str:
        allowed = {"lower", "upper", "title", "none"}
        if value not in allowed:
            raise ValueError(f"normalize_text_case must be one of {sorted(allowed)}")
        return value


class ScoringConfig(BaseModel):
    """Weights and thresholds for the quality score."""

    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "completeness": 0.25,
            "validity": 0.25,
            "uniqueness": 0.20,
            "consistency": 0.15,
            "accuracy": 0.15,
        }
    )
    pass_threshold: float = Field(default=80.0, ge=0.0, le=100.0)

    @model_validator(mode="after")
    def _check_weights(self) -> ScoringConfig:
        known = {dim.value for dim in QualityDimension}
        unknown = set(self.weights) - known
        if unknown:
            raise ValueError(f"unknown scoring dimensions: {sorted(unknown)}")
        total = sum(self.weights.values())
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(f"scoring weights must sum to 1.0, got {total:.4f}")
        return self


class AnomalyConfig(BaseModel):
    """Anomaly-detection configuration."""

    methods: list[AnomalyMethod] = Field(
        default_factory=lambda: [AnomalyMethod.ZSCORE, AnomalyMethod.IQR]
    )
    zscore_threshold: float = Field(default=3.0, gt=0)
    iqr_multiplier: float = Field(default=1.5, gt=0)
    isolation_forest_contamination: float = Field(default=0.05, gt=0, le=0.5)
    random_state: int = 42


class DriftConfig(BaseModel):
    """Thresholds for schema and data drift detection."""

    psi_warning: float = Field(default=0.1, gt=0)
    psi_critical: float = Field(default=0.25, gt=0)
    ks_pvalue_alpha: float = Field(default=0.05, gt=0, lt=1)
    numeric_bins: int = Field(default=10, ge=2, le=1000)

    @model_validator(mode="after")
    def _check_bands(self) -> DriftConfig:
        if self.psi_warning >= self.psi_critical:
            raise ValueError("psi_warning must be lower than psi_critical")
        return self


class DashboardConfig(BaseModel):
    """Streamlit dashboard presentation options."""

    title: str = "Smart Data Quality Monitoring System"
    theme: str = "light"
    max_upload_mb: int = Field(default=200, ge=1)

    @field_validator("theme")
    @classmethod
    def _check_theme(cls, value: str) -> str:
        # The value is forwarded to Streamlit's --theme.base flag, which only
        # accepts these two bases; validating here fails fast with a clear error.
        allowed = {"light", "dark"}
        lowered = value.strip().lower()
        if lowered not in allowed:
            raise ValueError(f"theme must be one of {sorted(allowed)}, got {value!r}")
        return lowered


class ReportConfig(BaseModel):
    """Report generation options."""

    company_name: str = "Data Engineering"
    include_charts: bool = True
    formats: list[str] = Field(default_factory=lambda: ["html", "pdf"])

    @field_validator("formats")
    @classmethod
    def _check_formats(cls, value: list[str]) -> list[str]:
        allowed = {"html", "pdf", "summary"}
        lowered = [item.lower() for item in value]
        unknown = set(lowered) - allowed
        if unknown:
            raise ValueError(f"unknown report formats: {sorted(unknown)}")
        return lowered


class Settings(BaseSettings):
    """Root settings object composed of the sections defined above."""

    model_config = SettingsConfigDict(
        env_prefix="DQMS_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    paths: PathsConfig = Field(default_factory=PathsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    loader: LoaderConfig = Field(default_factory=LoaderConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    cleaning: CleaningConfig = Field(default_factory=CleaningConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    anomaly: AnomalyConfig = Field(default_factory=AnomalyConfig)
    drift: DriftConfig = Field(default_factory=DriftConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Insert the YAML source below environment variables in priority."""
        yaml_source = YamlConfigSettingsSource(
            settings_cls, yaml_file=_CONFIG_FILE_HOLDER["path"]
        )
        return (init_settings, env_settings, dotenv_settings, yaml_source, file_secret_settings)

    def ensure_directories(self) -> None:
        """Create the output and log directories if they do not yet exist.

        The input directory is intentionally left untouched - it is a source
        location that the operator is expected to populate.
        """
        for directory in (self.paths.output_dir, self.paths.log_dir):
            directory.mkdir(parents=True, exist_ok=True)


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Build a :class:`Settings` instance from a specific config file.

    Parameters
    ----------
    config_path:
        Path to a YAML configuration file. When ``None`` the default lookup
        (current-directory ``config/config.yaml`` then packaged default) is
        used. A non-existent path raises :class:`ConfigurationError`.
    """
    if config_path is not None:
        resolved = Path(config_path).expanduser()
        if not resolved.is_file():
            raise ConfigurationError(
                "configuration file not found",
                details={"path": str(resolved)},
            )
        _CONFIG_FILE_HOLDER["path"] = resolved
    else:
        _CONFIG_FILE_HOLDER["path"] = _default_config_path()

    try:
        return Settings()
    except Exception as exc:
        raise ConfigurationError(
            "failed to load configuration", details={"error": str(exc)}
        ) from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached :class:`Settings` instance."""
    return load_settings()


def reset_settings_cache() -> None:
    """Clear the cached settings (used by tests and the CLI ``--config`` flag)."""
    get_settings.cache_clear()
