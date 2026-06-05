"""CLI launcher for the Streamlit GUI frontend."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from importlib.resources import as_file, files
from pathlib import Path


def run_gui(*, bundle_dir: Path | None = None) -> int:
  """Launch the Streamlit review frontend in the current environment."""
  app_resource = files("risk_compose.gui").joinpath("app.py")
  with as_file(app_resource) as app_path:
    command = [sys.executable, "-m", "streamlit", "run", str(app_path)]
    if bundle_dir is not None:
      command.extend(["--", "--bundle-dir", str(bundle_dir)])
    completed = subprocess.run(command, check=False)
  return int(completed.returncode)


def main(argv: Sequence[str] | None = None) -> int:
  """Run the standalone GUI console script."""
  parser = argparse.ArgumentParser(prog="risk-compose-gui")
  parser.add_argument(
    "--bundle-dir",
    help="Optional previously exported score or explain bundle to open at startup.",
  )
  args = parser.parse_args(list(argv) if argv is not None else None)
  bundle_dir = Path(args.bundle_dir).resolve() if args.bundle_dir else None
  return run_gui(bundle_dir=bundle_dir)
