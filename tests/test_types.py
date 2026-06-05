from __future__ import annotations

from datetime import date
from typing import cast

from risk_compose.types import (
  SubjectExplainResult,
  SubjectRecord,
  DatabaseTableSpec,
  DatabaseSourceSpec,
  DiagnosisRecord,
  FlatFileTableSpec,
  FlatFileSourceSpec,
  PreparedScoringInputs,
  ScoringOptions,
  ScoringRequest,
  SourcePreparationRequest,
  TableArtifact,
)


def test_scoring_request_coerces_iterables_to_tuples() -> None:
  request = ScoringRequest(
    subjects=cast(
      tuple[SubjectRecord, ...],
      [
      SubjectRecord(
        subject_id="1",
        date_of_birth=date(1950, 1, 1),
        sex=1,
        original_reason_entitlement_code=0,
      ),
      ],
    ),
    diagnoses=cast(
      tuple[DiagnosisRecord, ...],
      [
      DiagnosisRecord(
        subject_id="1",
        icd10_code="A0104",
      ),
      ],
    ),
    options=ScoringOptions(),
  )
  assert isinstance(request.subjects, tuple)
  assert isinstance(request.diagnoses, tuple)


def test_table_artifact_empty_preserves_schema() -> None:
  artifact = TableArtifact.empty("subject_scores", ("subject_id", "score_ne"))
  assert artifact.name == "subject_scores"
  assert artifact.columns == ("subject_id", "score_ne")
  assert artifact.rows == ()


def test_source_and_explain_types_construct_cleanly() -> None:
  source_request = SourcePreparationRequest(
    source_spec=DatabaseSourceSpec(
      source_profile="ccw_vrdc_ffs_2026",
      sources={
        "subject": DatabaseTableSpec(
          locator="mbsf_base",
          columns={
            "subject_id": "BENE_ID",
            "date_of_birth": "BENE_BIRTH_DT",
            "sex": "SEX_IDENT_CD",
            "original_reason_entitlement_code": "BENE_ENTLMT_RSN_CURR",
          },
        ),
        "professional": DatabaseTableSpec(
          locator="carrier_ffs",
          columns={
            "subject_id": "BENE_ID",
            "icd10_code": "LINE_ICD_DGNS_CD",
            "procedure_code": "HCPCS_CD",
          },
        ),
      },
    ),
  )
  prepared_inputs = PreparedScoringInputs(
    scoring_request=ScoringRequest(subjects=(), diagnoses=(), options=ScoringOptions()),
    prepared_subjects=TableArtifact.empty("prepared_subjects", ("subject_id",)),
    prepared_diagnoses=TableArtifact.empty("prepared_diagnoses", ("subject_id", "icd10_code")),
    rejected_diagnosis_candidates=TableArtifact.empty(
      "rejected_diagnosis_candidates",
      ("subject_id", "rejection_code"),
    ),
    source_lineage=TableArtifact.empty("source_lineage", ("source_profile",)),
  )
  explain_result = SubjectExplainResult(
    model_spec=None,  # type: ignore[arg-type]
    subject_summary=TableArtifact.empty("subject_summary", ("subject_id",)),
    subject_predictors=TableArtifact.empty("subject_predictors", ("subject_id",)),
    diagnosis_mappings=TableArtifact.empty("diagnosis_mappings", ("subject_id",)),
    hierarchy_effects=TableArtifact.empty("hierarchy_effects", ("subject_id",)),
    interaction_details=TableArtifact.empty("interaction_details", ("subject_id",)),
    score_contributions=TableArtifact.empty("score_contributions", ("subject_id",)),
    subject_scores=TableArtifact.empty("subject_scores", ("subject_id",)),
    raf_totals=TableArtifact.empty("raf_totals", ("subject_id",)),
  )
  assert isinstance(source_request.source_spec, DatabaseSourceSpec)
  assert prepared_inputs.prepared_subjects.name == "prepared_subjects"
  assert prepared_inputs.rejected_diagnosis_candidates.name == "rejected_diagnosis_candidates"
  assert explain_result.raf_totals.name == "raf_totals"
