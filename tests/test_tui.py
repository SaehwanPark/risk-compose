from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from textual.widgets import Input, Static

from risk_compose.cli import main
from risk_compose.tui.app import RiskComposeApp


def _write_score_inputs(tmp_path: Path) -> tuple[Path, Path]:
  subjects_path = tmp_path / "subjects.csv"
  diagnoses_path = tmp_path / "diagnoses.csv"
  subjects_path.write_text(
    "ID,DOB,SEX,OREC,LTIMCAID,NEMCAID\n100,01/21/1950,1,0,1,0\n",
    encoding="utf-8",
  )
  diagnoses_path.write_text(
    "ID,ICD10\n100,A0104\n",
    encoding="utf-8",
  )
  return subjects_path, diagnoses_path


async def _wait_for_status(app: RiskComposeApp, pilot: Any, text: str) -> None:
  for _ in range(40):
    await pilot.pause(0.1)
    if text.lower() in str(app.query_one("#status-line", Static).render()).lower():
      return
  raise AssertionError(f"Timed out waiting for status containing {text!r}.")


async def _submit_command(app: RiskComposeApp, pilot: Any, command: str) -> None:
  prompt = app.query_one("#command-input", Input)
  prompt.focus()
  prompt.value = command
  app._dispatch_command(command)
  await pilot.pause(0.1)


def test_tui_launches_with_command_help_and_resizes() -> None:
  async def _run() -> None:
    app = RiskComposeApp()
    async with app.run_test(size=(100, 30)) as pilot:
      output_text = str(app.query_one("#screen-output", Static).render())
      assert "score --subjects" in output_text
      assert "subject_id: subject_id, beneficiary_id, patient_id, case_id, id" in output_text
      assert "Diagnosis aliases" in output_text
      await pilot.resize_terminal(140, 40)
      await pilot.pause()
      assert "risk-compose tui" in str(app.query_one("#title-bar", Static).render())
      app.exit()

  asyncio.run(_run())


def test_tui_score_workflow_exports_same_artifacts_as_cli(tmp_path: Path) -> None:
  subjects_path, diagnoses_path = _write_score_inputs(tmp_path)
  tui_export_dir = tmp_path / "tui-export"
  cli_export_dir = tmp_path / "cli-export"

  async def _run() -> None:
    app = RiskComposeApp()
    async with app.run_test(size=(140, 40)) as pilot:
      await _submit_command(
        app,
        pilot,
        f"score --subjects {subjects_path} --diagnoses {diagnoses_path}",
      )
      await _wait_for_status(app, pilot, "completed")
      summary_text = str(app.query_one("#screen-output", Static).render())
      assert "Score Review" in summary_text
      assert "subject_scores: 1 row(s)" in summary_text
      await _submit_command(app, pilot, f"export {tui_export_dir}")
      await _wait_for_status(app, pilot, "Exported")
      app.exit()

  asyncio.run(_run())

  exit_code = main(
    [
      "score",
      "--subjects",
      str(subjects_path),
      "--diagnoses",
      str(diagnoses_path),
      "--output-dir",
      str(cli_export_dir),
    ],
  )

  assert exit_code == 0
  for filename in (
    "subject_predictors.csv",
    "subject_scores.csv",
    "diagnosis_mappings.csv",
    "score_contributions.csv",
    "validation_issues.csv",
  ):
    assert (tui_export_dir / filename).read_text(encoding="utf-8") == (cli_export_dir / filename).read_text(encoding="utf-8")


def test_tui_explain_workflow_loads_and_runs(tmp_path: Path) -> None:
  subjects_path, diagnoses_path = _write_score_inputs(tmp_path)

  async def _run() -> None:
    app = RiskComposeApp()
    async with app.run_test(size=(140, 40)) as pilot:
      await _submit_command(
        app,
        pilot,
        f"explain load --subjects {subjects_path} --diagnoses {diagnoses_path}",
      )
      await _wait_for_status(app, pilot, "Loaded")
      preloaded_text = str(app.query_one("#screen-output", Static).render())
      assert "Explain input loaded" in preloaded_text
      await _submit_command(app, pilot, "explain run --subject-id 100")
      await _wait_for_status(app, pilot, "completed")
      summary_text = str(app.query_one("#screen-output", Static).render())
      assert "Subject Explain" in summary_text
      assert "subject_summary: 1 row(s)" in summary_text
      assert "raf_totals: 9 row(s)" in summary_text
      app.exit()

  asyncio.run(_run())


def test_tui_open_bundle_workflow_loads_exported_score_bundle(tmp_path: Path) -> None:
  subjects_path, diagnoses_path = _write_score_inputs(tmp_path)
  bundle_dir = tmp_path / "score-bundle"
  exit_code = main(
    [
      "score",
      "--subjects",
      str(subjects_path),
      "--diagnoses",
      str(diagnoses_path),
      "--output-dir",
      str(bundle_dir),
    ],
  )
  assert exit_code == 0

  async def _run() -> None:
    app = RiskComposeApp()
    async with app.run_test(size=(140, 40)) as pilot:
      await _submit_command(app, pilot, f"open --bundle-dir {bundle_dir}")
      await _wait_for_status(app, pilot, "Opened")
      summary_text = str(app.query_one("#screen-output", Static).render())
      assert "Opened Bundle" in summary_text
      assert "bundle_dir:" in summary_text
      assert "subject_scores: 1 row(s)" in summary_text
      app.exit()

  asyncio.run(_run())


def test_tui_artifact_search_and_row_detail_commands(tmp_path: Path) -> None:
  subjects_path, diagnoses_path = _write_score_inputs(tmp_path)

  async def _run() -> None:
    app = RiskComposeApp()
    async with app.run_test(size=(140, 40)) as pilot:
      await _submit_command(
        app,
        pilot,
        f"score --subjects {subjects_path} --diagnoses {diagnoses_path}",
      )
      await _wait_for_status(app, pilot, "completed")
      await _submit_command(app, pilot, "artifact diagnosis_mappings")
      await _wait_for_status(app, pilot, "Switched")
      await _submit_command(app, pilot, "search A0104")
      await _wait_for_status(app, pilot, "Search query")
      await _submit_command(app, pilot, "row 1")
      await _wait_for_status(app, pilot, "Showing row")
      output_text = str(app.query_one("#screen-output", Static).render())
      assert "diagnosis_mappings" in output_text
      assert "\"subject_id\": \"100\"" in output_text
      app.exit()

  asyncio.run(_run())
