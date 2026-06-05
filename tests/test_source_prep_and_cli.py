from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

import pytest

import risk_compose.cli as cli
from risk_compose.registry import get_model_spec
from risk_compose.source_prep import (
  PREPARED_BENEFICIARY_COLUMNS,
  PREPARED_DIAGNOSIS_COLUMNS,
  REJECTED_DIAGNOSIS_COLUMNS,
  SOURCE_LINEAGE_COLUMNS,
)
from risk_compose.core import prepare_scoring_inputs
from risk_compose.types import (
  SubjectRecord,
  FlatFileSourceSpec,
  FlatFileTableSpec,
  PredictorArtifacts,
  PreparedScoringInputs,
  ScoreArtifacts,
  ScoringOptions,
  ScoringRequest,
  ScoringResult,
  SourcePreparationRequest,
  TableArtifact,
  ValidationIssue,
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
  with path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)


def test_prepare_scoring_inputs_applies_prefilters_before_candidate_rules(tmp_path: Path) -> None:
  subject_path = tmp_path / "subjects.csv"
  professional_path = tmp_path / "professional.csv"
  _write_csv(
    subject_path,
    [
      {
        "id": "B1",
        "dob": "1950-01-01",
        "sex": 1,
        "orec": 0,
      },
    ],
  )
  _write_csv(
    professional_path,
    [
      {
        "id": "B1",
        "icd10": "E119",
        "hcpcs_code": "99213",
        "provider_type": "office",
        "telehealth_flag": 0,
        "audio_only_flag": 0,
        "keep_row": 1,
      },
      {
        "id": "B1",
        "icd10": "I509",
        "hcpcs_code": "99213",
        "provider_type": "office",
        "telehealth_flag": 0,
        "audio_only_flag": 0,
        "keep_row": 0,
      },
      {
        "id": "B1",
        "icd10": "J449",
        "hcpcs_code": "99213",
        "provider_type": "diagnostic_radiology",
        "telehealth_flag": 0,
        "audio_only_flag": 0,
        "keep_row": 1,
      },
    ],
  )

  prepared = prepare_scoring_inputs(
    SourcePreparationRequest(
      source_spec=FlatFileSourceSpec(
        source_profile="cms_purchased_files_ffs_2026",
        sources={
          "subject": FlatFileTableSpec(path=subject_path),
          "professional": FlatFileTableSpec(path=professional_path, filter="keep_row = 1"),
        },
      ),
    ),
  )

  assert prepared.preparation_issues == ()
  assert [row["icd10_code"] for row in prepared.prepared_diagnoses.rows] == ["E119"]
  assert [row["rejection_code"] for row in prepared.rejected_diagnosis_candidates.rows] == [
    "diagnostic_radiology_excluded",
  ]
  assert all(row["icd10_code"] != "I509" for row in prepared.prepared_diagnoses.rows)
  assert all(row["icd10_code"] != "I509" for row in prepared.rejected_diagnosis_candidates.rows)
  assert any(
    row["source_role"] == "professional" and row["source_filter"] == "keep_row = 1"
    for row in prepared.source_lineage.rows
  )


def test_prepare_scoring_inputs_blocks_missing_profile_owned_eligibility_fields(
  tmp_path: Path,
) -> None:
  subject_path = tmp_path / "subjects.csv"
  professional_path = tmp_path / "professional_missing_fields.csv"
  _write_csv(
    subject_path,
    [
      {
        "id": "B1",
        "dob": "1950-01-01",
        "sex": 1,
        "orec": 0,
      },
    ],
  )
  _write_csv(
    professional_path,
    [
      {
        "id": "B1",
        "icd10": "E119",
        "hcpcs_code": "99213",
      },
    ],
  )

  prepared = prepare_scoring_inputs(
    SourcePreparationRequest(
      source_spec=FlatFileSourceSpec(
        source_profile="cms_purchased_files_ffs_2026",
        sources={
          "subject": FlatFileTableSpec(path=subject_path),
          "professional": FlatFileTableSpec(path=professional_path),
        },
      ),
    ),
  )

  assert prepared.prepared_subjects.rows == ()
  assert prepared.prepared_diagnoses.rows == ()
  assert any(
    issue.code == "missing_professional_eligibility_mappings"
    for issue in prepared.preparation_issues
  )


def test_run_score_source_command_prepares_once_and_merges_validation_issues(
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
) -> None:
  model_spec = get_model_spec()
  scoring_request = ScoringRequest(
    subjects=(
      SubjectRecord(
        subject_id="B1",
        date_of_birth=date(1950, 1, 1),
        sex=1,
        original_reason_entitlement_code=0,
      ),
    ),
    diagnoses=(),
  )
  prepared_inputs = PreparedScoringInputs(
    scoring_request=scoring_request,
    prepared_subjects=TableArtifact(
      name="prepared_subjects",
      columns=PREPARED_BENEFICIARY_COLUMNS,
      rows=(
        {
          "subject_id": "B1",
          "date_of_birth": date(1950, 1, 1),
          "sex": 1,
          "original_reason_entitlement_code": 0,
          "limited_income_medicaid_flag": None,
          "new_enrollee_medicaid_flag": None,
        },
      ),
    ),
    prepared_diagnoses=TableArtifact.empty("prepared_diagnoses", PREPARED_DIAGNOSIS_COLUMNS),
    rejected_diagnosis_candidates=TableArtifact.empty(
      "rejected_diagnosis_candidates",
      REJECTED_DIAGNOSIS_COLUMNS,
    ),
    source_lineage=TableArtifact.empty("source_lineage", SOURCE_LINEAGE_COLUMNS),
    preparation_issues=(
      ValidationIssue(
        severity="warning",
        code="prep_warning",
        message="Preparation warning",
      ),
    ),
  )
  scoring_result = ScoringResult(
    model_spec=model_spec,
    predictors=PredictorArtifacts(
      model_spec=model_spec,
      subject_predictors=TableArtifact(
        name="subject_predictors",
        columns=("subject_id",),
        rows=({"subject_id": "B1"},),
      ),
      diagnosis_mappings=TableArtifact.empty(
        "diagnosis_mappings",
        ("subject_id", "icd10_code"),
      ),
    ),
    scores=ScoreArtifacts(
      model_spec=model_spec,
      subject_scores=TableArtifact(
        name="subject_scores",
        columns=("subject_id", "model_version", "score_community_na"),
        rows=(({"subject_id": "B1", "model_version": model_spec.version_id, "score_community_na": 0.0}),),
      ),
      score_contributions=TableArtifact.empty(
        "score_contributions",
        ("subject_id", "score_family"),
      ),
    ),
    validation_issues=(
      ValidationIssue(
        severity="info",
        code="score_info",
        message="Score info",
      ),
    ),
  )

  call_counts = {"prepare": 0, "score": 0}
  source_request = object()

  def fake_source_request_from_manifest(args: argparse.Namespace) -> object:
    assert args.output_format == "csv"
    return source_request

  def fake_prepare_scoring_inputs(request: object) -> PreparedScoringInputs:
    assert request is source_request
    call_counts["prepare"] += 1
    return prepared_inputs

  def fake_score_subjects(request: ScoringRequest) -> ScoringResult:
    assert request is prepared_inputs.scoring_request
    call_counts["score"] += 1
    return scoring_result

  monkeypatch.setattr(cli, "_source_request_from_manifest", fake_source_request_from_manifest)
  monkeypatch.setattr(cli, "prepare_scoring_inputs", fake_prepare_scoring_inputs)
  monkeypatch.setattr(cli, "score_subjects", fake_score_subjects)

  exit_code = cli._run_score_source_command(
    argparse.Namespace(
      source_manifest="unused.json",
      output_dir=str(tmp_path),
      output_format="csv",
    ),
  )

  assert exit_code == 0
  assert call_counts == {"prepare": 1, "score": 1}

  validation_issue_rows = list(
    csv.DictReader((tmp_path / "validation_issues.csv").open("r", encoding="utf-8")),
  )
  assert [row["code"] for row in validation_issue_rows] == ["prep_warning", "score_info"]


def test_prepare_scoring_inputs_rejects_non_cms_hcc_model_versions(tmp_path: Path) -> None:
  subject_path = tmp_path / "subjects.csv"
  professional_path = tmp_path / "professional.csv"
  _write_csv(
    subject_path,
    [
      {
        "id": "B1",
        "dob": "1950-01-01",
        "sex": 1,
        "orec": 0,
      },
    ],
  )
  _write_csv(
    professional_path,
    [
      {
        "id": "B1",
        "icd10": "E119",
        "hcpcs_code": "99213",
        "provider_type": "office",
        "telehealth_flag": 0,
        "audio_only_flag": 0,
      },
    ],
  )

  prepared = prepare_scoring_inputs(
    SourcePreparationRequest(
      source_spec=FlatFileSourceSpec(
        source_profile="cms_purchased_files_ffs_2026",
        sources={
          "subject": FlatFileTableSpec(path=subject_path),
          "professional": FlatFileTableSpec(path=professional_path),
        },
      ),
      options=ScoringOptions(model_version="esrd_v21_2026"),
    ),
  )

  assert prepared.prepared_subjects.rows == ()
  assert prepared.prepared_diagnoses.rows == ()
  assert any(
    issue.code == "unsupported_source_model_family"
    for issue in prepared.preparation_issues
  )
