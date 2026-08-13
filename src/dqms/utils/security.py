"""Security helpers used at every trust boundary of the system.

These functions are deliberately conservative: the loader and exporters call
them before touching the filesystem so that a hostile file name or path can
never escape the intended directory, exhaust memory, or smuggle a spreadsheet
formula into an exported report.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from dqms.core.constants import FORMULA_INJECTION_PREFIXES
from dqms.core.exceptions import FileAccessError, FileTooLargeError, SecurityError

# Characters that are unsafe in a file name on the major operating systems.
_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_UNDERSCORE = re.compile(r"_{2,}")


def safe_resolve_path(
    candidate: str | Path,
    *,
    allowed_extensions: set[str] | list[str] | None = None,
    base_dir: Path | None = None,
    allow_symlinks: bool = False,
    max_size_bytes: int | None = None,
    must_exist: bool = True,
) -> Path:
    """Resolve and validate a filesystem path before it is read.

    The function guards against the most common file-handling vulnerabilities:

    * **Path traversal** - the path is fully resolved and, when ``base_dir`` is
      supplied, must stay inside it.
    * **Symlink escape** - symlinked files are rejected unless explicitly
      allowed, preventing a link from redirecting reads outside ``base_dir``.
    * **Unexpected file types** - only ``allowed_extensions`` are accepted.
    * **Resource exhaustion** - files larger than ``max_size_bytes`` are refused
      before any bytes are read into memory.

    Parameters
    ----------
    candidate:
        The user-supplied path.
    allowed_extensions:
        Iterable of lower-case extensions (including the dot) that may be read.
    base_dir:
        Optional directory the resolved path must stay within.
    allow_symlinks:
        Whether symlinked targets are permitted.
    max_size_bytes:
        Optional hard cap on the file size.
    must_exist:
        When ``True`` (the default) the path must point at an existing file.

    Returns
    -------
    pathlib.Path
        The fully resolved, validated path.
    """
    text = str(candidate)
    if "\x00" in text:
        raise SecurityError(
            "path contains a null byte", details={"path": text.replace("\x00", "\\x00")}
        )

    raw = Path(text).expanduser()
    _reject_alternate_data_stream(raw)

    if not allow_symlinks and raw.is_symlink():
        raise SecurityError(
            "refusing to read a symlinked file", details={"path": str(raw)}
        )

    resolved = raw.resolve()

    if base_dir is not None:
        base_resolved = Path(base_dir).expanduser().resolve()
        if not _is_relative_to(resolved, base_resolved):
            raise SecurityError(
                "path escapes the permitted base directory",
                details={"path": str(resolved), "base_dir": str(base_resolved)},
            )

    if must_exist:
        if not resolved.exists():
            raise FileAccessError("file does not exist", details={"path": str(resolved)})
        if not resolved.is_file():
            raise FileAccessError("path is not a regular file", details={"path": str(resolved)})

    if allowed_extensions is not None:
        allowed = {ext.lower() for ext in allowed_extensions}
        if resolved.suffix.lower() not in allowed:
            raise SecurityError(
                "file extension is not allowed",
                details={"path": str(resolved), "suffix": resolved.suffix},
            )

    if max_size_bytes is not None and resolved.is_file():
        size = resolved.stat().st_size
        if size > max_size_bytes:
            raise FileTooLargeError(
                "file exceeds the maximum permitted size",
                details={"path": str(resolved), "size_bytes": size, "limit_bytes": max_size_bytes},
            )

    return resolved


def _reject_alternate_data_stream(path: Path) -> None:
    """Refuse NTFS alternate-data-stream syntax such as ``file.exe:hidden.csv``.

    On NTFS a colon attaches a named stream to a file. The syntax defeats an
    extension allow-list, because ``Path("payload.exe:hidden.csv").suffix`` is
    ``".csv"`` while the bytes actually read belong to a stream on an executable.
    A legitimate path only ever carries a colon in its drive anchor (``C:\\``),
    so a colon anywhere else is rejected outright.
    """
    for part in path.parts:
        # Skip the anchor, which legitimately contains the drive colon.
        if part == path.anchor or (len(part) == 2 and part.endswith(":")):
            continue
        if ":" in part:
            raise SecurityError(
                "path contains an alternate data stream or a stray colon",
                details={"path": str(path), "component": part},
            )


def _is_relative_to(path: Path, base: Path) -> bool:
    """Backport-friendly ``Path.is_relative_to`` check."""
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def sanitize_filename(name: str, *, default: str = "export", max_length: int = 120) -> str:
    """Return a safe, portable file name derived from ``name``.

    Unicode is normalised, unsafe characters are stripped, and the result is
    truncated. This prevents a column value or dataset name from injecting path
    separators or control characters into an output file name.
    """
    normalised = unicodedata.normalize("NFKD", name)
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", normalised).strip(" ._")
    cleaned = _MULTI_UNDERSCORE.sub("_", cleaned)
    if not cleaned:
        cleaned = default
    return cleaned[:max_length]


def neutralise_formula_injection(value: object) -> object:
    """Neutralise spreadsheet formula injection in a single cell value.

    Strings beginning with a formula trigger (``=``, ``+``, ``-``, ``@`` ...)
    are prefixed with a single quote so spreadsheet software treats them as
    text. Non-string values are returned unchanged.
    """
    if isinstance(value, str) and value[:1] in FORMULA_INJECTION_PREFIXES:
        return "'" + value
    return value
