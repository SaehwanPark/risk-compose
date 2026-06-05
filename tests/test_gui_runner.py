from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import risk_compose.gui.runner as gui_runner


def test_run_gui_invokes_streamlit_with_startup_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
  recorded_command: list[str] = []
  recorded_check: bool | None = None

  def _fake_run(command: list[str], check: bool) -> SimpleNamespace:
    nonlocal recorded_command, recorded_check
    recorded_command = command
    recorded_check = check
    return SimpleNamespace(returncode=0)

  monkeypatch.setattr(subprocess, "run", _fake_run)

  exit_code = gui_runner.run_gui(bundle_dir=Path("out/bundle"))

  assert exit_code == 0
  assert recorded_check is False
  assert recorded_command[:4] == [sys.executable, "-m", "streamlit", "run"]
  assert recorded_command[-3:] == ["--", "--bundle-dir", "out/bundle"]
