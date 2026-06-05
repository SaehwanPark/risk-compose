from __future__ import annotations

from pathlib import Path
from typing import Any

from streamlit.testing.v1 import AppTest

from risk_compose.cli import main

GUI_APP_PATH = Path("packages/core/src/risk_compose/gui/app.py")
GUI_RUN_TIMEOUT_SECONDS = 10


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


def _text_input(at: AppTest, label: str) -> Any:
  return next(widget for widget in at.text_input if widget.label == label)


def _button(at: AppTest, label: str) -> Any:
  return next(widget for widget in at.button if widget.label == label)


def _selectbox(at: AppTest, label: str) -> Any:
  return next(widget for widget in at.selectbox if widget.label == label)


def _summary_code(at: AppTest) -> str:
  return at.code[0].value


def _run(widget: Any) -> Any:
  return widget.run(timeout=GUI_RUN_TIMEOUT_SECONDS)


def test_gui_score_workflow_exports_same_artifacts_as_cli(tmp_path: Path) -> None:
  subjects_path, diagnoses_path = _write_score_inputs(tmp_path)
  gui_export_dir = tmp_path / "gui-export"
  cli_export_dir = tmp_path / "cli-export"

  at = AppTest.from_file(GUI_APP_PATH)
  _run(at)
  _text_input(at, "Subject CSV").set_value(str(subjects_path))
  _text_input(at, "Diagnosis CSV").set_value(str(diagnoses_path))
  _run(_button(at, "Run Score").click())

  assert "Score Review" in _summary_code(at)
  assert _selectbox(at, "Artifact").value == "subject_scores"

  _text_input(at, "Export Directory").set_value(str(gui_export_dir))
  _run(_button(at, "Export Current Session").click())

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
    assert (gui_export_dir / filename).read_text(encoding="utf-8") == (cli_export_dir / filename).read_text(encoding="utf-8")


def test_gui_explain_workflow_loads_and_runs(tmp_path: Path) -> None:
  subjects_path, diagnoses_path = _write_score_inputs(tmp_path)

  at = AppTest.from_file(GUI_APP_PATH)
  _run(at)
  _run(at.radio[0].set_value("Explain"))
  _text_input(at, "Subject CSV").set_value(str(subjects_path))
  _text_input(at, "Diagnosis CSV").set_value(str(diagnoses_path))
  _run(_button(at, "Load Subjects").click())

  assert _selectbox(at, "Subject").value == "100"

  _run(_button(at, "Run Explain").click())

  assert "Subject Explain" in _summary_code(at)
  assert _selectbox(at, "Artifact").value == "subject_summary"


def test_gui_open_bundle_workflow_loads_exported_score_bundle(tmp_path: Path) -> None:
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

  at = AppTest.from_file(GUI_APP_PATH)
  _run(at)
  _run(at.radio[0].set_value("Open Bundle"))
  _text_input(at, "Bundle Directory").set_value(str(bundle_dir))
  _run(_button(at, "Open Bundle").click())

  assert "Opened Bundle" in _summary_code(at)
  assert _selectbox(at, "Artifact").value == "subject_scores"
