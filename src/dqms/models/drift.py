"""Schema-drift and data-drift result models."""

from __future__ import annotations

from pydantic import Field

from dqms.models.base import ResultModel


class SchemaFieldChange(ResultModel):
    """A single schema-level difference between two datasets."""

    column: str
    change_type: str = Field(description="added | removed | dtype_changed")
    baseline_dtype: str | None = None
    current_dtype: str | None = None


class SchemaDriftReport(ResultModel):
    """Structural comparison between a baseline and a current dataset."""

    added_columns: list[str] = Field(default_factory=list)
    removed_columns: list[str] = Field(default_factory=list)
    dtype_changes: list[SchemaFieldChange] = Field(default_factory=list)
    stable_columns: list[str] = Field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        """Whether any structural change was detected."""
        return bool(self.added_columns or self.removed_columns or self.dtype_changes)

    @property
    def change_count(self) -> int:
        """Total number of structural changes."""
        return len(self.added_columns) + len(self.removed_columns) + len(self.dtype_changes)


class ColumnDrift(ResultModel):
    """Distribution comparison for a single shared column."""

    column: str
    is_numeric: bool
    psi: float | None = Field(default=None, description="Population Stability Index")
    ks_statistic: float | None = None
    ks_pvalue: float | None = None
    mean_change: float | None = None
    median_change: float | None = None
    variance_change: float | None = None
    drift_detected: bool = False
    severity: str = Field(default="none", description="none | warning | critical")


class DataDriftReport(ResultModel):
    """Statistical comparison between historical and current distributions."""

    baseline_rows: int = Field(ge=0)
    current_rows: int = Field(ge=0)
    columns: list[ColumnDrift] = Field(default_factory=list)
    correlation_changes: dict[str, float] = Field(
        default_factory=dict,
        description="Absolute change in pairwise correlation, keyed 'a|b'",
    )

    @property
    def drifted_columns(self) -> list[str]:
        """Names of columns where drift was detected."""
        return [col.column for col in self.columns if col.drift_detected]

    @property
    def has_drift(self) -> bool:
        """Whether any column drifted."""
        return bool(self.drifted_columns)
