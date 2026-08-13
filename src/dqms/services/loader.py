"""File loading engine.

The loader is the system's primary trust boundary: every byte that enters the
pipeline passes through here. It therefore combines convenience (automatic
format and encoding detection, chunked reading for large files) with strict
security checks (path-traversal protection, size limits, extension allow-list).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from dqms.config.settings import Settings, get_settings
from dqms.core.constants import EXTENSION_TO_FORMAT, FileFormat
from dqms.core.exceptions import FileAccessError, UnsupportedFormatError
from dqms.utils.logging import get_logger
from dqms.utils.security import safe_resolve_path
from dqms.utils.timing import Stopwatch

_logger = get_logger("dqms.loader")

# Number of bytes sampled when sniffing text encoding.
_ENCODING_SAMPLE_BYTES = 65536


class FileLoader:
    """Load supported dataset files into pandas DataFrames.

    Parameters
    ----------
    settings:
        Application settings. Defaults to the cached global settings.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def detect_format(self, path: Path) -> FileFormat:
        """Resolve a :class:`FileFormat` from a file's extension.

        Raises
        ------
        UnsupportedFormatError
            If the extension is not associated with any supported format.
        """
        fmt = EXTENSION_TO_FORMAT.get(path.suffix.lower())
        if fmt is None:
            raise UnsupportedFormatError(
                "unsupported file extension",
                details={"path": str(path), "suffix": path.suffix},
            )
        return fmt

    def load(self, path: str | Path, **options: Any) -> pd.DataFrame:
        """Load a dataset file and return it as a DataFrame.

        The path is validated against the security policy (size, extension,
        symlink, optional base-directory containment) before any data is read.

        Parameters
        ----------
        path:
            Location of the dataset file.
        options:
            Extra keyword arguments forwarded to the underlying pandas reader.

        Returns
        -------
        pandas.DataFrame
            The loaded dataset.
        """
        security = self._settings.security
        base_dir = (
            self._settings.paths.input_dir if security.restrict_to_input_dir else None
        )
        resolved = safe_resolve_path(
            path,
            allowed_extensions=security.allowed_extensions,
            base_dir=base_dir,
            allow_symlinks=security.allow_symlinks,
            max_size_bytes=security.max_file_size_bytes,
            must_exist=True,
        )

        if resolved.stat().st_size == 0:
            raise FileAccessError("file is empty", details={"path": str(resolved)})

        fmt = self.detect_format(resolved)
        _logger.info("Loading {} as {}", resolved.name, fmt.value)

        with Stopwatch(f"load[{resolved.name}]"):
            frame = self._dispatch(resolved, fmt, options)

        frame = self._apply_row_sampling(frame)
        _logger.success(
            "Loaded {} rows x {} columns from {}",
            len(frame),
            frame.shape[1],
            resolved.name,
        )
        return frame

    # -- format dispatch ---------------------------------------------------

    def _dispatch(
        self, path: Path, fmt: FileFormat, options: dict[str, Any]
    ) -> pd.DataFrame:
        """Route to the reader responsible for ``fmt``."""
        readers = {
            FileFormat.CSV: self._read_csv,
            FileFormat.EXCEL: self._read_excel,
            FileFormat.JSON: self._read_json,
            FileFormat.PARQUET: self._read_parquet,
        }
        try:
            return readers[fmt](path, options)
        except (UnsupportedFormatError, FileAccessError):
            raise
        except Exception as exc:
            raise FileAccessError(
                "failed to read file",
                details={"path": str(path), "format": fmt.value, "error": str(exc)},
            ) from exc

    def _read_csv(self, path: Path, options: dict[str, Any]) -> pd.DataFrame:
        """Read a CSV/TSV file, detecting encoding and streaming large files."""
        loader_cfg = self._settings.loader
        encoding = loader_cfg.encoding or self._detect_encoding(path)
        delimiter = loader_cfg.csv_delimiter

        read_kwargs: dict[str, Any] = {
            "encoding": encoding,
            "on_bad_lines": "warn",
            **options,
        }
        if delimiter:
            read_kwargs["sep"] = delimiter
        else:
            # Let pandas sniff the delimiter with the python engine.
            read_kwargs.setdefault("sep", None)
            read_kwargs.setdefault("engine", "python")

        size = path.stat().st_size
        if size >= loader_cfg.large_file_threshold_bytes and loader_cfg.sample_rows is None:
            _logger.info(
                "Large file detected ({:.1f} MB); reading in chunks of {}",
                size / (1024 * 1024),
                loader_cfg.chunk_size,
            )
            # chunksize is incompatible with the sniffing python engine, so pin
            # a delimiter for the streamed path.
            read_kwargs.setdefault("sep", delimiter or ",")
            read_kwargs["engine"] = "c"
            read_kwargs.pop("on_bad_lines", None)
            chunks = pd.read_csv(path, chunksize=loader_cfg.chunk_size, **read_kwargs)
            return pd.concat(chunks, ignore_index=True)

        # pandas reader overloads cannot be resolved against dynamic **kwargs.
        frame: pd.DataFrame = pd.read_csv(path, **read_kwargs)  # type: ignore[call-overload]
        return frame

    def _read_excel(self, path: Path, options: dict[str, Any]) -> pd.DataFrame:
        """Read the first sheet of an Excel workbook.

        The engine is chosen from the extension: openpyxl handles the modern
        zip-based formats but cannot read the legacy BIFF ``.xls`` container, so
        that one is delegated to pandas (which uses ``xlrd``). When ``xlrd`` is
        absent the failure is translated into an actionable error rather than a
        bare ImportError from deep inside pandas.
        """
        if path.suffix.lower() == ".xls":
            try:
                import xlrd  # noqa: F401
            except ImportError as exc:
                raise UnsupportedFormatError(
                    "reading legacy .xls workbooks requires the optional 'xlrd' package; "
                    "install it with `pip install xlrd` or convert the file to .xlsx",
                    details={"path": str(path)},
                ) from exc
        else:
            options.setdefault("engine", "openpyxl")
        frame: pd.DataFrame = pd.read_excel(path, **options)  # type: ignore[call-overload]
        return frame

    def _read_json(self, path: Path, options: dict[str, Any]) -> pd.DataFrame:
        """Read a JSON file, tolerating both records and line-delimited JSON."""
        try:
            frame: pd.DataFrame = pd.read_json(path, **options)  # type: ignore[call-overload]
        except ValueError:
            # Fall back to newline-delimited JSON.
            frame = pd.read_json(path, lines=True, **options)  # type: ignore[call-overload]
        return frame

    def _read_parquet(self, path: Path, options: dict[str, Any]) -> pd.DataFrame:
        """Read a Parquet file via pyarrow."""
        options.setdefault("engine", "pyarrow")
        frame: pd.DataFrame = pd.read_parquet(path, **options)
        return frame

    # -- helpers -----------------------------------------------------------

    def _detect_encoding(self, path: Path) -> str:
        """Best-effort text-encoding detection using chardet.

        Only a sample of the file is inspected to keep detection fast on large
        files. Falls back to UTF-8 when confidence is low.
        """
        try:
            import chardet

            with path.open("rb") as handle:
                sample = handle.read(_ENCODING_SAMPLE_BYTES)
            guess = chardet.detect(sample)
            encoding = guess.get("encoding")
            confidence = guess.get("confidence") or 0.0
            if encoding and confidence >= 0.5:
                _logger.debug("Detected encoding {} ({:.0%})", encoding, confidence)
                return str(encoding)
        except Exception as exc:
            _logger.debug("Encoding detection failed ({}); defaulting to utf-8", exc)
        return "utf-8"

    def _apply_row_sampling(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Optionally cap the number of rows, per the loader configuration."""
        sample_rows = self._settings.loader.sample_rows
        if sample_rows is not None and len(frame) > sample_rows:
            _logger.info("Sampling first {} of {} rows", sample_rows, len(frame))
            return frame.head(sample_rows).reset_index(drop=True)
        return frame
