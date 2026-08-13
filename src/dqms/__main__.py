"""Enable ``python -m dqms`` as an alias for the CLI entry point."""

from __future__ import annotations

from dqms.cli import app

if __name__ == "__main__":
    app()
