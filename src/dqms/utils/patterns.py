"""Compiled regular expressions and predicate helpers for validation.

Keeping the patterns in one module means the validation service and the cleaner
share a single, tested definition of "what a valid email looks like" rather than
duplicating slightly different regexes.
"""

from __future__ import annotations

import re

# Pragmatic email pattern: not full RFC 5322 (which is impractical), but
# rejects the overwhelming majority of malformed addresses seen in real data.
EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
)

# E.164-friendly phone pattern allowing an optional leading '+' and 7-15 digits
# once separators (spaces, dashes, dots, parentheses) are removed.
_PHONE_CLEANER = re.compile(r"[\s().\-]")
_PHONE_PATTERN = re.compile(r"^\+?\d{7,15}$")

# Column names that strongly suggest an identifier column (used by profiling
# and uniqueness scoring to reason about expected uniqueness).
ID_COLUMN_PATTERN = re.compile(r"(^id$|_id$|^id_|uuid|guid)", re.IGNORECASE)


def is_valid_email(value: str) -> bool:
    """Return ``True`` if ``value`` looks like a syntactically valid email."""
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate or len(candidate) > 254:
        return False
    return EMAIL_PATTERN.match(candidate) is not None


def is_valid_phone(value: str) -> bool:
    """Return ``True`` if ``value`` looks like a valid phone number.

    Separators are stripped first, so ``"+1 (555) 123-4567"`` is accepted.
    """
    if not isinstance(value, str):
        return False
    candidate = _PHONE_CLEANER.sub("", value.strip())
    return bool(candidate) and _PHONE_PATTERN.match(candidate) is not None


def looks_like_identifier(column_name: str) -> bool:
    """Return ``True`` if the column name suggests a unique identifier."""
    return ID_COLUMN_PATTERN.search(column_name) is not None


def column_matches_hint(column_name: str, hints: list[str]) -> bool:
    """Return ``True`` if ``column_name`` contains any of the given hints.

    Matching is case-insensitive and substring based, so a hint of ``"email"``
    matches ``"customer_email"`` and ``"Email_Address"``.
    """
    lowered = column_name.lower()
    return any(hint.lower() in lowered for hint in hints)
