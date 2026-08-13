# Installation

## Prerequisites

- **Python 3.11 or newer.** The package targets 3.11 and 3.12 and uses modern typing syntax.
- **pip** and the ability to create a virtual environment (`venv` ships with CPython).
- No system-level libraries are required. PDF generation uses the pure-Python `fpdf2`, and charts
  render through Matplotlib's headless Agg backend, so the toolchain works on servers without a GUI.

Check your interpreter version before starting:

```bash
python --version
```

## Create a virtual environment

Working inside a virtual environment keeps the project's dependencies isolated from the rest of the
system.

### Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script, allow scripts for the current user and try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.venv\Scripts\Activate.ps1
```

### Unix / macOS

```bash
python -m venv .venv
source .venv/bin/activate
```

## Install dependencies

From the project root (the directory containing `pyproject.toml`):

### Runtime only

Installs the package and just the libraries needed to run it:

```bash
pip install -e .
```

### With development extras

Adds the test, lint, and type-checking toolchain (`pytest`, `pytest-cov`, `ruff`, `mypy`, and type
stubs). This is the recommended setup for contributors:

```bash
pip install -e ".[dev]"
```

The editable install (`-e`) links the package to the source tree, so code changes take effect
without reinstalling. It also registers the `dqms` console entry point on your `PATH`.

## Verify the installation

```bash
dqms --version
```

You should see output of the form `dqms 1.0.0`. As a further check, the CLI prints its full command
list when invoked with no arguments:

```bash
dqms --help
```

You can also invoke the package as a module, which is equivalent to the console script:

```bash
python -m dqms --help
```

## Troubleshooting

**`dqms` is not recognised as a command.** The console script is installed into the virtual
environment's scripts directory. Make sure the environment is activated (your shell prompt should
show `(.venv)`). As a fallback, `python -m dqms` always works regardless of `PATH`.

**PowerShell refuses to run the activation script.** The default execution policy blocks unsigned
scripts. Run `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` once, then
re-activate.

**A file is rejected with a security error on load.** This is by design. The loader enforces an
extension allow-list, a maximum file size, and (optionally) a base-directory restriction, and it
refuses symlinked files. Confirm the file's extension is in `security.allowed_extensions`, that its
size is below `security.max_file_size_mb`, and that it is not a symlink. These limits are
configurable in `config/config.yaml` or via `DQMS_SECURITY__*` environment variables.

**`Configuration file not found`.** Passing `--config path/to/config.yaml` requires the file to
exist. Without `--config`, the system looks for `config/config.yaml` under the current working
directory, then the bundled default, and falls back to built-in defaults if neither is present.

**Invalid configuration on startup.** Settings are validated by Pydantic at load time. The error
message names the offending field (for example, scoring weights that do not sum to 1.0, or an
unknown log level). Correct the value in your YAML file or environment variable and re-run.

**Reports render without charts.** Chart generation requires the source DataFrame and
`report.include_charts: true`. The `report` and `analyze --report` commands pass the frame
automatically; if you call `ReportGenerator.generate` directly, supply the `frame` argument.
