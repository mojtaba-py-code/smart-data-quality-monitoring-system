"""Safe DataFrame export helpers.

A single entry point, :func:`export_dataframe`, writes a frame to any supported
format while applying formula-injection neutralisation for the spreadsheet-style
formats (CSV, Excel). Centralising this keeps every exporter consistent and
secure by default.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from dqms.core.constants import EXTENSION_TO_FORMAT, FileFormat
from dqms.core.exceptions import UnsupportedFormatError
from dqms.utils.logging import get_logger
from dqms.utils.security import neutralise_formula_injection

_logger = get_logger("dqms.io")

# Formats where a leading '=', '+', '-' or '@' could be executed by a
# spreadsheet application and therefore must be neutralised.
_INJECTION_SENSITIVE = {FileFormat.CSV, FileFormat.EXCEL}


def _sanitize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``frame`` with formula triggers neutralised.

    Only object/string columns are scanned; numeric and datetime columns can
    never carry a formula prefix, so they are left untouched for performance.
    """
    sanitized = frame.copy()
    object_columns = sanitized.select_dtypes(include=["object", "string"]).columns
    for column in object_columns:
        sanitized[column] = sanitized[column].map(neutralise_formula_injection)
    return sanitized


def export_dataframe(
    frame: pd.DataFrame,
    path: str | Path,
    *,
    fmt: FileFormat | None = None,
    sanitize: bool = True,
    index: bool = False,
) -> Path:
    """Write ``frame`` to ``path`` in the requested (or inferred) format.

    Parameters
    ----------
    frame:
        The DataFrame to persist.
    path:
        Destination path. Parent directories are created automatically.
    fmt:
        Explicit output format. When ``None`` it is inferred from the file
        extension.
    sanitize:
        Neutralise spreadsheet formula injection for CSV/Excel outputs.
    index:
        Whether to write the DataFrame index.

    Returns
    -------
    pathlib.Path
        The path that was written.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    resolved_format = fmt or EXTENSION_TO_FORMAT.get(destination.suffix.lower())
    if resolved_format is None:
        raise UnsupportedFormatError(
            "cannot infer export format from extension",
            details={"path": str(destination), "suffix": destination.suffix},
        )

    payload = frame
    if sanitize and resolved_format in _INJECTION_SENSITIVE:
        payload = _sanitize_frame(frame)

    if resolved_format is FileFormat.CSV:
        payload.to_csv(destination, index=index)
    elif resolved_format is FileFormat.EXCEL:
        payload.to_excel(destination, index=index, engine="openpyxl")
    elif resolved_format is FileFormat.JSON:
        payload.to_json(destination, orient="records", date_format="iso", indent=2)
    elif resolved_format is FileFormat.PARQUET:
        payload.to_parquet(destination, index=index, engine="pyarrow")
    else:  # pragma: no cover - defensive, all enum members handled above
        raise UnsupportedFormatError(
            "unsupported export format", details={"format": resolved_format.value}
        )

    _logger.debug("Exported {} rows to {}", len(payload), destination)
    return destination
