# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-08-13

First stable release.

### Added

**Loading.** CSV, TSV, TXT, Excel (`.xlsx`, `.xlsm`, and legacy `.xls` with the optional `xlrd`
extra), JSON (records and line-delimited), and Parquet. Text encoding is detected with `chardet`,
CSV delimiters are sniffed, files above a configurable threshold are read in chunks, and an optional
row cap bounds what is loaded.

**Profiling.** Per-column dtype, non-null count, null ratio, unique count, cardinality ratio, memory
footprint, mode and top frequency, plus min/max/mean/median/standard deviation for numeric columns.
Dataset-level roll-ups cover row and column counts, duplicate rows, and missing-cell ratios.

**Validation.** Rules for missing values, empty and whitespace-only strings, leading and trailing
whitespace, numeric columns polluted by text, range and sign violations, over-length strings, invalid
e-mail addresses, invalid telephone numbers, unparseable dates, and duplicate rows. Column-hint
matching runs the right rule against the right column. Issues carry a rule id, severity, affected
count, and a bounded sample of zero-based row positions.

**Cleaning.** An ordered, auditable sequence: duplicate column labels made unique, column names
standardised to snake_case ASCII, whitespace trimmed and collapsed, optional case normalisation,
currency strings converted to floats, numeric coercion, date parsing, missing-value imputation
(mean/median/zero/drop for numeric, mode/constant/drop for categorical), and duplicate-row removal.
Every run returns an action log and before/after row counts; the input frame is never mutated.

**Scoring.** A weighted 0-100 score across completeness, validity, uniqueness, consistency, and
accuracy. Weights are configurable and validated to sum to 1.0. Each dimension carries a
plain-language explanation of how its score was derived, so the result is auditable rather than
opaque.

**Anomaly detection.** Univariate z-score and IQR per numeric column, plus a multivariate Isolation
Forest for rows that are only unusual in combination. Which methods run is configuration-driven.

**Drift monitoring.** Schema drift (added, removed, and retyped columns) and data drift (Population
Stability Index, a two-sample Kolmogorov-Smirnov test, moment comparisons, categorical PSI, and
pairwise correlation shifts), each graded against configurable bands.

**Reporting and interfaces.** Self-contained HTML (charts embedded as base64), paginated PDF, and a
plain-text summary. A Typer CLI with seven commands and CI-friendly exit codes, and a Streamlit
dashboard that calls the same pipeline as the CLI so the two can never disagree.

**Configuration.** Layered and validated at load time: built-in defaults, then `config/config.yaml`,
then environment variables (`DQMS_` prefix, `__` nesting), then a local `.env`.

### Security

The operator is trusted; every dataset file is not. Enforced by default:

- path resolution with base-directory containment, symlink refusal, and an extension allow-list
- rejection of NTFS alternate-data-stream paths, where `payload.exe:hidden.csv` presents a `.csv`
  suffix to a naive check while the bytes read belong to a stream on an executable
- an on-disk size limit and a separate in-memory budget, so a small, highly compressible file cannot
  expand into an unbounded frame
- spreadsheet formula-injection neutralisation on CSV and Excel export, applied to column headers as
  well as cell values
- Unicode-normalised output file names stripped of separators and control characters
- HTML autoescaping in report rendering, and YAML parsed without an unsafe loader
- log sinks with diagnostics disabled, and line breaks in untrusted text escaped so a crafted file or
  column name cannot forge a log line
- a dashboard bound to loopback with telemetry disabled

See [SECURITY.md](SECURITY.md) for the full threat model, the hardening guide for shared
deployments, and the residual limitations.

[1.0.0]: https://github.com/mojtaba-py-code/smart-data-quality-monitoring-system/releases/tag/v1.0.0
