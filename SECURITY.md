# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 1.0.x | Yes |
| < 1.0 | No |

## Reporting a vulnerability

Please report security issues **privately**, not through a public issue.

Use GitHub's private vulnerability reporting: open the
[Security tab](https://github.com/mojtaba-py-code/smart-data-quality-monitoring-system/security)
and choose **Report a vulnerability**. The report stays visible only to you and the maintainer until
a fix is published.

Please include the affected version, a minimal reproduction (a small dataset file is ideal), and the
impact you believe the issue has. Expect an acknowledgement within 7 days and a status update within
30 days. Please give a reasonable window for a fix before any public disclosure.

## Threat model

DQMS is a local analysis tool. It assumes that **the operator is trusted but every dataset file is
not**: the operator deliberately points the tool at a file, and that file may be hostile.

### In scope

Anything that lets a crafted **dataset file**, **file name**, **configuration file**, or **column
value** do something the operator did not intend:

- escaping the permitted directory, following a symlink out of it, or reading an unexpected file type
- exhausting memory or disk through a file the size checks should have refused
- injecting an executable formula into an exported CSV/Excel file
- injecting scripts or markup into a generated HTML report
- injecting content into a generated file name or into log output
- crashing the pipeline in a way that leaks host paths or environment values

### Out of scope

- Vulnerabilities inside third-party parsers (`pandas`, `pyarrow`, `openpyxl`, `chardet`) rather than
  in this project's code. Please report those upstream; if this project can add a meaningful
  mitigation, a report here is still welcome.
- Consequences of the operator deliberately widening the configuration, for example raising
  `security.max_file_size_mb` past available memory or allowing extra extensions.
- Exposure caused by deliberately publishing the dashboard with `dqms dashboard --host 0.0.0.0`.
  The dashboard has no authentication of its own; see *Hardening* below.
- Anything requiring an attacker who already has code execution or write access on the host.

## Security controls

These are enforced by default and covered by the test suite:

| Control | Where |
| --- | --- |
| Path resolution, base-directory containment, symlink refusal, extension allow-list, size cap | `src/dqms/utils/security.py`, applied by `services/loader.py` |
| Rejection of NTFS alternate-data-stream paths (`file.exe:hidden.csv` reads a stream on an executable while presenting a `.csv` suffix to an allow-list) and of paths containing a null byte | `src/dqms/utils/security.py` |
| In-memory size budget, so a small compressed file cannot expand into an unbounded frame | `security.max_frame_memory_mb`, enforced in `services/loader.py` |
| Spreadsheet formula-injection neutralisation on CSV/Excel export, applied to **cell values and column headers alike** - a hostile dataset controls its own column names, and a spreadsheet evaluates the header row like any other | `src/dqms/utils/io.py` |
| Log-forging defence: line breaks in untrusted text are escaped, so one event can never become two log lines | `src/dqms/utils/logging.py` |
| Unicode-normalised, separator-stripped output file names | `sanitize_filename` |
| HTML autoescaping in report rendering | `src/dqms/reports/generator.py` |
| YAML parsed through Pydantic settings, never `yaml.load` with an unsafe loader | `src/dqms/config/settings.py` |
| Log sinks with `diagnose=False`, so values never leak through logged stack frames | `src/dqms/utils/logging.py` |
| Dashboard bound to loopback with telemetry disabled | `dqms dashboard` in `src/dqms/cli.py` |

The project contains no use of `eval`, `exec`, `pickle`, `os.system`, or `shell=True`.

## Hardening for shared or automated deployments

The defaults suit a single operator on a workstation. If DQMS runs somewhere less trusted - a shared
server, a scheduled job, or behind any kind of service - change these:

```yaml
security:
  restrict_to_input_dir: true   # confine every read to paths.input_dir
  max_file_size_mb: 64          # bytes on disk
  max_frame_memory_mb: 256      # bytes once parsed - the limit that matters
  allowed_extensions: [.csv]    # narrow to the formats you actually ingest

loader:
  sample_rows: 1000000          # bound the in-memory row count
```

Keep `dqms dashboard` on loopback and put authentication in front of it (an SSH tunnel or an
authenticating reverse proxy) rather than binding it to a public interface.

## Known limitations

Stated plainly so operators can judge the residual risk:

- **`max_frame_memory_mb` bounds retention, not peak allocation.** A compressed container such as
  `.xlsx` or `.parquet` can expand far beyond its size on disk - a 50 KB Parquet file that becomes a
  400 MB frame is easy to construct. The budget rejects the dataset, but only after the parser has
  already materialised it, so the peak still occurs. For genuinely untrusted input, combine it with
  `loader.sample_rows` and a small `security.max_file_size_mb`.
- **The dashboard has no authentication or authorisation.** It is safe because it is loopback-only
  by default, not because it can defend itself.
- **Dependencies are declared with lower bounds only.** There is no lockfile, so a reproducible
  deployment should pin its own versions and track advisories for the parsing libraries.
