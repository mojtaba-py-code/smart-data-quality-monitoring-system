"""Visualization service.

Produces the standard set of data-quality charts as PNG files using Matplotlib's
non-interactive *Agg* backend, so it works on headless servers and inside the
report generators. The backend is selected before ``pyplot`` is imported to
avoid pulling in a GUI toolkit.
"""

from __future__ import annotations

import base64
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from dqms.models.quality import QualityScore
from dqms.utils.logging import get_logger
from dqms.utils.security import sanitize_filename

_logger = get_logger("dqms.visualizer")

# Cap the number of columns charted so a very wide dataset does not generate
# hundreds of images.
_MAX_NUMERIC_CHARTS = 12
_FIG_DPI = 110


class ChartFactory:
    """Create and persist the standard data-quality charts."""

    def __init__(self, output_dir: str | Path) -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def generate_all(self, frame: pd.DataFrame, quality: QualityScore) -> dict[str, Path]:
        """Generate every applicable chart and return a name -> path mapping."""
        charts: dict[str, Path] = {}
        numeric = frame.select_dtypes(include=[np.number])

        quality_chart = self.quality_dimensions(quality)
        if quality_chart is not None:
            charts["quality_dimensions"] = quality_chart

        missing = self.missing_matrix(frame)
        if missing is not None:
            charts["missing_matrix"] = missing

        if not numeric.empty:
            hist = self.histogram_grid(numeric)
            if hist is not None:
                charts["histograms"] = hist
            box = self.box_plot(numeric)
            if box is not None:
                charts["box_plot"] = box
        if numeric.shape[1] >= 2:
            heatmap = self.correlation_heatmap(numeric)
            if heatmap is not None:
                charts["correlation_heatmap"] = heatmap

        _logger.info("Generated {} chart(s) in {}", len(charts), self._output_dir)
        return charts

    # -- individual charts -------------------------------------------------

    def quality_dimensions(self, quality: QualityScore) -> Path | None:
        """Horizontal bar chart of the per-dimension quality scores."""
        if not quality.dimensions:
            return None
        labels = [d.dimension.value.title() for d in quality.dimensions]
        scores = [d.score for d in quality.dimensions]
        colors = ["#2e7d32" if s >= 80 else "#f9a825" if s >= 60 else "#c62828" for s in scores]

        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.barh(labels, scores, color=colors)
        ax.set_xlim(0, 100)
        ax.set_xlabel("Score (%)")
        ax.set_title("Quality dimensions")
        for index, score in enumerate(scores):
            ax.text(min(score + 1, 96), index, f"{score:.1f}", va="center", fontsize=9)
        return self._save(fig, "quality_dimensions")

    def histogram_grid(self, numeric: pd.DataFrame) -> Path | None:
        """Grid of histograms for the numeric columns."""
        columns = list(numeric.columns)[:_MAX_NUMERIC_CHARTS]
        if not columns:
            return None
        cols = min(3, len(columns))
        rows = int(np.ceil(len(columns) / cols))
        fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 3 * rows), squeeze=False)
        for index, column in enumerate(columns):
            ax = axes[index // cols][index % cols]
            data = numeric[column].dropna()
            ax.hist(data, bins=min(30, max(5, int(np.sqrt(len(data) or 1)))), color="#1565c0")
            ax.set_title(str(column), fontsize=10)
        for index in range(len(columns), rows * cols):
            axes[index // cols][index % cols].axis("off")
        fig.suptitle("Distributions")
        fig.tight_layout()
        return self._save(fig, "histograms")

    def box_plot(self, numeric: pd.DataFrame) -> Path | None:
        """Box plot of numeric columns (standardised for comparability)."""
        columns = list(numeric.columns)[:_MAX_NUMERIC_CHARTS]
        if not columns:
            return None
        standardised = []
        labels = []
        for column in columns:
            series = numeric[column].dropna()
            std = series.std(ddof=0)
            if std and std > 0:
                standardised.append(((series - series.mean()) / std).to_numpy())
                labels.append(str(column))
        if not standardised:
            return None
        fig, ax = plt.subplots(figsize=(1.2 * len(labels) + 3, 5))
        ax.boxplot(standardised, tick_labels=labels, vert=True)
        ax.set_title("Standardised box plots (outlier view)")
        ax.set_ylabel("z-score")
        plt.setp(ax.get_xticklabels(), rotation=40, ha="right")
        fig.tight_layout()
        return self._save(fig, "box_plot")

    def correlation_heatmap(self, numeric: pd.DataFrame) -> Path | None:
        """Correlation heatmap for the numeric columns."""
        corr = numeric.corr(numeric_only=True)
        if corr.empty:
            return None
        fig, ax = plt.subplots(figsize=(0.6 * len(corr) + 3, 0.6 * len(corr) + 3))
        image = ax.imshow(corr.to_numpy(), cmap="coolwarm", vmin=-1, vmax=1)
        ax.set_xticks(range(len(corr)))
        ax.set_yticks(range(len(corr)))
        ax.set_xticklabels(corr.columns, rotation=45, ha="right", fontsize=8)
        ax.set_yticklabels(corr.index, fontsize=8)
        fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
        ax.set_title("Correlation heatmap")
        fig.tight_layout()
        return self._save(fig, "correlation_heatmap")

    def missing_matrix(self, frame: pd.DataFrame) -> Path | None:
        """Visualise the pattern of missing values across the dataset."""
        if frame.empty:
            return None
        mask = frame.isna().to_numpy()
        if not mask.any():
            return None
        fig, ax = plt.subplots(figsize=(min(0.5 * frame.shape[1] + 3, 16), 5))
        ax.imshow(mask, aspect="auto", cmap="gray_r", interpolation="nearest")
        ax.set_xticks(range(frame.shape[1]))
        ax.set_xticklabels(frame.columns, rotation=45, ha="right", fontsize=8)
        ax.set_ylabel("Row")
        ax.set_title("Missing-value matrix (dark = missing)")
        fig.tight_layout()
        return self._save(fig, "missing_matrix")

    # -- helpers -----------------------------------------------------------

    def _save(self, fig: plt.Figure, name: str) -> Path:
        """Persist ``fig`` as a PNG and close it to free memory."""
        path = self._output_dir / f"{sanitize_filename(name)}.png"
        fig.savefig(path, dpi=_FIG_DPI, bbox_inches="tight")
        plt.close(fig)
        return path


def encode_png_base64(path: Path) -> str:
    """Return a base64 data URI for a PNG, for inline embedding in HTML."""
    data = Path(path).read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{encoded}"
