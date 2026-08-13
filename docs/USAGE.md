# Usage

This guide walks through every command-line command, the Python API, the dashboard, configuration
overrides, and how to read the quality score. It assumes the package is installed and the virtual
environment is active (see [INSTALLATION.md](INSTALLATION.md)).

All commands accept two global options:

- `--config, -c PATH` — use a specific YAML configuration file.
- `--version` — print the version and exit.

## Command-line interface

### `analyze`

Runs the full pipeline — load, profile, validate, detect anomalies, score — and prints a summary.

```bash
dqms analyze data/customers.csv
```

Options:

- `--report / --no-report` — also write report files (default: off).
- `--anomalies / --no-anomalies` — run anomaly detection (default: on).
- `--output, -o PATH` — directory for report files when `--report` is set.

```bash
dqms analyze data/customers.csv --report --output output/
```

Expected output shape:

```text
╭──────────────── Analysis summary ────────────────╮
│ customers                                         │
│ Score: 86.4% (grade B)  Status: PASS              │
│ Rows: 10,000  Columns: 12  Issues: 137            │
╰───────────────────────────────────────────────────╯
        Quality dimensions
┏━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Dimension    ┃ Score  ┃ Explanation            ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Completeness │ 97.8%  │ 264 of 120000 cells... │
│ Validity     │ 99.1%  │ Based on invalid...    │
│ ...          │ ...    │ ...                    │
└──────────────┴────────┴────────────────────────┘
Recommendations:
  [warning] Address missing values - 2.2% of cells are missing. ...
```

Exit codes: `0` when the score meets the pass threshold, `2` when it does not, and `1` on a load or
analysis error. This makes `analyze` a convenient CI quality gate.

### `profile`

Prints per-column descriptive statistics without scoring.

```bash
dqms profile data/customers.csv
```

Expected output shape:

```text
                    Profile: customers.csv
┏━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━┳━━━━━━┳━━━━━━┓
┃ Column   ┃ Type   ┃ Nulls ┃ Unique ┃ Min ┃ Max  ┃ Mean ┃
┡━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━╇━━━━━━╇━━━━━━┩
│ age      │ int64  │ 0.4%  │ 71     │ 18  │ 95   │ 41.3 │
│ email    │ object │ 1.1%  │ 9,842  │ -   │ -    │ -    │
└──────────┴────────┴───────┴────────┴─────┴──────┴──────┘
Rows: 10,000  Columns: 12  Duplicates: 3  Missing: 0.22%
```

### `validate`

Applies the rule battery and lists the detected issues.

```bash
dqms validate data/customers.csv
```

Expected output shape:

```text
                     Validation: customers.csv
┏━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━┓
┃ Column  ┃ Rule          ┃ Severity ┃ Affected ┃ Message        ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━┩
│ email   │ invalid_email │ error    │ 42       │ Column 'email' │
│ phone   │ invalid_phone │ error    │ 18       │ Column 'phone' │
└─────────┴───────────────┴──────────┴──────────┴────────────────┘
Total affected values: 60
```

If no issues are found it prints a success line. It exits `2` when a CRITICAL issue is present.

For CI gating, `--strict` widens that gate to any ERROR-severity issue (invalid emails, phones,
dates, wrong types, and range violations):

```bash
dqms validate data/customers.csv --strict
```

### `clean`

Cleans a dataset and writes the result. The output path is required, and its extension determines
the export format (CSV, Excel, JSON, or Parquet). CSV/Excel exports have formula injection
neutralised automatically, unless `security.sanitize_exports` is turned off in configuration.

```bash
dqms clean data/raw.csv --output data/clean.csv
```

Expected output shape:

```text
╭─────────── Cleaning actions ───────────╮
│ - Standardised column names to snake_c │
│ - Trimmed whitespace in 4 text column( │
│ - Handled missing values in numeric... │
│ - Removed 3 duplicate row(s)           │
╰────────────────────────────────────────╯
Cleaned 10,000 -> 9,997 rows, written to data/clean.csv
```

### `compare`

Detects schema and data drift between a baseline and a current dataset.

```bash
dqms compare data/january.csv data/february.csv
```

Expected output shape:

```text
             Schema drift
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Change       ┃ Columns                ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Added        │ loyalty_tier           │
│ Removed      │ -                      │
│ Type changed │ age (int64->float64)   │
└──────────────┴────────────────────────┘
                     Data drift
┏━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━┓
┃ Column  ┃ PSI  ┃ KS p-value ┃ Mean change ┃ Severity ┃
┡━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━┩
│ balance │ 0.31 │ 0.001      │ 128.4       │ critical │
└─────────┴──────┴────────────┴─────────────┴──────────┘
Drift detected.
```

It exits `2` when any schema or data drift is detected.

### `report`

Generates report files for a dataset.

```bash
dqms report data/customers.csv --output output/
```

Options:

- `--output, -o PATH` — output directory (defaults to the configured `paths.output_dir`).
- `--format, -f FORMAT` — one of `html`, `pdf`, `summary`; repeatable. Defaults to the configured
  `report.formats`.

```bash
dqms report data/customers.csv -f html -f summary
```

Expected output shape:

```text
Reports written:
  html -> output/customers_report.html
  summary -> output/customers_summary.txt
```

### `history`

Lists runs previously recorded by `analyze`.

```bash
dqms history                      # every dataset, newest first
dqms history --dataset customers --limit 50
```

### `trend`

Plots how one dataset's score has moved across its recorded runs, and reports the net movement.

```bash
dqms trend customers
```

```text
                        Quality trend: customers
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ When (UTC)       ┃ Score ┃ Status ┃ Chart                                 ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 2026-08-01 09:00 │ 97.2% │ PASS   │ #######################################│
│ 2026-08-02 09:00 │ 95.0% │ PASS   │ ######################################.│
└──────────────────┴───────┴────────┴───────────────────────────────────────┘
Across 2 runs the score has declined by 2.2 points.
```

It exits `1` when the dataset has no recorded runs.

### `dashboard`

Launches the Streamlit dashboard.

```bash
dqms dashboard --port 8501
```

Options:

- `--port, -p PORT` — server port (default `8501`).
- `--host HOST` — interface to bind (default `127.0.0.1`). The dashboard reads whatever dataset is
  uploaded to it, so it stays on loopback unless you deliberately pass `--host 0.0.0.0`.

The command also forwards the `dashboard` configuration section (`max_upload_mb`, `theme`) to
Streamlit and disables Streamlit's usage telemetry.

## Monitoring over time

`analyze` records each run in a SQLite file (`paths.history_db`) and compares the result against that
dataset's previous run, so a regression is visible the moment it appears:

```text
Previous run 2026-08-01 09:00 UTC scored 97.2% - now down 2.2 points.
```

Pass `--no-record` for a one-off analysis that should not enter the history, or set
`history.enabled: false` to switch recording off entirely. `history.retention_runs` caps how many
runs are kept per dataset.

### Alerting on a regression

A regression is one of: the quality gate failed, the score fell below `alerts.min_score`, or the
score dropped by more than `alerts.max_score_drop` since the previous run. The reasons are always
printed. To also deliver them to a webhook:

```bash
export DQMS_ALERTS__ENABLED=true
export DQMS_ALERTS__WEBHOOK_URL="https://hooks.example.com/services/..."
dqms analyze data/customers.csv
```

Keep the URL in the environment rather than in `config/config.yaml`: a webhook URL is normally a
credential in its own right, and that file is committed. The URL is redacted in logs for the same
reason.

The destination is validated before anything is sent - HTTPS only, no credentials in the URL, no
redirects followed, and every address the host resolves to must be globally routable. Loopback,
RFC1918, carrier-grade NAT, cloud metadata endpoints, and multicast are all refused, which stops a
scheduled quality check from being turned into a probe of your own network. If you run a receiver on
localhost, set `alerts.allow_private_targets: true` to opt out deliberately.

The payload contains summary statistics only:

```json
{
  "source": "dqms",
  "dataset": "customers",
  "overall_score": 91.4,
  "grade": "A",
  "passed": true,
  "alerts": [{"reason": "score_dropped", "detail": "Score fell 6.1 points..."}]
}
```

Never cell values, column names, or a source path - an alert crosses a network boundary, so it must
not become a channel through which the dataset itself leaks.

## Python API

The same pipeline that powers the CLI is available directly. `QualityPipeline` orchestrates the
analysis and `ReportGenerator` renders the result.

```python
from dqms.config.settings import load_settings
from dqms.services.orchestrator import QualityPipeline
from dqms.reports.generator import ReportGenerator

# Load settings (None uses the default lookup: ./config/config.yaml then packaged default)
settings = load_settings()

pipeline = QualityPipeline(settings)

# Option A: analyse a file directly through the secure loader
report = pipeline.analyze_file("data/customers.csv")

# Option B: analyse an in-memory DataFrame you already hold
frame = pipeline.load("data/customers.csv")
report = pipeline.analyze(frame, dataset_name="customers", source_path="data/customers.csv")

print(f"Score: {report.quality.overall_score:.1f}% (grade {report.quality.grade})")
print(f"Passed: {report.quality.passed}")
for dim in report.quality.dimensions:
    print(f"  {dim.dimension.value}: {dim.score:.1f}%")
for rec in report.recommendations:
    print(f"  [{rec.severity.value}] {rec.title}")

# Render reports (returns {format: written_path})
outputs = ReportGenerator(settings).generate(
    report, frame=frame, output_dir="output/", formats=["html", "pdf", "summary"]
)
for fmt, path in outputs.items():
    print(f"{fmt}: {path}")
```

Individual services can also be used on their own — for example `DataProfiler().analyze(frame)`,
`DataValidator(settings).analyze(frame)`, or `DataCleaner(settings).clean(frame)` — each returning
its immutable result model.

## Running the dashboard

Start it through the CLI:

```bash
dqms dashboard --port 8501
```

Or run the Streamlit app directly:

```bash
streamlit run src/dqms/dashboard/app.py
```

The dashboard offers two modes in the sidebar:

- **Analyse** — upload a single dataset to see its score, quality-dimension chart, recommendations,
  validation issues, column profile, interactive charts, and a downloadable HTML report.
- **Compare** — upload a baseline and a current dataset to view schema and data drift.

Uploaded files are written to a private temporary directory and loaded through the same secure
loader the CLI uses, so the dashboard enforces the identical security policy.

## Overriding configuration

### With a YAML file

Copy or edit `config/config.yaml` and point the CLI at it:

```bash
dqms --config config/config.yaml analyze data/customers.csv
```

For example, to require a stricter score and treat negative numbers as invalid:

```yaml
scoring:
  pass_threshold: 90.0
validation:
  treat_negative_as_invalid: true
```

### With environment variables

Environment variables override the YAML file. Use the `DQMS_` prefix and `__` to descend into nested
sections:

```bash
# Raise the pass threshold to 90
export DQMS_SCORING__PASS_THRESHOLD=90

# Enable Isolation Forest alongside the default methods requires editing YAML,
# but simple scalars are settable directly, e.g. a larger file-size limit:
export DQMS_SECURITY__MAX_FILE_SIZE_MB=1024

# Turn on structured JSON logs at DEBUG level
export DQMS_LOGGING__LEVEL=DEBUG
export DQMS_LOGGING__JSON_LOGS=true
```

Precedence, highest to lowest: a local `.env` file, then process environment variables, then the
YAML file, then built-in defaults.

## Interpreting the quality score

The overall score is a weighted average of five dimensions, each normalised to a 0-100 percentage.
The default weights (configurable under `scoring.weights`, and validated to sum to 1.0) are:

| Dimension | Default weight | What it measures |
| --- | --- | --- |
| Completeness | 0.25 | Share of non-missing cells (`1 - missing_ratio`) |
| Validity | 0.25 | Absence of invalid emails, phones, dates, and type mismatches |
| Uniqueness | 0.20 | Absence of fully duplicated rows |
| Consistency | 0.15 | Absence of whitespace, blank strings, and over-length values |
| Accuracy | 0.15 | Absence of out-of-range values and statistical anomaly density |

Each dimension score is `100 * (1 - penalty)`, where the penalty is the ratio of affected cells (or
rows) to the total. The accuracy dimension blends range violations with anomaly density, weighting
range violations more heavily because statistical outliers can be legitimate extreme values rather
than errors.

The overall score is compared against `scoring.pass_threshold` (default 80.0) to produce the
pass/fail verdict, and it maps to a letter grade:

| Grade | Overall score |
| --- | --- |
| A | 90 and above |
| B | 80 to 89.9 |
| C | 70 to 79.9 |
| D | 60 to 69.9 |
| F | below 60 |

Every dimension carries a plain-language explanation of how its score was derived, and the pipeline
turns low scores and specific rule failures into prioritised recommendations, so a score is always
accompanied by concrete next steps rather than a bare number.
