from __future__ import annotations

from importlib import import_module

from risk_compose import score_subjects
from risk_compose.cli import main
from risk_compose.gui.runner import run_gui
from risk_compose.tui.app import RiskComposeApp


def test_legacy_python_imports_are_removed() -> None:
  for module_name in (
    "hcc_generator",
    "hcc_generator.cli",
    "hcc_generator.core",
    "hcc_generator.gui.runner",
    "hcc_generator.tui.app",
  ):
    try:
      import_module(module_name)
    except ModuleNotFoundError:
      continue
    raise AssertionError(f"{module_name} should not be importable.")


def test_canonical_imports_still_resolve() -> None:
  assert score_subjects is not None
  assert main is not None
  assert run_gui is not None
  assert RiskComposeApp.__name__ == "RiskComposeApp"
