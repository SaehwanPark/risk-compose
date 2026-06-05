from __future__ import annotations

from pathlib import Path

import pytest

from risk_compose.core import score_subjects, score_from_source
from risk_compose.source_prep import prepare_scoring_inputs, validate_source_request
from risk_compose.types import (
  DatabaseSourceSpec,
  DatabaseTableSpec,
  FlatFileSourceSpec,
  FlatFileTableSpec,
  ScoringOptions,
  SourcePreparationRequest,
)
from risk_compose.validation import ValidationError, build_request_from_rows


def test_prepare_scoring_inputs_accepts_candidate_roles_and_rejects_noncandidate_roles(
  tmp_path: Path,
) -> None:
  subjects_path = _write_csv(
    tmp_path / "subjects.csv",
    "bene_key,birth_dt,sex_cd,orec_cd,ltimcaid_cd,nemcaid_cd\n100,01/21/1950,1,0,1,0\n",
  )
  professional_path = _write_csv(
    tmp_path / "professional.csv",
    "bene_key,dx_code,claim_id,procedure_code,provider_type,telehealth_service,audio_only\n100,A0104,prof-1,C1062,,0,0\n",
  )
  dme_path = _write_csv(
    tmp_path / "dme.csv",
    "bene_key,dx_code,claim_id\n100,E119,dme-1\n",
  )

  prepared_inputs = prepare_scoring_inputs(
    SourcePreparationRequest(
      source_spec=FlatFileSourceSpec(
        source_profile="cms_purchased_files_ffs_2026",
        sources={
          "subject": FlatFileTableSpec(subjects_path, columns=_subject_mapping()),
          "professional": FlatFileTableSpec(professional_path, columns=_professional_mapping()),
          "dme": FlatFileTableSpec(dme_path, columns=_noncandidate_mapping()),
        },
      ),
    ),
  )

  assert prepared_inputs.prepared_subjects.name == "prepared_subjects"
  assert prepared_inputs.prepared_diagnoses.rows == (
    {
      "subject_id": "100",
      "icd10_code": "A0104",
      "service_date": None,
      "claim_id": "prof-1",
      "source": str(professional_path),
      "source_role": "professional",
      "acceptance_status": "accepted",
      "acceptance_reason": "eligible_professional_claim",
    },
  )
  assert {row["source_role"] for row in prepared_inputs.rejected_diagnosis_candidates.rows} == {"dme"}
  assert {row["rejection_code"] for row in prepared_inputs.rejected_diagnosis_candidates.rows} == {
    "non_candidate_source_role",
  }
  assert any(
    row["source_role"] == "professional" and row["canonical_field"] == "procedure_code"
    for row in prepared_inputs.source_lineage.rows
  )


def test_validate_source_request_accepts_database_source_spec() -> None:
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

  _, issues = validate_source_request(source_request)

  assert issues == ()


def test_validate_source_request_rejects_unsupported_source_profile_and_role(tmp_path: Path) -> None:
  subjects_path = _write_csv(tmp_path / "subjects.csv", "id,dob,sex,orec\n")
  lab_path = _write_csv(tmp_path / "lab.csv", "id,icd10_code\n")
  source_request = SourcePreparationRequest(
    source_spec=FlatFileSourceSpec(
      source_profile="unsupported_profile",
      sources={
        "subject": FlatFileTableSpec(subjects_path),
        "lab": FlatFileTableSpec(lab_path),
      },
    ),
  )

  _, issues = validate_source_request(source_request)

  assert {issue.code for issue in issues} >= {"unsupported_source_profile", "unsupported_source_role"}


def test_validate_source_request_accumulates_independent_source_issues(tmp_path: Path) -> None:
  missing_professional_path = tmp_path / "missing-professional.csv"
  source_request = SourcePreparationRequest(
    source_spec=FlatFileSourceSpec(
      source_profile="unsupported_profile",
      sources={
        "lab": FlatFileTableSpec(missing_professional_path),
      },
      file_format="parquet",
    ),
    options=ScoringOptions(model_version="esrd_v21_2026"),
  )

  _, issues = validate_source_request(source_request)
  codes = [issue.code for issue in issues]

  assert "unsupported_source_model_family" in codes
  assert "unsupported_source_profile" in codes
  assert "unsupported_source_role" in codes
  assert "missing_subject_source" in codes
  assert "missing_candidate_source_role" in codes
  assert "unsupported_source_file_format" in codes
  assert "missing_source_file" in codes


def test_validate_source_request_rejects_missing_database_mappings_in_strict_mode() -> None:
  source_request = SourcePreparationRequest(
    source_spec=DatabaseSourceSpec(
      source_profile="ccw_vrdc_ffs_2026",
      sources={
        "subject": DatabaseTableSpec(
          locator="mbsf_base",
          columns={"subject_id": "BENE_ID"},
        ),
        "professional": DatabaseTableSpec(
          locator="carrier_ffs",
          columns={"subject_id": "BENE_ID"},
        ),
      },
    ),
    options=source_request_options(strict_validation=True),
  )

  with pytest.raises(ValidationError, match="Validation failed"):
    validate_source_request(source_request)


def test_validate_source_request_requires_candidate_role(tmp_path: Path) -> None:
  subjects_path = _write_csv(
    tmp_path / "subjects.csv",
    "bene_key,birth_dt,sex_cd,orec_cd\n100,01/21/1950,1,0\n",
  )
  dme_path = _write_csv(tmp_path / "dme.csv", "bene_key,dx_code\n100,E119\n")
  source_request = SourcePreparationRequest(
    source_spec=FlatFileSourceSpec(
      source_profile="cms_purchased_files_ffs_2026",
      sources={
        "subject": FlatFileTableSpec(subjects_path, columns=_subject_mapping()),
        "dme": FlatFileTableSpec(dme_path, columns=_noncandidate_mapping()),
      },
    ),
  )

  _, issues = validate_source_request(source_request)

  assert {issue.code for issue in issues} >= {"missing_candidate_source_role"}


def test_source_prefilters_apply_before_candidate_eligibility_rules(tmp_path: Path) -> None:
  subjects_path = _write_csv(
    tmp_path / "subjects.csv",
    "bene_key,birth_dt,sex_cd,orec_cd\n100,01/21/1950,1,0\n",
  )
  professional_path = _write_csv(
    tmp_path / "professional.csv",
    (
      "bene_key,dx_code,claim_id,procedure_code,provider_type,telehealth_service,audio_only\n"
      "100,A0104,prof-1,ZZZZ1,,0,0\n"
    ),
  )

  prepared_inputs = prepare_scoring_inputs(
    SourcePreparationRequest(
      source_spec=FlatFileSourceSpec(
        source_profile="cms_purchased_files_ffs_2026",
        sources={
          "subject": FlatFileTableSpec(subjects_path, columns=_subject_mapping()),
          "professional": FlatFileTableSpec(
            professional_path,
            columns=_professional_mapping(),
            filter="procedure_code = 'C1062'",
          ),
        },
      ),
    ),
  )

  assert prepared_inputs.prepared_diagnoses.rows == ()
  assert prepared_inputs.rejected_diagnosis_candidates.rows == ()
  assert any(
    row["source_role"] == "professional" and row["source_field"] == "procedure_code"
    for row in prepared_inputs.source_lineage.rows
  )


def test_prepare_scoring_inputs_applies_scaffolded_filtering_rules(tmp_path: Path) -> None:
  subjects_path = _write_csv(
    tmp_path / "subjects.csv",
    "bene_key,birth_dt,sex_cd,orec_cd\n100,01/21/1950,1,0\n",
  )
  inpatient_path = _write_csv(
    tmp_path / "inpatient.csv",
    "bene_key,dx_code,claim_id,bill_type\n100,A0104,ip-1,111\n",
  )
  outpatient_path = _write_csv(
    tmp_path / "outpatient.csv",
    (
      "bene_key,dx_code,claim_id,bill_type,procedure_code,provider_type,telehealth_service,audio_only\n"
      "100,E119,op-1,131,C1062,,0,0\n"
    ),
  )
  professional_path = _write_csv(
    tmp_path / "professional.csv",
    (
      "bene_key,dx_code,claim_id,procedure_code,provider_type,telehealth_service,audio_only\n"
      "100,J440,prof-accept,C1062,,0,0\n"
      "100,F329,prof-audio,C1062,,1,1\n"
      "100,R101,prof-rad,C1062,diagnostic_radiology,0,0\n"
      "100,R5383,prof-bad,ZZZZ1,,0,0\n"
    ),
  )
  hospice_path = _write_csv(
    tmp_path / "hospice.csv",
    "bene_key,dx_code,claim_id\n100,C801,hosp-1\n",
  )

  prepared_inputs = prepare_scoring_inputs(
    SourcePreparationRequest(
      source_spec=FlatFileSourceSpec(
        source_profile="cms_purchased_files_ffs_2026",
        sources={
          "subject": FlatFileTableSpec(subjects_path, columns=_subject_mapping()),
          "hospital_inpatient": FlatFileTableSpec(inpatient_path, columns=_inpatient_mapping()),
          "hospital_outpatient": FlatFileTableSpec(outpatient_path, columns=_outpatient_mapping()),
          "professional": FlatFileTableSpec(professional_path, columns=_professional_filter_mapping()),
          "hospice": FlatFileTableSpec(hospice_path, columns=_noncandidate_mapping()),
        },
      ),
    ),
  )

  accepted_codes = {row["icd10_code"] for row in prepared_inputs.prepared_diagnoses.rows}
  rejection_codes = {row["rejection_code"] for row in prepared_inputs.rejected_diagnosis_candidates.rows}

  assert accepted_codes == {"A0104", "E119", "J440"}
  assert rejection_codes >= {
    "audio_only_telehealth_excluded",
    "diagnostic_radiology_excluded",
    "procedure_code_not_eligible",
    "non_candidate_source_role",
  }


def test_score_from_source_matches_explicit_input_when_canonical_inputs_match(tmp_path: Path) -> None:
  subjects_path = _write_csv(
    tmp_path / "subjects.csv",
    "ID,DOB,SEX,OREC,LTIMCAID,NEMCAID\n100,01/21/1950,1,0,1,0\n",
  )
  professional_path = _write_csv(
    tmp_path / "professional.csv",
    "ID,ICD10,claim_id,procedure_code,provider_type,telehealth_service,audio_only\n100,A0104,prof-1,C1062,,0,0\n",
  )
  source_request = SourcePreparationRequest(
    source_spec=FlatFileSourceSpec(
      source_profile="cms_purchased_files_ffs_2026",
      sources={
        "subject": FlatFileTableSpec(subjects_path),
        "professional": FlatFileTableSpec(professional_path),
      },
    ),
  )

  source_result = score_from_source(source_request)
  explicit_request = build_request_from_rows(
    subject_rows=(
      {"ID": "100", "DOB": "01/21/1950", "SEX": "1", "OREC": "0", "LTIMCAID": "1", "NEMCAID": "0"},
    ),
    diagnosis_rows=(
      {"ID": "100", "ICD10": "A0104", "claim_id": "prof-1", "source": str(professional_path)},
    ),
  )
  explicit_result = score_subjects(explicit_request)

  assert source_result.scores.subject_scores.rows == explicit_result.scores.subject_scores.rows
  assert source_result.predictors.subject_predictors.rows == explicit_result.predictors.subject_predictors.rows


def test_score_from_source_rejects_non_cms_model_versions(tmp_path: Path) -> None:
  subjects_path = _write_csv(
    tmp_path / "subjects.csv",
    "ID,DOB,SEX,OREC,LTIMCAID,NEMCAID\n100,01/21/1950,1,0,1,0\n",
  )
  professional_path = _write_csv(
    tmp_path / "professional.csv",
    "ID,ICD10,claim_id,procedure_code,provider_type,telehealth_service,audio_only\n100,A0104,prof-1,C1062,,0,0\n",
  )
  source_request = SourcePreparationRequest(
    source_spec=FlatFileSourceSpec(
      source_profile="cms_purchased_files_ffs_2026",
      sources={
        "subject": FlatFileTableSpec(subjects_path),
        "professional": FlatFileTableSpec(professional_path),
      },
    ),
    options=ScoringOptions(model_version="esrd_v21_2026"),
  )

  with pytest.raises(ValidationError, match="unsupported_source_model_family"):
    score_from_source(source_request)


def _write_csv(path: Path, content: str) -> Path:
  path.write_text(content, encoding="utf-8")
  return path


def _subject_mapping() -> dict[str, str]:
  return {
    "subject_id": "bene_key",
    "date_of_birth": "birth_dt",
    "sex": "sex_cd",
    "original_reason_entitlement_code": "orec_cd",
    "limited_income_medicaid_flag": "ltimcaid_cd",
    "new_enrollee_medicaid_flag": "nemcaid_cd",
  }


def _professional_mapping() -> dict[str, str]:
  return {
    "subject_id": "bene_key",
    "icd10_code": "dx_code",
    "claim_id": "claim_id",
    "procedure_code": "procedure_code",
    "provider_type": "provider_type",
    "telehealth_service": "telehealth_service",
    "audio_only": "audio_only",
  }


def _professional_filter_mapping() -> dict[str, str]:
  return _professional_mapping()


def _inpatient_mapping() -> dict[str, str]:
  return {
    "subject_id": "bene_key",
    "icd10_code": "dx_code",
    "claim_id": "claim_id",
    "bill_type": "bill_type",
  }


def _outpatient_mapping() -> dict[str, str]:
  return {
    "subject_id": "bene_key",
    "icd10_code": "dx_code",
    "claim_id": "claim_id",
    "bill_type": "bill_type",
    "procedure_code": "procedure_code",
    "provider_type": "provider_type",
    "telehealth_service": "telehealth_service",
    "audio_only": "audio_only",
  }


def _noncandidate_mapping() -> dict[str, str]:
  return {
    "subject_id": "bene_key",
    "icd10_code": "dx_code",
    "claim_id": "claim_id",
  }


def source_request_options(*, strict_validation: bool) -> ScoringOptions:
  from risk_compose.types import ScoringOptions

  return ScoringOptions(strict_validation=strict_validation)
