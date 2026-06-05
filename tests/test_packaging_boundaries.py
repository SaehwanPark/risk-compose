from __future__ import annotations

import tomllib
from pathlib import Path


def test_bundle_package_includes_cli_tui_and_gui_modules() -> None:
  package_dir = Path("packages/core/src/risk_compose")

  assert (package_dir / "cli.py").exists()
  assert (package_dir / "tui" / "app.py").exists()
  assert (package_dir / "gui" / "runner.py").exists()


def test_single_distribution_metadata_defines_expected_scripts() -> None:
  pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
  project = pyproject["project"]

  assert project["name"] == "risk-compose"
  assert project["version"] == "1.0.2"
  assert project["license"] == "Apache-2.0"
  assert project["readme"] == "README.md"
  assert project["scripts"] == {
    "risk-compose": "risk_compose.cli:main",
    "risk-compose-tui": "risk_compose.tui.app:main",
    "risk-compose-gui": "risk_compose.gui.runner:main",
  }


def test_bundle_package_installs_frontend_dependencies_by_default() -> None:
  pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
  requirements = "\n".join(str(dependency).lower() for dependency in pyproject["project"]["dependencies"])

  assert "textual" in requirements
  assert "streamlit" in requirements


def test_bundle_package_advertises_supported_python_versions() -> None:
  pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
  project = pyproject["project"]
  classifiers = set(project["classifiers"])

  assert project["requires-python"] == ">=3.11"
  assert "Programming Language :: Python :: 3.11" in classifiers
  assert "Programming Language :: Python :: 3.12" in classifiers
  assert "Programming Language :: Python :: 3.13" in classifiers
