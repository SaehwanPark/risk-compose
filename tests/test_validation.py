from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from risk_compose.registry import get_model_spec
from risk_compose.types import SubjectRecord, DiagnosisRecord, ScoringOptions, ScoringRequest
from risk_compose.validation import ValidationError, build_request_from_rows, validate_scoring_request


def test_build_request_from_rows_supports_cms_column_aliases() -> None:
  request = build_request_from_rows(
    subject_rows=(
      {
        "ID": "100",
        "DOB": "01/21/1950",
        "SEX": "1",
        "OREC": "0",
        "LTIMCAID": "1",
        "NEMCAID": "0",
        "ESRD": "1",
        "MCAID": "1",
        "FBDual": "1",
        "PBDual": "0",
        "LTI": "1",
      },
    ),
    diagnosis_rows=(
      {
        "ID": "100",
        "ICD10": "A0104",
      },
    ),
  )
  subject = request.subjects[0]
  diagnosis = request.diagnoses[0]
  assert subject.subject_id == "100"
  assert subject.date_of_birth == date(1950, 1, 21)
  assert subject.concurrent_esrd_flag == 1
  assert subject.medicaid_flag == 1
  assert subject.full_benefit_dual_flag == 1
  assert subject.partial_benefit_dual_flag == 0
  assert subject.long_term_institutional_flag == 1
  assert diagnosis.icd10_code == "A0104"


def test_validate_scoring_request_collects_issues_in_non_strict_mode() -> None:
  request = ScoringRequest(
    subjects=(
      SubjectRecord(
        subject_id="100",
        date_of_birth=None,
        sex=9,
        original_reason_entitlement_code=9,
      ),
    ),
    diagnoses=(
      DiagnosisRecord(
        subject_id="404",
        icd10_code="",
      ),
    ),
    options=ScoringOptions(strict_validation=False),
  )
  _, issues = validate_scoring_request(request, get_model_spec())
  codes = {issue.code for issue in issues}
  assert "missing_date_of_birth" in codes
  assert "invalid_sex" in codes
  assert "invalid_orec" in codes
  assert "unknown_diagnosis_subject_id" in codes
  assert "missing_icd10_code" in codes


def test_validate_scoring_request_accumulates_independent_record_issues() -> None:
  request = ScoringRequest(
    subjects=(
      SubjectRecord(
        subject_id="100",
        date_of_birth=date(1950, 1, 21),
        sex=1,
        original_reason_entitlement_code=0,
      ),
      SubjectRecord(
        subject_id="100",
        date_of_birth=None,
        sex=3,
        original_reason_entitlement_code=4,
        limited_income_medicaid_flag=7,
      ),
    ),
    diagnoses=(
      DiagnosisRecord(subject_id="", icd10_code=""),
      DiagnosisRecord(subject_id="404", icd10_code=""),
    ),
  )

  _, issues = validate_scoring_request(request, get_model_spec())
  codes = [issue.code for issue in issues]

  assert codes.count("duplicate_subject_id") == 1
  assert codes.count("missing_date_of_birth") == 1
  assert codes.count("invalid_sex") == 1
  assert codes.count("invalid_orec") == 1
  assert codes.count("invalid_binary_flag") == 1
  assert codes.count("missing_diagnosis_subject_id") == 1
  assert codes.count("unknown_diagnosis_subject_id") == 1
  assert codes.count("missing_icd10_code") == 2


def test_validate_scoring_request_raises_in_strict_mode() -> None:
  request = ScoringRequest(
    subjects=(
      SubjectRecord(
        subject_id="100",
        date_of_birth=None,
        sex=9,
        original_reason_entitlement_code=9,
      ),
    ),
    diagnoses=(),
    options=ScoringOptions(strict_validation=True),
  )
  with pytest.raises(ValidationError, match="Validation failed"):
    validate_scoring_request(request, get_model_spec())


@pytest.mark.parametrize(
  ("model_version", "required_field"),
  (
    ("esrd_v21_2026", "medicaid_flag"),
    ("esrd_v21_2026", "new_enrollee_medicaid_flag"),
    ("esrd_v24_2026", "full_benefit_dual_flag"),
    ("esrd_v24_2026", "partial_benefit_dual_flag"),
    ("esrd_v24_2026", "long_term_institutional_flag"),
    ("rxhcc_v8_t_2026", "concurrent_esrd_flag"),
    ("rxhcc_v8_x_2026", "concurrent_esrd_flag"),
  ),
)
def test_validate_scoring_request_enforces_model_specific_required_fields(
  model_version: str,
  required_field: str,
) -> None:
  subject = SubjectRecord(
    subject_id="100",
    date_of_birth=date(1950, 1, 21),
    sex=1,
    original_reason_entitlement_code=0,
    medicaid_flag=1,
    new_enrollee_medicaid_flag=0,
    full_benefit_dual_flag=1,
    partial_benefit_dual_flag=0,
    long_term_institutional_flag=0,
    concurrent_esrd_flag=1,
  )
  if required_field == "medicaid_flag":
    subject = replace(subject, medicaid_flag=None)
  elif required_field == "new_enrollee_medicaid_flag":
    subject = replace(subject, new_enrollee_medicaid_flag=None)
  elif required_field == "full_benefit_dual_flag":
    subject = replace(subject, full_benefit_dual_flag=None)
  elif required_field == "partial_benefit_dual_flag":
    subject = replace(subject, partial_benefit_dual_flag=None)
  elif required_field == "long_term_institutional_flag":
    subject = replace(subject, long_term_institutional_flag=None)
  else:
    subject = replace(subject, concurrent_esrd_flag=None)
  request = ScoringRequest(
    subjects=(subject,),
    diagnoses=(DiagnosisRecord(subject_id="100", icd10_code="A0104"),),
    options=ScoringOptions(model_version=model_version),
  )

  _, issues = validate_scoring_request(request, get_model_spec(model_version))

  assert any(
    issue.code == "missing_required_model_field" and issue.field_name == required_field
    for issue in issues
  )
