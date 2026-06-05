from __future__ import annotations

from datetime import date

from risk_compose.core import explain_subject_raf, generate_predictors, score_subjects
from risk_compose.types import SubjectRecord, DiagnosisRecord, ScoringRequest


def _sample_request() -> ScoringRequest:
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
      DiagnosisRecord(
        subject_id="100",
        icd10_code="A0104",
      ),
    ),
  )


def test_generate_predictors_returns_stable_artifact_shapes() -> None:
  predictors = generate_predictors(_sample_request())
  assert predictors.subject_predictors.name == "subject_predictors"
  assert predictors.diagnosis_mappings.name == "diagnosis_mappings"
  assert "subject_id" in predictors.subject_predictors.columns
  assert "model_version" in predictors.subject_predictors.columns
  assert "mapped_cc_count" in predictors.subject_predictors.columns
  assert "mapping_status" in predictors.diagnosis_mappings.columns


def test_score_subjects_returns_stable_score_columns() -> None:
  result = score_subjects(_sample_request())
  score_columns = result.scores.subject_scores.columns
  assert "subject_id" in score_columns
  assert "model_version" in score_columns
  assert "score_community_na" in score_columns
  assert "score_institutional" in score_columns
  assert "score_ne" in score_columns
  assert "score_ne_snp" in score_columns


def test_explain_subject_raf_returns_structured_lineage_artifacts() -> None:
  request = _sample_request()
  explain_result = explain_subject_raf(
    request.subjects[0],
    request.diagnoses,
    options=request.options,
  )

  assert explain_result.subject_summary.name == "subject_summary"
  assert explain_result.hierarchy_effects.name == "hierarchy_effects"
  assert explain_result.interaction_details.name == "interaction_details"
  assert explain_result.score_contributions.name == "score_contributions"
  assert explain_result.raf_totals.name == "raf_totals"
  assert explain_result.score_contributions.rows
  assert explain_result.raf_totals.rows


def test_explain_subject_raf_matches_single_subject_batch_outputs() -> None:
  request = _sample_request()
  batch_result = score_subjects(request)
  explain_result = explain_subject_raf(
    request.subjects[0],
    request.diagnoses,
    options=request.options,
  )

  assert explain_result.subject_scores.rows == batch_result.scores.subject_scores.rows
  assert explain_result.diagnosis_mappings.rows == batch_result.predictors.diagnosis_mappings.rows
