# Smart Data Quality Monitoring System

[![CI](https://github.com/mojtaba-py-code/smart-data-quality-monitoring-system/actions/workflows/ci.yml/badge.svg)](https://github.com/mojtaba-py-code/smart-data-quality-monitoring-system/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)
![Style Ruff](https://img.shields.io/badge/style-ruff-000000)

An enterprise-grade Python toolkit for measuring, explaining, and monitoring the quality of
tabular datasets. `dqms` loads data from a range of formats, profiles it, validates it against a
configurable battery of rules, cleans it, and condenses the result into a single explainable
0-100 quality score across five dimensions. It also detects statistical anomalies and tracks both
schema and distributional drift between dataset versions, then packages everything into HTML, PDF,
and plain-text reports or an interactive dashboard. The package is built on Clean Architecture
principles, is fully type-annotated, and treats every file it reads as an untrusted input.

![The dashboard analysing a sample dataset: overall score and grade, per-dimension quality bars, and
prioritised recommendations](docs/screenshots/dashboard.png)

## Features

### Loading

- Multi-format ingestion: CSV, TSV, TXT, Excel (`.xlsx`, `.xlsm`, and legacy `.xls` when the
  optional `xlrd` package is installed), JSON (records and line-delimited), and Parquet.
- Automatic text-encoding detection via `chardet` and automatic CSV delimiter sniffing.
- Chunked, streaming reads for large files above a configurable threshold, with an optional row
  sampling cap.

### Profiling

- Per-column descriptive statistics: dtype, non-null count, null ratio, unique count, cardinality
  ratio, memory footprint, mode and top frequency, plus min/max/mean/median/standard deviation for
  numeric columns.
- Dataset-level roll-ups: row and column counts, duplicate-row count and ratio, total and missing
  cell counts, and overall missing ratio.

### Validation

- A rule battery covering missing values, empty and whitespace-only strings, leading/trailing
  whitespace, wrong-type columns (numeric columns polluted by text), range and sign violations,
  over-length strings, invalid emails, invalid phone numbers, unparseable dates, and duplicate rows.
- Column-hint driven email/phone/date checks, so the right rules run on the right columns.
- Structured issues with rule id, severity, affected-count, and a bounded sample of zero-based row
  positions (positions rather than index labels, so results stay meaningful for datasets with a
  string or datetime index).
- Awkward-but-legal inputs are handled rather than crashed on: repeated column labels are analysed
  positionally and de-duplicated by the cleaner, and empty files are rejected with a clear message.

### Cleaning

- Ordered, auditable transformations: column-name standardisation (snake_case, ASCII,
  deduplicated), whitespace trimming and collapsing, optional case normalisation, currency-string
  to float conversion, numeric type coercion, date parsing, missing-value imputation
  (mean/median/zero/drop for numeric, mode/constant/drop for categorical), and duplicate removal.
- Every run returns a `CleaningResult` with a human-readable action log and before/after row counts;
  the input frame is never mutated.

### Quality scoring

- A transparent weighted score across five dimensions: completeness, validity, uniqueness,
  consistency, and accuracy. Each dimension is normalised to a percentage, weighted per
  configuration (weights validated to sum to 1.0), and combined into an overall score with a letter
  grade and a pass/fail verdict against a configurable threshold.
- Every dimension carries a plain-language explanation of how its score was derived.

### Anomaly detection

- Univariate Z-score and IQR (Tukey fence) detection per numeric column.
- Multivariate Isolation Forest detection to catch rows that are unusual only in combination.
- Which methods run is configuration-driven; each reports bounds, counts, ratios, and row indices.

### Monitoring over time

- Every `analyze` run is recorded in a local SQLite history, so a dataset is measured against its own
  past rather than judged in isolation. `dqms history` lists past runs and `dqms trend` plots how a
  dataset's score has moved.
- Each run reports its movement against the previous one, and a regression - a failed gate, a score
  below the alert floor, or a drop larger than the configured tolerance - can be delivered to a
  webhook. Alerting is off by default, and the destination is validated before anything is sent.

### Drift monitoring

- Schema drift: added, removed, and dtype-changed columns between a baseline and a current dataset.
- Data drift: Population Stability Index (PSI) plus a Kolmogorov-Smirnov test for numeric columns,
  moment comparisons (mean/median/variance), categorical PSI, and pairwise correlation shifts, each
  graded none/warning/critical against configurable bands.

### Visualization and reporting

- Matplotlib charts (headless Agg backend): quality-dimension bars, missing-value matrix, histogram
  grid, standardised box plots, and a correlation heatmap.
- Report generation to self-contained HTML (charts embedded as base64), paginated PDF (`fpdf2`,
  pure Python), and a compact plain-text summary.

### Interfaces

- A Typer-based CLI with nine commands and process-wide exit codes suitable for CI gating.
- A Streamlit dashboard that reuses the exact same pipeline as the CLI, guaranteeing consistent
  results between the two.

## Security

Every byte that enters the system passes through a single hardened trust boundary. The following
protections are enforced by default:

- **Path-traversal protection.** Candidate paths are fully resolved; when a base directory is
  configured, the resolved path must stay inside it.
- **File-size limits.** Files larger than the configured maximum are refused before any bytes are
  read into memory.
- **Extension allow-list.** Only explicitly permitted extensions are accepted, and NTFS
  alternate-data-stream paths are rejected outright - `payload.exe:hidden.csv` presents a `.csv`
  suffix to a naive check while the bytes read belong to a stream on an executable.
- **In-memory size budget.** A dataset that expands past `security.max_frame_memory_mb` once parsed
  is refused, so a small, highly compressible file cannot balloon into an unbounded frame.
- **Symlink refusal.** Symlinked dataset files are rejected unless explicitly allowed, preventing a
  link from redirecting a read outside the permitted directory.
- **Formula-injection neutralisation.** On CSV/Excel export, values beginning with a formula trigger
  (`=`, `+`, `-`, `@`, tab, carriage return) are prefixed with a single quote so spreadsheet software
  treats them as text. This covers **column headers as well as cell values**: a hostile dataset
  controls its own column names, and an Excel writer stores a header beginning with `=` as a live
  formula.
- **Log-forging defence.** Line breaks in untrusted text (file names, column labels) are escaped
  before they reach a log sink, so a crafted name cannot fabricate an extra log line.
- **Safe filename derivation.** Dataset and column values used in output file names are Unicode
  normalised and stripped of path separators and control characters.
- **Safe YAML loading.** Configuration is parsed through Pydantic's YAML settings source, never via
  `yaml.load` with an unsafe loader.
- **HTML autoescaping.** The Jinja2 report environment enables autoescaping for HTML and XML.
- **No secret leakage in logs.** Loguru sinks disable diagnostic tracebacks so values never leak
  through logged stack frames.
- **Loopback-only dashboard.** `dqms dashboard` binds to `127.0.0.1` unless `--host` says otherwise,
  and disables Streamlit's usage telemetry, so an uploaded dataset is never exposed to the local
  network or reported to a third party by default.
- **SSRF-guarded alerting.** Alerting is the only outbound request the system makes and is disabled
  by default. A webhook URL is operator-supplied configuration, so it is validated before a byte is
  sent: HTTPS only, no embedded credentials, no redirects followed, and every address the host
  resolves to must be globally routable - an allow-list, so cloud metadata endpoints, loopback,
  RFC1918, carrier-grade NAT, and multicast are all refused. The payload carries summary statistics
  only, never cell values or a source path, and the webhook URL is redacted in logs because such a
  URL is usually itself the credential.

The threat model, the boundary these controls defend, and the hardening required for shared or
automated deployments are documented in [SECURITY.md](SECURITY.md).

## Quick Start

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Unix / macOS
source .venv/bin/activate

# 2. Install the package with development extras
pip install -e ".[dev]"

# 3. Analyse a dataset
dqms analyze path/to/dataset.csv
```

Verify the installation at any time:

```bash
dqms --version
```

## CLI commands

Every command accepts the global options `--config/-c` (path to a YAML config file) and
`--version`.

| Command | Purpose | Example |
| --- | --- | --- |
| `analyze` | Run the full pipeline and print a scored summary | `dqms analyze data/customers.csv` |
| `profile` | Print per-column descriptive statistics | `dqms profile data/customers.csv` |
| `validate` | List detected validation issues | `dqms validate data/customers.csv` |
| `clean` | Clean a dataset and export the result | `dqms clean data/raw.csv -o data/clean.csv` |
| `compare` | Detect schema and data drift between two datasets | `dqms compare data/jan.csv data/feb.csv` |
| `report` | Generate HTML/PDF/summary reports | `dqms report data/customers.csv -o output/` |
| `history` | List previously recorded runs | `dqms history --dataset customers` |
| `trend` | Plot a dataset's score over time | `dqms trend customers` |
| `dashboard` | Launch the Streamlit dashboard | `dqms dashboard --port 8501` |

```bash
# Full analysis, also writing report files to a chosen directory
dqms analyze data/customers.csv --report --output output/

# Analysis without the (slower) anomaly-detection pass
dqms analyze data/customers.csv --no-anomalies

# Generate only selected report formats (the --format flag is repeatable)
dqms report data/customers.csv -f html -f summary

# Use an alternative configuration file
dqms --config config/config.yaml analyze data/customers.csv
```

`analyze` and `validate` exit non-zero when quality gates fail, which makes them convenient CI
checks: `analyze` exits `2` when the overall score is below the pass threshold, `validate` exits `2`
when a CRITICAL issue is present (or, with `--strict`, when any ERROR-severity issue is present),
and `compare` exits `2` when drift is detected.

```bash
# Fail the build on any error-severity validation issue
dqms validate data/customers.csv --strict

# Track quality over time: analyse on a schedule, then inspect the trend
dqms analyze data/customers.csv          # records the run and reports the movement
dqms trend customers                     # how the score has moved across runs
```

## Configuration

Configuration is layered. Built-in defaults are overlaid by `config/config.yaml`, which is in turn
overridden by environment variables, which are overridden by a local `.env` file. Everything is
validated by Pydantic at load time, so an invalid configuration fails fast with a clear message.

Environment variables use the `DQMS_` prefix and `__` as the nesting delimiter, mirroring the YAML
structure:

```bash
# Equivalent to logging.level: DEBUG
export DQMS_LOGGING__LEVEL=DEBUG

# Equivalent to security.max_file_size_mb: 1024
export DQMS_SECURITY__MAX_FILE_SIZE_MB=1024

# Equivalent to scoring.pass_threshold: 90
export DQMS_SCORING__PASS_THRESHOLD=90
```

The YAML file is organised into sections: `paths`, `logging`, `security`, `loader`, `validation`,
`cleaning`, `scoring`, `anomaly`, `drift`, `dashboard`, and `report`. See
[`config/config.yaml`](config/config.yaml) for the full annotated set of options and their defaults.

## Project structure

```text
.
├── config/
│   └── config.yaml            # Annotated default configuration
├── docs/
│   ├── ARCHITECTURE.md        # Layering, dependency rule, data flow
│   ├── INSTALLATION.md        # Environment setup and troubleshooting
│   ├── USAGE.md               # Worked CLI and Python API examples
│   └── screenshots/           # Dashboard and report screenshots
├── src/
│   └── dqms/
│       ├── core/              # Domain contracts, constants, exceptions
│       ├── config/            # Pydantic settings and layered loading
│       ├── models/            # Immutable Pydantic result objects
│       ├── services/          # Use cases (loader, profiler, validator, ...)
│       ├── utils/             # Security, IO, logging, patterns, timing
│       ├── reports/           # HTML/PDF/summary report generation
│       ├── dashboard/         # Streamlit presentation layer
│       ├── cli.py             # Typer CLI (console entry point `dqms`)
│       └── __main__.py        # `python -m dqms` alias
├── tests/
├── pyproject.toml
└── LICENSE
```

## Running tests

The development extras install the full quality toolchain. Run the test suite, linter, and type
checker from the project root:

```bash
# Unit tests
pytest

# Linting (Ruff)
ruff check .

# Static type checking (mypy)
mypy
```

Coverage settings, Ruff rule selection, and mypy strictness are all defined in
[`pyproject.toml`](pyproject.toml).

## Architecture

The system follows Clean Architecture: an inner domain layer (`core`) defines contracts and errors,
`models` holds immutable result objects, `services` implements the use cases, and the outer adapters
(CLI, dashboard, reports) depend inward only. The `QualityPipeline` orchestrator is the single
façade that both the CLI and dashboard call, so the two interfaces can never disagree. For the full
picture, including a layer diagram and the load -> profile -> validate -> anomaly -> score -> report
data flow, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

Released under the MIT License. See [LICENSE](LICENSE) for details.
