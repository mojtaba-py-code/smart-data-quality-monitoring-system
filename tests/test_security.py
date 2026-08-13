"""Tests for the security helpers - the system's trust boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from dqms.core.exceptions import FileAccessError, FileTooLargeError, SecurityError
from dqms.utils.security import (
    neutralise_formula_injection,
    safe_resolve_path,
    sanitize_filename,
)


def test_resolve_valid_file(tmp_path: Path) -> None:
    target = tmp_path / "data.csv"
    target.write_text("a,b\n1,2\n", encoding="utf-8")
    resolved = safe_resolve_path(target, allowed_extensions=[".csv"])
    assert resolved == target.resolve()


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileAccessError):
        safe_resolve_path(tmp_path / "nope.csv", allowed_extensions=[".csv"])


def test_disallowed_extension(tmp_path: Path) -> None:
    target = tmp_path / "data.exe"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(SecurityError):
        safe_resolve_path(target, allowed_extensions=[".csv"])


def test_size_limit(tmp_path: Path) -> None:
    target = tmp_path / "big.csv"
    target.write_bytes(b"0" * 2048)
    with pytest.raises(FileTooLargeError):
        safe_resolve_path(target, allowed_extensions=[".csv"], max_size_bytes=1024)


def test_base_dir_containment(tmp_path: Path) -> None:
    base = tmp_path / "allowed"
    base.mkdir()
    outside = tmp_path / "secret.csv"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(SecurityError):
        safe_resolve_path(outside, allowed_extensions=[".csv"], base_dir=base)


def test_traversal_blocked(tmp_path: Path) -> None:
    base = tmp_path / "allowed"
    base.mkdir()
    (tmp_path / "secret.csv").write_text("x", encoding="utf-8")
    sneaky = base / ".." / "secret.csv"
    with pytest.raises(SecurityError):
        safe_resolve_path(sneaky, allowed_extensions=[".csv"], base_dir=base)


@pytest.mark.parametrize(
    ("value", "expected_prefix"),
    [("=SUM(A1)", "'"), ("+1", "'"), ("-1", "'"), ("@cmd", "'"), ("safe", "s")],
)
def test_formula_injection_neutralised(value: str, expected_prefix: str) -> None:
    assert str(neutralise_formula_injection(value)).startswith(expected_prefix)


def test_formula_injection_ignores_non_strings() -> None:
    assert neutralise_formula_injection(42) == 42
    assert neutralise_formula_injection(None) is None


def test_sanitize_filename() -> None:
    assert sanitize_filename("../../etc/passwd") == "etc_passwd"
    assert sanitize_filename("") == "export"
    assert "/" not in sanitize_filename("a/b\\c")


# -- attack regressions ----------------------------------------------------
#
# Each test below corresponds to a bypass that was demonstrated against an
# earlier revision of this module.


def test_alternate_data_stream_path_rejected(tmp_path: Path) -> None:
    """`payload.exe:hidden.csv` presents a .csv suffix but reads a stream on an exe."""
    payload = tmp_path / "payload.exe"
    payload.write_bytes(b"MZ")
    assert Path(f"{payload}:hidden.csv").suffix == ".csv"  # what a naive check sees
    with pytest.raises(SecurityError, match="alternate data stream"):
        safe_resolve_path(f"{payload}:hidden.csv", allowed_extensions=[".csv"])


def test_default_data_stream_suffix_rejected(tmp_path: Path) -> None:
    target = tmp_path / "data.csv"
    target.write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(SecurityError):
        safe_resolve_path(f"{target}::$DATA", allowed_extensions=[".csv"])


def test_null_byte_in_path_rejected(tmp_path: Path) -> None:
    """A null byte must raise a domain error, not a raw ValueError from os.stat."""
    with pytest.raises(SecurityError, match="null byte"):
        safe_resolve_path(f"{tmp_path}/evil\x00.csv", allowed_extensions=[".csv"])


def test_drive_letter_is_not_mistaken_for_a_stream(tmp_path: Path) -> None:
    """The colon in a Windows drive anchor must stay legal."""
    target = tmp_path / "fine.csv"
    target.write_text("a\n1\n", encoding="utf-8")
    assert safe_resolve_path(target.absolute(), allowed_extensions=[".csv"]) == target.resolve()


@pytest.mark.parametrize("trigger", ["=", "+", "-", "@", "\t", "\r"])
def test_every_declared_formula_trigger_is_neutralised(trigger: str) -> None:
    assert str(neutralise_formula_injection(f"{trigger}cmd|calc")).startswith("'")
