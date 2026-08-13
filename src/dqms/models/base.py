"""Shared base class for every analysis result model.

Results describe what *was* observed in a dataset, so they are values rather
than state: once a service has returned one, nobody downstream should be able to
edit a score, a severity, or an affected-row count in place. Freezing the models
makes that guarantee enforceable instead of merely conventional, and turns an
accidental mutation into an immediate, well-located error.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ResultModel(BaseModel):
    """Immutable, validated base for analysis result objects."""

    model_config = ConfigDict(frozen=True)
