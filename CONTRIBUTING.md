# Contributing

Thanks for taking the time. This file describes how the project is built, the gates a change has to
pass, and the conventions the history follows, so that a first contribution does not have to be
guessed at.

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

Python 3.11 or 3.12 - CI runs the suite against both, and `pyproject.toml` requires 3.11 or newer.
No system libraries are needed: PDF output uses the pure-Python `fpdf2` and charts render through
Matplotlib's headless Agg backend.

```bash
git clone https://github.com/mojtaba-py-code/smart-data-quality-monitoring-system.git
cd smart-data-quality-monitoring-system

python -m venv .venv
source .venv/bin/activate        # Windows (PowerShell): .venv\Scripts\Activate.ps1

pip install -e ".[dev]"
```

The `dev` extra pulls in the dashboard and legacy-`.xls` extras along with the whole quality
toolchain, so an editable install is enough to run every gate below. `pip install -r
requirements-dev.txt` covers nearly the same ground - it omits the package itself and the legacy
`.xls` reader - so prefer the editable install, which also registers the `dqms` console script.

Check the install:

```bash
dqms --version
dqms analyze data/samples/customers.csv
```

`data/samples/` holds the small datasets the tests and the CLI smoke test use. Please do not commit
real datasets - `data/raw/` and `data/private/` are ignored for that reason, as is `data/history.db`,
which is an operational record of what was analysed on a given machine.

## The gates

Run all four locally before opening a pull request; CI runs the same commands, and a red run is
almost always one of these.

```bash
# Tests, with the coverage floor CI enforces
pytest --cov=src/dqms --cov-report=term-missing --cov-fail-under=80

# Lint (line length 100; rule selection lives in pyproject.toml)
ruff check .

# Static types (strict enough that every function needs annotations)
mypy

# Static security analysis of the package
bandit -c pyproject.toml -r src --severity-level medium
```

`ruff check --fix` handles most lint findings, including import order. `mypy` is configured with
`disallow_untyped_defs`, so new functions - tests included, by convention here - carry type
annotations. Coverage counts the Streamlit dashboard: it is measured rather than excluded, and the
80% floor already accounts for that.

CI additionally builds the container image and verifies it runs unprivileged, audits
`requirements.txt` and `requirements-dev.txt` with `pip-audit --strict`, and greps the tree for
credential-shaped values. If you want to reproduce the image build:

```bash
docker build -t dqms:ci .
```

## Working on the code

The package follows Clean Architecture and the dependency rule is the one design constraint worth
protecting:

- `core/` - contracts, constants, exceptions. Depends on nothing else in the package.
- `models/` - immutable Pydantic result objects.
- `services/` - the use cases (loader, profiler, validator, cleaner, scorer, anomaly, drift,
  history, alerting) plus the `QualityPipeline` orchestrator.
- `cli.py`, `dashboard/`, `reports/` - outer adapters. They depend inward, never the other way.

The CLI and the dashboard both go through `QualityPipeline`, which is what keeps the two interfaces
from disagreeing about a result. New behaviour belongs in a service and is exposed through the
pipeline, not implemented twice.

Two habits matter more than style here:

- **Every file the tool reads is untrusted.** Path handling, size limits, extension checks and the
  rest live in `utils/security.py`; go through that boundary rather than around it. New output
  formats need the same treatment on the way out - see the formula-injection and filename handling
  already there, and the threat model in [SECURITY.md](SECURITY.md).
- **Configuration is Pydantic-validated and layered** (defaults, `config/config.yaml`, `DQMS_`
  environment variables, `.env`). A new option is added to the settings model with a default, and
  documented in `config/config.yaml`.

New or changed behaviour needs a test in `tests/`, named after the module it exercises. A test that
passes against the unfixed code proves nothing, so for a bug fix, write the failing test first.

## Commits and pull requests

Commit subjects use a lowercase conventional prefix and state the **effect**, not the file touched:

```
build: raise dependency floors off releases with published CVEs
ci: audit dependencies once instead of twice per run
test: assert on the parsed redacted URL instead of a substring
```

`build`, `ci`, `chore`, `docs` and `test` are in use; `feat`, `fix`, `perf` and `refactor` follow
the same convention. Keep the subject under about 72 characters, in the imperative, no full stop,
and use the body to explain why the change is needed - what the reader cannot get from the diff.
Prefer several small commits, one concern each, over a single large one.

Pull requests: branch off `main`, keep the change focused, describe what breaks without it, and add
a `CHANGELOG.md` entry under the current unreleased heading for anything user-visible. Text files
are stored with LF endings (`.gitattributes` enforces this), so no line-ending churn should appear
in the diff.

## Reporting things

- **Bugs and feature ideas:** open an issue. For a data-quality bug, a minimal CSV that reproduces
  it is worth more than a description.
- **Security vulnerabilities:** do not open a public issue. Follow the private reporting process in
  [SECURITY.md](SECURITY.md).
