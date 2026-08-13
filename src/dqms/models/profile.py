"""Data-profiling result models."""

from __future__ import annotations

from pydantic import Field

from dqms.models.base import ResultModel


class ColumnProfile(ResultModel):
    """Descriptive statistics for a single column.

    Numeric summary fields (``minimum`` ... ``std_dev``) are ``None`` for
    non-numeric columns rather than raising, which keeps the profile uniform
    across mixed-type datasets.
    """

    name: str
    dtype: str
    count: int = Field(ge=0, description="Non-null value count")
    null_count: int = Field(ge=0)
    null_ratio: float = Field(ge=0.0, le=1.0)
    unique_count: int = Field(ge=0)
    cardinality_ratio: float = Field(
        ge=0.0, le=1.0, description="unique_count / total rows"
    )
    memory_bytes: int = Field(ge=0)
    is_numeric: bool = False

    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    median: float | None = None
    std_dev: float | None = None
    mode: str | None = Field(default=None, description="Most frequent value, as text")
    top_frequency: int | None = Field(default=None, ge=0)


class DatasetProfile(ResultModel):
    """Aggregate profile for an entire dataset."""

    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    total_memory_bytes: int = Field(ge=0)
    duplicate_row_count: int = Field(ge=0)
    duplicate_row_ratio: float = Field(ge=0.0, le=1.0)
    total_cells: int = Field(ge=0)
    missing_cells: int = Field(ge=0)
    missing_ratio: float = Field(ge=0.0, le=1.0)
    columns: list[ColumnProfile] = Field(default_factory=list)

    def column(self, name: str) -> ColumnProfile | None:
        """Return the profile for ``name`` or ``None`` if absent."""
        return next((col for col in self.columns if col.name == name), None)

    @property
    def numeric_columns(self) -> list[str]:
        """Names of the numeric columns in the dataset."""
        return [col.name for col in self.columns if col.is_numeric]
