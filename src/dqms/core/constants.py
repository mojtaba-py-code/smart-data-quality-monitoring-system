"""Project-wide constants and enumerations.

Centralising these avoids "magic strings" scattered across modules and gives a
single place to extend supported formats, quality dimensions, or severities.
"""

from __future__ import annotations

from enum import StrEnum


class FileFormat(StrEnum):
    """Supported input/output file formats."""

    CSV = "csv"
    EXCEL = "excel"
    JSON = "json"
    PARQUET = "parquet"


class Severity(StrEnum):
    """Severity levels for validation issues, ordered low to high."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class QualityDimension(StrEnum):
    """The dimensions that make up the overall data quality score."""

    COMPLETENESS = "completeness"
    CONSISTENCY = "consistency"
    VALIDITY = "validity"
    UNIQUENESS = "uniqueness"
    ACCURACY = "accuracy"


class AnomalyMethod(StrEnum):
    """Supported anomaly-detection strategies."""

    ZSCORE = "zscore"
    IQR = "iqr"
    ISOLATION_FOREST = "isolation_forest"


# Mapping of canonical formats to the file extensions that resolve to them.
EXTENSION_TO_FORMAT: dict[str, FileFormat] = {
    ".csv": FileFormat.CSV,
    ".tsv": FileFormat.CSV,
    ".txt": FileFormat.CSV,
    ".xlsx": FileFormat.EXCEL,
    ".xlsm": FileFormat.EXCEL,
    ".xls": FileFormat.EXCEL,
    ".json": FileFormat.JSON,
    ".parquet": FileFormat.PARQUET,
    ".pq": FileFormat.PARQUET,
}

# Characters that trigger formula execution in spreadsheet software. Cells that
# begin with one of these are neutralised on export to prevent CSV injection.
FORMULA_INJECTION_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")

# Default weighting used when combining quality dimensions into one score.
DEFAULT_DIMENSION_WEIGHTS: dict[QualityDimension, float] = {
    QualityDimension.COMPLETENESS: 0.25,
    QualityDimension.VALIDITY: 0.25,
    QualityDimension.UNIQUENESS: 0.20,
    QualityDimension.CONSISTENCY: 0.15,
    QualityDimension.ACCURACY: 0.15,
}
