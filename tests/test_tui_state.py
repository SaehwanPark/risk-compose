from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from risk_compose._artifact_io import write_artifact_csv
from risk_compose.core import explain_subject_raf, score_subjects
from risk_compose.review import build_artifact_view
from risk_compose.tui.bundle_loader import load_bundle_directory
from risk_compose.tui.session import (
  build_bundle_session,
  build_explain_session,
  build_score_session,
  filter_artifact_by_subject,
)
from risk_compose.types import SubjectRecord, DiagnosisRecord, ScoringOptions, ScoringRequest, TableArtifact


def _build_request() -> ScoringRequest:
  return ScoringRequest(
    subjects=(
      SubjectRecord(
        subject_id="100",
        date_of_birth=date(1950, 1, 21),
        sex=1,
        original_reason_entitlement_code=0,
        limited_income_medicaid_flag=1,
        new_enrollee_medicaid_flag=0,
      ),
    ),
    diagnoses=(
      DiagnosisRecord("100", "A0104"),
    ),
    options=ScoringOptions(model_version="cms_hcc_v28_2026"),
  )


def test_build_score_session_summarizes_artifacts() -> None:
  result = score_subjects(_build_request())

  session = build_score_session(
    result,
    source_paths={
      "subjects": Path("subjects.csv"),
      "diagnoses": Path("diagnoses.csv"),
    },
  )

  assert session.summary.model_version == "cms_hcc_v28_2026"
  assert session.summary.subject_count == 1
  assert session.summary.diagnosis_count == 1
  assert session.selected_subject_id == "100"
  assert session.summary.artifact_row_counts["subject_scores"] == 1


def test_build_explain_session_summarizes_artifacts() -> None:
  request = _build_request()
  result = explain_subject_raf(
    request.subjects[0],
    request.diagnoses,
    options=request.options,
  )

  session = build_explain_session(
    result,
    source_paths={
      "subjects": Path("subjects.csv"),
      "diagnoses": Path("diagnoses.csv"),
    },
  )

  assert session.summary.model_version == "cms_hcc_v28_2026"
  assert session.summary.subject_count == 1
  assert session.summary.artifact_row_counts["subject_summary"] == 1
  assert session.selected_subject_id == "100"


def test_filter_artifact_by_subject_filters_subject_aware_rows() -> None:
  artifact = TableArtifact(
    name="subject_scores",
    columns=("subject_id", "score"),
    rows=(
      {"subject_id": "100", "score": 1.0},
      {"subject_id": "200", "score": 2.0},
    ),
  )

  filtered = filter_artifact_by_subject(artifact, "200")

  assert filtered.rows == ({"subject_id": "200", "score": 2.0},)


def test_build_artifact_view_filters_and_paginates_rows() -> None:
  session = build_bundle_session(
    bundle_kind="score",
    bundle_dir=Path("score-bundle"),
    artifacts={
      "subject_scores": TableArtifact(
        name="subject_scores",
        columns=("subject_id", "score"),
        rows=tuple(
          {
            "subject_id": "100" if row_number < 28 else "200",
            "score": row_number,
          }
          for row_number in range(30)
        ),
      ),
      "subject_predictors": TableArtifact.empty("subject_predictors", ("subject_id",)),
      "diagnosis_mappings": TableArtifact.empty("diagnosis_mappings", ("subject_id",)),
      "score_contributions": TableArtifact.empty("score_contributions", ("subject_id",)),
      "validation_issues": TableArtifact.empty("validation_issues", ("subject_id",)),
    },
  )

  view = build_artifact_view(
    session,
    "subject_scores",
    subject_id="100",
    search_query="2",
    page=1,
    page_size=2,
  )

  assert view.filtered_row_count == 10
  assert view.page_count == 5
  assert len(view.page_rows) == 2
  assert view.page_rows[0]["score"] == 2


def test_load_bundle_directory_loads_score_bundle(tmp_path: Path) -> None:
  session = build_score_session(
    score_subjects(_build_request()),
    source_paths={
      "subjects": Path("subjects.csv"),
      "diagnoses": Path("diagnoses.csv"),
    },
  )
  bundle_dir = tmp_path / "score-bundle"
  bundle_dir.mkdir()
  for artifact_name, artifact in session.artifacts.items():
    write_artifact_csv(bundle_dir / f"{artifact_name}.csv", artifact)

  loaded_bundle = load_bundle_directory(bundle_dir)
  bundle_session = build_bundle_session(
    bundle_kind=loaded_bundle.bundle_kind,
    bundle_dir=loaded_bundle.bundle_dir,
    artifacts=loaded_bundle.artifacts,
  )

  assert loaded_bundle.bundle_kind == "score"
  assert bundle_session.kind == "bundle_score"
  assert bundle_session.summary.artifact_row_counts["subject_scores"] == 1


def test_load_bundle_directory_loads_explain_bundle(tmp_path: Path) -> None:
  request = _build_request()
  explain_session = build_explain_session(
    explain_subject_raf(
      request.subjects[0],
      request.diagnoses,
      options=request.options,
    ),
    source_paths={
      "subjects": Path("subjects.csv"),
      "diagnoses": Path("diagnoses.csv"),
    },
  )
  bundle_dir = tmp_path / "explain-bundle"
  bundle_dir.mkdir()
  for artifact_name, artifact in explain_session.artifacts.items():
    write_artifact_csv(bundle_dir / f"{artifact_name}.csv", artifact)

  loaded_bundle = load_bundle_directory(bundle_dir)

  assert loaded_bundle.bundle_kind == "explain"
  assert loaded_bundle.artifacts["subject_summary"].rows


def test_load_bundle_directory_rejects_incomplete_bundle(tmp_path: Path) -> None:
  write_artifact_csv(
    tmp_path / "subject_scores.csv",
    TableArtifact(
      name="subject_scores",
      columns=("subject_id", "model_version"),
      rows=({"subject_id": "100", "model_version": "cms_hcc_v28_2026"},),
    ),
  )

  with pytest.raises(ValueError, match="Missing score files"):
    load_bundle_directory(tmp_path)
