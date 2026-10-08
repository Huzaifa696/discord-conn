#!/usr/bin/env python3
"""Entry point for the Discord Connector CLI."""

import sys
from pathlib import Path

# Ensure root directory is on sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from discord_conn.cli.main import cli

if __name__ == "__main__":
    cli()
