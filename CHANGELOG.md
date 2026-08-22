# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] - unreleased

### Added

**A release pipeline.** Distributions are built, checked, and version-matched against the tag on
every `v*` tag, and uploaded by a workflow using PyPI Trusted Publishing (OIDC), so no API token
exists on a developer machine or in repository secrets, and every distribution carries a build
attestation. Nothing has been uploaded yet - `pip install dqms` does not work until the first tag
is pushed; install from a clone or from the repository URL in the meantime.

### Changed

**The dashboard is an opt-in extra.** Streamlit and Plotly moved out of the base dependencies into
the `dashboard` extra. The dashboard runs as its own process and is never imported by the library or
the CLI, so a plain install no longer pulls a web framework in order to profile a CSV. An `all`
extra installs everything. Running `dqms dashboard` without the extra now explains what to install
instead of failing inside the subprocess.

## [1.2.0] - 2026-08-13

### Added

**A History view in the dashboard.** Pick any dataset with recorded runs and see its score plotted
over time against the pass threshold, the net movement since the first run, and a table of every
recorded run. The timeline is the same one the CLI writes, so runs from a scheduled `dqms analyze`
appear here. An analysis performed in the dashboard now also reports its movement against the
previous run.

**A container image.** A multi-stage `Dockerfile` for running scheduled checks without installing
Python on the host. CI builds it on every push and verifies that it starts, runs as a non-root user,
and analyses a dataset end to end.

**Dashboard tests.** The dashboard had no test coverage at all; it is now exercised headlessly
through Streamlit's AppTest harness - the three modes, the empty-history message, and a rendered
timeline.

### Changed

- Coverage measurement now includes the dashboard, which was previously excluded. The headline
  number falls from 88% to 84% as a result: untested code is counted rather than hidden.

### Security

- The image runs as an unprivileged user (uid 10001), holds no secrets, and expects its input mounted
  read-only. The alert webhook URL is passed at run time so it never enters an image layer, and
  `.dockerignore` keeps local state - `.env`, logs, output, and the history database - out of the
  build context entirely.
- Recording a run from the dashboard is idempotent per upload. Streamlit re-executes its script on
  every interaction, so a naive implementation would have written a duplicate row on each click and
  quietly corrupted the timeline the alerting thresholds are measured against.

## [1.1.0] - 2026-08-13

Turns the tool into an actual monitor. Until now every run stood alone: a dataset could be scored,
but not tracked, so a slow decline was invisible until someone happened to look.

### Added

**Run history.** Every `analyze` run is recorded in a local SQLite file (`paths.history_db`). Two new
commands read it: `dqms history` lists past runs, and `dqms trend <dataset>` plots how a dataset's
score has moved and reports the net movement. `--no-record` skips recording a one-off analysis, and
`history.retention_runs` caps how many runs are kept per dataset.

**Regression detection.** Each run is compared against that dataset's previous run and the movement
is printed. A regression - a failed gate, a score below `alerts.min_score`, or a drop larger than
`alerts.max_score_drop` - is reported explicitly.

**Alerting.** Regressions can be delivered to a webhook as JSON. Disabled by default.

### Changed

- `dqms dashboard` now starts Streamlit headless and opens the browser itself. Streamlit's
  interactive first-run e-mail prompt would otherwise block any caller without a console - a
  scheduled job, a container, a CI step. `--no-open` skips the browser for unattended use.

### Security

- The alert webhook is the only outbound request the system makes, and is guarded against SSRF:
  HTTPS only, no credentials embedded in the URL, no redirects followed, and every address the host
  resolves to must be globally routable. The check is written as an allow-list rather than a list of
  banned ranges, because enumerating bad ranges is always one range behind - carrier-grade NAT
  (100.64.0.0/10) is neither "private" nor routable. Multicast is excluded explicitly on top.
- Alert payloads carry summary statistics only, never cell values, column names, or a source path.
  The webhook URL is redacted in logs, since such a URL is normally a credential itself.
- Run history uses parameterised SQL exclusively; a dataset name is derived from a file name and is
  treated as untrusted input.
- The history database is excluded from version control: it records which datasets were analysed and
  when, which is operational information rather than source.

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

[1.2.0]: https://github.com/mojtaba-py-code/smart-data-quality-monitoring-system/releases/tag/v1.2.0
[1.1.0]: https://github.com/mojtaba-py-code/smart-data-quality-monitoring-system/releases/tag/v1.1.0
[1.0.0]: https://github.com/mojtaba-py-code/smart-data-quality-monitoring-system/releases/tag/v1.0.0
