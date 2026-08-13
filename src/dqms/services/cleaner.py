"""Automatic data-cleaning service.

The cleaner applies a configurable, ordered sequence of transformations and
records every action it takes. Returning an explicit :class:`CleaningResult`
(rather than mutating in place) keeps the operation transparent and auditable -
important when cleaning feeds regulated reporting.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from dqms.config.settings import Settings, get_settings
from dqms.utils.logging import get_logger
from dqms.utils.patterns import column_matches_hint

_logger = get_logger("dqms.cleaner")

_NON_ALNUM = re.compile(r"[^0-9a-zA-Z]+")
_CURRENCY_CHARS = re.compile(r"[^\d.\-]")
_CURRENCY_CANDIDATE = re.compile(r"^\s*[-+]?[$€£¥]?\s*[\d,]+(\.\d+)?\s*$")


@dataclass
class CleaningResult:
    """Outcome of a cleaning run.

    Attributes
    ----------
    frame:
        The cleaned DataFrame (a new object; the input is never mutated).
    actions:
        Ordered, human-readable log of the transformations applied.
    rows_before / rows_after:
        Row counts before and after cleaning, useful for reporting how many
        duplicates or unfillable rows were dropped.
    """

    frame: pd.DataFrame
    actions: list[str] = field(default_factory=list)
    rows_before: int = 0
    rows_after: int = 0


class DataCleaner:
    """Apply automatic cleaning transformations to a dataset."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def clean(self, frame: pd.DataFrame) -> CleaningResult:
        """Return a cleaned copy of ``frame`` together with an action log."""
        cfg = self._settings.cleaning
        result = CleaningResult(frame=frame.copy(), rows_before=len(frame))
        _logger.info("Cleaning dataset with shape {}", frame.shape)

        # Repeated column labels must go first: every later step addresses
        # columns by name, and a repeated label would otherwise resolve to a
        # DataFrame slice instead of a Series.
        self._deduplicate_columns(result)
        if cfg.standardize_column_names:
            self._standardize_columns(result)
        if cfg.trim_whitespace:
            self._trim_whitespace(result)
        if cfg.normalize_text_case != "none":
            self._normalize_case(result, cfg.normalize_text_case)
        self._normalize_currencies(result)
        self._convert_types(result)
        self._normalize_dates(result)
        self._handle_missing(result)
        if cfg.drop_duplicate_rows:
            self._drop_duplicates(result)

        result.rows_after = len(result.frame)
        _logger.success(
            "Cleaning complete: {} actions, {} -> {} rows",
            len(result.actions),
            result.rows_before,
            result.rows_after,
        )
        return result

    # -- transformations ---------------------------------------------------

    def _deduplicate_columns(self, result: CleaningResult) -> None:
        """Make repeated column labels unique by suffixing ``_1``, ``_2``, ..."""
        labels = [str(label) for label in result.frame.columns]
        if len(set(labels)) == len(labels):
            return
        seen: dict[str, int] = {}
        unique: list[str] = []
        for label in labels:
            if label in seen:
                seen[label] += 1
                candidate = f"{label}_{seen[label]}"
                while candidate in seen:
                    seen[label] += 1
                    candidate = f"{label}_{seen[label]}"
                seen[candidate] = 0
                unique.append(candidate)
            else:
                seen[label] = 0
                unique.append(label)
        result.frame.columns = pd.Index(unique)
        result.actions.append(
            f"Made {len(labels) - len(set(labels))} duplicate column label(s) unique"
        )

    def _standardize_columns(self, result: CleaningResult) -> None:
        """Rename columns to unique, ascii, snake_case identifiers."""
        seen: dict[str, int] = {}
        renamed: dict[str, str] = {}
        for original in result.frame.columns:
            clean = self._to_snake_case(str(original))
            if clean in seen:
                seen[clean] += 1
                clean = f"{clean}_{seen[clean]}"
            else:
                seen[clean] = 0
            renamed[original] = clean
        if any(k != v for k, v in renamed.items()):
            result.frame = result.frame.rename(columns=renamed)
            result.actions.append("Standardised column names to snake_case")

    def _trim_whitespace(self, result: CleaningResult) -> None:
        """Strip and optionally collapse whitespace in text columns."""
        cfg = self._settings.cleaning
        touched: list[str] = []
        for column in result.frame.select_dtypes(include=["object", "string"]).columns:
            series = result.frame[column]
            stripped = series.apply(lambda v: v.strip() if isinstance(v, str) else v)
            if cfg.collapse_internal_whitespace:
                stripped = stripped.apply(
                    lambda v: re.sub(r"\s+", " ", v) if isinstance(v, str) else v
                )
            if not stripped.equals(series):
                result.frame[column] = stripped
                touched.append(column)
        if touched:
            result.actions.append(f"Trimmed whitespace in {len(touched)} text column(s)")

    def _normalize_case(self, result: CleaningResult, mode: str) -> None:
        """Normalise the case of text columns."""
        transform = {"lower": str.lower, "upper": str.upper, "title": str.title}[mode]
        for column in result.frame.select_dtypes(include=["object", "string"]).columns:
            result.frame[column] = result.frame[column].apply(
                lambda v: transform(v) if isinstance(v, str) else v
            )
        result.actions.append(f"Normalised text case to {mode}")

    def _normalize_currencies(self, result: CleaningResult) -> None:
        """Convert currency-formatted text columns into floats."""
        converted: list[str] = []
        for column in result.frame.select_dtypes(include=["object", "string"]).columns:
            series = result.frame[column].dropna().astype(str)
            if series.empty:
                continue
            looks_currency = series.str.match(_CURRENCY_CANDIDATE).mean()
            has_symbol = series.str.contains(r"[$€£¥,]").mean()
            if looks_currency >= 0.9 and has_symbol > 0:
                cleaned = (
                    result.frame[column]
                    .astype(str)
                    .str.replace(_CURRENCY_CHARS, "", regex=True)
                    .replace("", np.nan)
                )
                numeric = pd.to_numeric(cleaned, errors="coerce")
                result.frame[column] = numeric
                converted.append(column)
        if converted:
            result.actions.append(f"Normalised currency columns: {', '.join(converted)}")

    def _convert_types(self, result: CleaningResult) -> None:
        """Downcast object columns that are entirely numeric to numbers."""
        converted: list[str] = []
        for column in result.frame.select_dtypes(include=["object", "string"]).columns:
            series = result.frame[column]
            non_null = series.dropna()
            if non_null.empty:
                continue
            numeric = pd.to_numeric(non_null, errors="coerce")
            if numeric.notna().all():
                result.frame[column] = pd.to_numeric(series, errors="coerce")
                converted.append(column)
        if converted:
            result.actions.append(f"Converted {len(converted)} column(s) to numeric")

    def _normalize_dates(self, result: CleaningResult) -> None:
        """Parse date-hinted text columns into proper datetimes."""
        hints = self._settings.validation.date_column_hints
        converted: list[str] = []
        for column in result.frame.columns:
            series = result.frame[column]
            if pd.api.types.is_datetime64_any_dtype(series):
                continue
            if not (
                pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)
            ):
                continue
            if not column_matches_hint(str(column), hints):
                continue
            parsed = pd.to_datetime(series, errors="coerce", format="mixed")
            # Only accept the conversion if it does not destroy data.
            if parsed.notna().sum() >= series.notna().sum() * 0.9:
                result.frame[column] = parsed
                converted.append(str(column))
        if converted:
            result.actions.append(f"Normalised date columns: {', '.join(converted)}")

    def _handle_missing(self, result: CleaningResult) -> None:
        """Impute or drop missing values per the configured strategy."""
        cfg = self._settings.cleaning
        numeric_strategy = cfg.missing_numeric_strategy
        categorical_strategy = cfg.missing_categorical_strategy

        for column in result.frame.columns:
            series = result.frame[column]
            if series.isna().sum() == 0:
                continue
            if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
                self._impute_numeric(result, column, numeric_strategy)
            else:
                self._impute_categorical(result, column, categorical_strategy)

    def _impute_numeric(self, result: CleaningResult, column: str, strategy: str) -> None:
        """Impute missing numeric values."""
        series = result.frame[column]
        if strategy == "mean":
            result.frame[column] = series.fillna(series.mean())
        elif strategy == "median":
            result.frame[column] = series.fillna(series.median())
        elif strategy == "zero":
            result.frame[column] = series.fillna(0)
        elif strategy == "drop":
            result.frame = result.frame.dropna(subset=[column])
        else:  # "none"
            return
        result.actions.append(f"Handled missing values in numeric column '{column}' ({strategy})")

    def _impute_categorical(self, result: CleaningResult, column: str, strategy: str) -> None:
        """Impute missing categorical values."""
        series = result.frame[column]
        if strategy == "mode":
            mode = series.mode(dropna=True)
            if not mode.empty:
                result.frame[column] = series.fillna(mode.iloc[0])
        elif strategy == "constant":
            result.frame[column] = series.fillna(self._settings.cleaning.missing_fill_constant)
        elif strategy == "drop":
            result.frame = result.frame.dropna(subset=[column])
        else:  # "none"
            return
        result.actions.append(
            f"Handled missing values in categorical column '{column}' ({strategy})"
        )

    def _drop_duplicates(self, result: CleaningResult) -> None:
        """Remove fully duplicated rows."""
        before = len(result.frame)
        result.frame = result.frame.drop_duplicates(keep="first").reset_index(drop=True)
        removed = before - len(result.frame)
        if removed:
            result.actions.append(f"Removed {removed} duplicate row(s)")

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _to_snake_case(name: str) -> str:
        """Convert an arbitrary column label to a snake_case ascii identifier."""
        normalised = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
        # Insert underscores at camelCase boundaries before lowercasing.
        spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", normalised)
        snake = _NON_ALNUM.sub("_", spaced).strip("_").lower()
        return snake or "column"
