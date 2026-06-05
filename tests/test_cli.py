from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

import risk_compose.cli as cli
from risk_compose.cli import build_parser, main


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
  with path.open("r", encoding="utf-8", newline="") as handle:
    return list(csv.DictReader(handle))


def test_build_parser_requires_score_command_args() -> None:
  parser = build_parser()
  args = parser.parse_args(
    [
      "score",
      "--subjects",
      "subjects.csv",
      "--diagnoses",
      "diagnoses.csv",
      "--output-dir",
      "out",
    ],
  )
  assert args.command == "score"
  assert args.input_format == "csv"
  assert args.output_format == "csv"


def test_build_parser_supports_tui_command() -> None:
  parser = build_parser()
  args = parser.parse_args(["tui", "--bundle-dir", "out/score"])
  assert args.command == "tui"
  assert args.bundle_dir == "out/score"


def test_build_parser_supports_gui_command() -> None:
  parser = build_parser()
  args = parser.parse_args(["gui", "--bundle-dir", "out/score"])
  assert args.command == "gui"
  assert args.bundle_dir == "out/score"


def test_cli_score_writes_expected_artifacts(tmp_path: Path) -> None:
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
  output_dir = tmp_path / "out"

  exit_code = main(
    [
      "score",
      "--subjects",
      str(subjects_path),
      "--diagnoses",
      str(diagnoses_path),
      "--output-dir",
      str(output_dir),
    ],
  )

  assert exit_code == 0
  expected_outputs = (
    output_dir / "subject_predictors.csv",
    output_dir / "subject_scores.csv",
    output_dir / "diagnosis_mappings.csv",
    output_dir / "score_contributions.csv",
    output_dir / "validation_issues.csv",
  )
  for path in expected_outputs:
    assert path.exists()


def test_cli_score_supports_esrd_v24_model_versions(tmp_path: Path) -> None:
  subjects_path = tmp_path / "subjects.csv"
  diagnoses_path = tmp_path / "diagnoses.csv"
  subjects_path.write_text(
    "ID,DOB,SEX,OREC,FBDUAL,PBDUAL,LTI\n100,05/01/1953,2,0,1,0,0\n",
    encoding="utf-8",
  )
  diagnoses_path.write_text(
    "ID,ICD10\n100,A0103\n",
    encoding="utf-8",
  )
  output_dir = tmp_path / "esrd-out"

  exit_code = main(
    [
      "score",
      "--subjects",
      str(subjects_path),
      "--diagnoses",
      str(diagnoses_path),
      "--output-dir",
      str(output_dir),
      "--model-version",
      "esrd_v24_2026",
    ],
  )

  assert exit_code == 0
  score_row = _read_csv_rows(output_dir / "subject_scores.csv")[0]
  assert score_row["model_version"] == "esrd_v24_2026"
  assert float(score_row["score_dial"]) == pytest.approx(0.714)
  assert float(score_row["score_graft_ne_ge65_dur4_9_fbd"]) == pytest.approx(4.021)


def test_cli_score_supports_rxhcc_t_model_versions(tmp_path: Path) -> None:
  subjects_path = tmp_path / "subjects.csv"
  diagnoses_path = tmp_path / "diagnoses.csv"
  subjects_path.write_text(
    "ID,DOB,SEX,OREC,ESRD\n100,01/01/1970,1,0,1\n",
    encoding="utf-8",
  )
  diagnoses_path.write_text(
    "ID,ICD10\n100,F200\n",
    encoding="utf-8",
  )
  output_dir = tmp_path / "rxhcc-out"

  exit_code = main(
    [
      "score",
      "--subjects",
      str(subjects_path),
      "--diagnoses",
      str(diagnoses_path),
      "--output-dir",
      str(output_dir),
      "--model-version",
      "rxhcc_v8_t_2026",
    ],
  )

  assert exit_code == 0
  score_row = _read_csv_rows(output_dir / "subject_scores.csv")[0]
  mapping_row = _read_csv_rows(output_dir / "diagnosis_mappings.csv")[0]
  assert score_row["model_version"] == "rxhcc_v8_t_2026"
  assert float(score_row["score_ce_lti"]) == pytest.approx(2.529)
  assert float(score_row["score_ne_lti"]) == pytest.approx(2.358)
  assert mapping_row["mapped_cc"] == "RXCC130"
  assert mapping_row["mapped_hcc"] == "RXHCC130"


def test_cli_score_supports_elixhauser_model_version(tmp_path: Path) -> None:
  subjects_path = tmp_path / "subjects.csv"
  diagnoses_path = tmp_path / "diagnoses.csv"
  subjects_path.write_text("subject_id\nCASE-1\n", encoding="utf-8")
  diagnoses_path.write_text(
    "subject_id,icd10_code,diagnosis_sequence,present_on_admission\n"
    "CASE-1,E119,2,\n"
    "CASE-1,I509,2,Y\n"
    "CASE-1,D500,2,Y\n",
    encoding="utf-8",
  )
  output_dir = tmp_path / "elixhauser-out"

  exit_code = main(
    [
      "score",
      "--subjects",
      str(subjects_path),
      "--diagnoses",
      str(diagnoses_path),
      "--output-dir",
      str(output_dir),
      "--model-version",
      "elixhauser_v2026_1",
    ],
  )

  assert exit_code == 0
  predictor_row = _read_csv_rows(output_dir / "subject_predictors.csv")[0]
  score_row = _read_csv_rows(output_dir / "subject_scores.csv")[0]
  assert predictor_row["CMR_DIAB_UNCX"] == "1"
  assert predictor_row["CMR_HF"] == "1"
  assert predictor_row["CMR_BLDLOSS"] == "1"
  assert float(score_row["score_readmission_index"]) == pytest.approx(9.0)
  assert float(score_row["score_mortality_index"]) == pytest.approx(10.0)


def test_cli_rejects_unimplemented_parquet_output(tmp_path: Path) -> None:
  subjects_path = tmp_path / "subjects.csv"
  diagnoses_path = tmp_path / "diagnoses.csv"
  subjects_path.write_text("ID,DOB,SEX,OREC\n", encoding="utf-8")
  diagnoses_path.write_text("ID,ICD10\n", encoding="utf-8")

  exit_code = main(
    [
      "score",
      "--subjects",
      str(subjects_path),
      "--diagnoses",
      str(diagnoses_path),
      "--output-dir",
      str(tmp_path / "out"),
      "--output-format",
      "parquet",
    ],
  )

  assert exit_code == 2


def test_cli_prepare_source_writes_expected_artifacts(tmp_path: Path) -> None:
  subjects_path = tmp_path / "subjects_raw.csv"
  professional_path = tmp_path / "professional_raw.csv"
  subjects_path.write_text(
    "bene_key,birth_dt,sex_cd,orec_cd,ltimcaid_cd,nemcaid_cd\n100,01/21/1950,1,0,1,0\n",
    encoding="utf-8",
  )
  professional_path.write_text(
    "bene_key,dx_code,claim_id,procedure_code\n100,A0104,prof-1,C1062\n",
    encoding="utf-8",
  )
  manifest_path = tmp_path / "source_manifest.json"
  manifest_path.write_text(
    json.dumps(
      {
        "source_profile": "cms_purchased_files_ffs_2026",
        "source_kind": "flat-file",
        "sources": {
          "subject": {
            "path": str(subjects_path),
            "columns": {
              "subject_id": "bene_key",
              "date_of_birth": "birth_dt",
              "sex": "sex_cd",
              "original_reason_entitlement_code": "orec_cd",
              "limited_income_medicaid_flag": "ltimcaid_cd",
              "new_enrollee_medicaid_flag": "nemcaid_cd",
            },
          },
          "professional": {
            "path": str(professional_path),
            "columns": {
              "subject_id": "bene_key",
              "icd10_code": "dx_code",
              "claim_id": "claim_id",
              "procedure_code": "procedure_code",
            },
          },
        },
      },
    ),
    encoding="utf-8",
  )
  output_dir = tmp_path / "prepared"

  exit_code = main(
    [
      "prepare-source",
      "--source-manifest",
      str(manifest_path),
      "--output-dir",
      str(output_dir),
    ],
  )

  assert exit_code == 0
  expected_outputs = (
    output_dir / "prepared_subjects.csv",
    output_dir / "prepared_diagnoses.csv",
    output_dir / "rejected_diagnosis_candidates.csv",
    output_dir / "source_lineage.csv",
    output_dir / "preparation_issues.csv",
  )
  for path in expected_outputs:
    assert path.exists()


def test_cli_prepare_source_reports_missing_manifest(
  tmp_path: Path,
  capsys: pytest.CaptureFixture[str],
) -> None:
  exit_code = main(
    [
      "prepare-source",
      "--source-manifest",
      str(tmp_path / "missing.json"),
      "--output-dir",
      str(tmp_path / "out"),
    ],
  )

  captured = capsys.readouterr()
  assert exit_code == 1
  assert "missing_source_manifest" in captured.err


def test_cli_prepare_source_rejects_non_object_manifest(
  tmp_path: Path,
  capsys: pytest.CaptureFixture[str],
) -> None:
  manifest_path = tmp_path / "source_manifest.json"
  manifest_path.write_text('["not-an-object"]', encoding="utf-8")

  exit_code = main(
    [
      "prepare-source",
      "--source-manifest",
      str(manifest_path),
      "--output-dir",
      str(tmp_path / "out"),
    ],
  )

  captured = capsys.readouterr()
  assert exit_code == 1
  assert "invalid_source_manifest" in captured.err


def test_cli_prepare_source_rejects_invalid_source_kind(
  tmp_path: Path,
  capsys: pytest.CaptureFixture[str],
) -> None:
  manifest_path = tmp_path / "source_manifest.json"
  manifest_path.write_text(
    json.dumps(
      {
        "source_profile": "cms_purchased_files_ffs_2026",
        "source_kind": "api",
        "sources": {
          "subject": {
            "path": "subjects.csv",
            "columns": {"subject_id": "id"},
          },
        },
      },
    ),
    encoding="utf-8",
  )

  exit_code = main(
    [
      "prepare-source",
      "--source-manifest",
      str(manifest_path),
      "--output-dir",
      str(tmp_path / "out"),
    ],
  )

  captured = capsys.readouterr()
  assert exit_code == 1
  assert "invalid_source_kind" in captured.err


@pytest.mark.parametrize("command", ("prepare-source", "score-source"))
def test_cli_source_workflows_reject_non_cms_model_versions(
  tmp_path: Path,
  command: str,
) -> None:
  subjects_path = tmp_path / "subjects_raw.csv"
  professional_path = tmp_path / "professional_raw.csv"
  subjects_path.write_text(
    "bene_key,birth_dt,sex_cd,orec_cd,ltimcaid_cd,nemcaid_cd\n100,01/21/1950,1,0,1,0\n",
    encoding="utf-8",
  )
  professional_path.write_text(
    "bene_key,dx_code,claim_id,procedure_code\n100,A0104,prof-1,C1062\n",
    encoding="utf-8",
  )
  manifest_path = tmp_path / "source_manifest.json"
  manifest_path.write_text(
    json.dumps(
      {
        "source_profile": "cms_purchased_files_ffs_2026",
        "source_kind": "flat-file",
        "sources": {
          "subject": {
            "path": str(subjects_path),
            "columns": {
              "subject_id": "bene_key",
              "date_of_birth": "birth_dt",
              "sex": "sex_cd",
              "original_reason_entitlement_code": "orec_cd",
              "limited_income_medicaid_flag": "ltimcaid_cd",
              "new_enrollee_medicaid_flag": "nemcaid_cd",
            },
          },
          "professional": {
            "path": str(professional_path),
            "columns": {
              "subject_id": "bene_key",
              "icd10_code": "dx_code",
              "claim_id": "claim_id",
              "procedure_code": "procedure_code",
            },
          },
        },
      },
    ),
    encoding="utf-8",
  )
  output_dir = tmp_path / f"{command}-out"

  exit_code = main(
    [
      command,
      "--source-manifest",
      str(manifest_path),
      "--output-dir",
      str(output_dir),
      "--model-version",
      "rxhcc_v8_t_2026",
    ],
  )

  assert exit_code == 1
  assert not output_dir.exists()


def test_cli_explain_subject_writes_expected_artifacts(tmp_path: Path) -> None:
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
  output_dir = tmp_path / "explain"

  exit_code = main(
    [
      "explain-subject",
      "--subjects",
      str(subjects_path),
      "--diagnoses",
      str(diagnoses_path),
      "--subject-id",
      "100",
      "--output-dir",
      str(output_dir),
    ],
  )

  assert exit_code == 0
  expected_outputs = (
    output_dir / "subject_summary.csv",
    output_dir / "subject_predictors.csv",
    output_dir / "diagnosis_mappings.csv",
    output_dir / "hierarchy_effects.csv",
    output_dir / "interaction_details.csv",
    output_dir / "score_contributions.csv",
    output_dir / "subject_scores.csv",
    output_dir / "raf_totals.csv",
    output_dir / "validation_issues.csv",
  )
  for path in expected_outputs:
    assert path.exists()


def test_cli_tui_reports_missing_optional_dependency(
  monkeypatch: pytest.MonkeyPatch,
  capsys: pytest.CaptureFixture[str],
) -> None:
  error = ModuleNotFoundError("No module named 'textual'")
  error.name = "textual"

  def _raise_missing_dependency() -> object:
    raise error

  monkeypatch.setattr(cli, "_import_tui_runner", _raise_missing_dependency)

  exit_code = main(["tui"])

  captured = capsys.readouterr()
  assert exit_code == 1
  assert "bundled Textual frontend" in captured.err
  assert "uv sync --group dev" in captured.err


def test_cli_gui_reports_missing_optional_dependency(
  monkeypatch: pytest.MonkeyPatch,
  capsys: pytest.CaptureFixture[str],
) -> None:
  error = ModuleNotFoundError("No module named 'streamlit'")
  error.name = "streamlit"

  def _raise_missing_dependency() -> None:
    raise error

  monkeypatch.setattr(cli, "_import_gui_runner", _raise_missing_dependency)

  exit_code = main(["gui"])

  captured = capsys.readouterr()
  assert exit_code == 1
  assert "bundled Streamlit frontend" in captured.err
  assert "uv sync --group dev" in captured.err
