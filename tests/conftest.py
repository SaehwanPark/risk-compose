"""Test configuration for local workspace package imports."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SRC_PATHS = (
  REPO_ROOT / "packages" / "core" / "src",
  REPO_ROOT / "packages" / "cli" / "src",
  REPO_ROOT / "packages" / "tui" / "src",
  REPO_ROOT / "packages" / "gui" / "src",
)

for src_path in reversed(PACKAGE_SRC_PATHS):
  if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
