"""Tests that the convenience requirements file agrees with the package metadata.

`requirements.txt` is a copy of `[project.dependencies]` maintained by hand, and a
copy that drifts is worse than no copy at all: someone following the documented
`pip install -r requirements.txt` path would get a different environment from
someone running `pip install .`. In particular the dashboard stack belongs to the
`dashboard` extra, so it must not reappear in the base requirements file.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_NAME_TERMINATORS = "<>=!~;[ #"


def _distribution_name(requirement: str) -> str:
    """Reduce a requirement specifier to its normalised distribution name."""
    name = requirement
    for terminator in _NAME_TERMINATORS:
        name = name.split(terminator, 1)[0]
    return name.strip().lower().replace("_", "-")


def _requirements_file_names(path: Path) -> set[str]:
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-")):
            continue
        names.add(_distribution_name(stripped))
    return names


def _declared_dependency_names() -> set[str]:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    return {_distribution_name(item) for item in pyproject["project"]["dependencies"]}


def _extra_names(extra: str) -> set[str]:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    optional = pyproject["project"]["optional-dependencies"]
    return {_distribution_name(item) for item in optional[extra]}


def test_requirements_file_mirrors_declared_dependencies() -> None:
    assert _requirements_file_names(PROJECT_ROOT / "requirements.txt") == (
        _declared_dependency_names()
    )


def test_dashboard_stack_stays_out_of_the_base_requirements() -> None:
    base = _requirements_file_names(PROJECT_ROOT / "requirements.txt")
    dashboard = _extra_names("dashboard")
    assert dashboard
    assert not (base & dashboard)
