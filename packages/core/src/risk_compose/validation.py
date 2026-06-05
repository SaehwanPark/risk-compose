"""Request construction, alias resolution, and validation helpers."""

from __future__ import annotations

from collections.abc import Generator, Iterable, Mapping, Sequence
from typing import TypeVar

from comp_builders import Invalid, Valid, Validation, validation

from risk_compose._schemas import SubjectRowSchema, DiagnosisRowSchema
from risk_compose._typing import InputRowMapping
from risk_compose.types import (
  SubjectRecord,
  DiagnosisRecord,
  ModelSpec,
  ScoringOptions,
  ScoringRequest,
  ValidationIssue,
)

SUBJECT_COLUMN_ALIASES = {
  "subject_id": ("subject_id", "beneficiary_id", "patient_id", "case_id", "id"),
  "date_of_birth": ("date_of_birth", "dob"),
  "sex": ("sex",),
  "original_reason_entitlement_code": (
    "original_reason_entitlement_code",
    "orec",
  ),
  "limited_income_medicaid_flag": (
    "limited_income_medicaid_flag",
    "ltimcaid",
  ),
  "new_enrollee_medicaid_flag": (
    "new_enrollee_medicaid_flag",
    "nemcaid",
  ),
  "concurrent_esrd_flag": (
    "concurrent_esrd_flag",
    "esrd",
  ),
  "medicaid_flag": (
    "medicaid_flag",
    "mcaid",
  ),
  "full_benefit_dual_flag": (
    "full_benefit_dual_flag",
    "fbdual",
  ),
  "partial_benefit_dual_flag": (
    "partial_benefit_dual_flag",
    "pbdual",
  ),
  "long_term_institutional_flag": (
    "long_term_institutional_flag",
    "lti",
  ),
}

DIAGNOSIS_COLUMN_ALIASES = {
  "subject_id": ("subject_id", "beneficiary_id", "patient_id", "case_id", "id"),
  "icd10_code": ("icd10_code", "icd10"),
  "service_date": ("service_date",),
  "claim_id": ("claim_id",),
  "source": ("source",),
  "diagnosis_sequence": ("diagnosis_sequence", "dx_sequence", "sequence", "seq"),
  "present_on_admission": ("present_on_admission", "poa", "dxpoa"),
}

_VALID_SEX_VALUES = {1, 2}
_VALID_OREC_VALUES = {0, 1, 2, 3}
_VALID_BINARY_VALUES = {0, 1}
_OPTIONAL_BINARY_SUBJECT_FIELDS = (
  "limited_income_medicaid_flag",
  "new_enrollee_medicaid_flag",
  "concurrent_esrd_flag",
  "medicaid_flag",
  "full_benefit_dual_flag",
  "partial_benefit_dual_flag",
  "long_term_institutional_flag",
)


class ValidationError(ValueError):
  """Raised when strict validation is enabled and blocking issues are present."""

  def __init__(self, issues: Sequence[ValidationIssue]) -> None:
    self.issues = tuple(issues)
    super().__init__(self._build_message())

  def _build_message(self) -> str:
    issue_count = len(self.issues)
    preview = "; ".join(f"{issue.code}: {issue.message}" for issue in self.issues[:3])
    return f"Validation failed with {issue_count} blocking issue(s). {preview}"


_ValidationValue = TypeVar("_ValidationValue")


def build_request_from_rows(
  subject_rows: Sequence[InputRowMapping],
  diagnosis_rows: Sequence[InputRowMapping],
  *,
  options: ScoringOptions | None = None,
) -> ScoringRequest:
  """Normalize row-oriented inputs into the canonical typed request model."""
  subject_rows = tuple(subject_rows)
  diagnosis_rows = tuple(diagnosis_rows)
  subject_mapping = resolve_input_columns(
    _collect_columns(subject_rows),
    SUBJECT_COLUMN_ALIASES,
  )
  diagnosis_mapping = resolve_input_columns(
    _collect_columns(diagnosis_rows),
    DIAGNOSIS_COLUMN_ALIASES,
  )
  return ScoringRequest(
    subjects=tuple(
      _build_subject_record(row, subject_mapping) for row in subject_rows
    ),
    diagnoses=tuple(
      _build_diagnosis_record(row, diagnosis_mapping) for row in diagnosis_rows
    ),
    options=options or ScoringOptions(),
  )


def resolve_input_columns(
  columns: Iterable[str],
  aliases: Mapping[str, tuple[str, ...]],
) -> dict[str, str]:
  """Resolve canonical field names to source columns using case-insensitive aliases."""
  normalized_columns = {column.strip().lower(): column for column in columns}
  resolved = {}
  for canonical_name, candidates in aliases.items():
    for candidate in candidates:
      original_name = normalized_columns.get(candidate.lower())
      if original_name is not None:
        resolved[canonical_name] = original_name
        break
  return resolved


def validate_scoring_request(
  request: ScoringRequest,
  model_spec: ModelSpec,
) -> tuple[ScoringRequest, tuple[ValidationIssue, ...]]:
  """Validate a scoring request and return collected issues."""
  validated_request, issues = _unwrap_validation_result(
    _validate_scoring_request(request, model_spec),
    fallback=request,
  )

  if request.options.strict_validation:
    enforce_strict_validation(issues)

  return validated_request, issues


def _unwrap_validation_result(
  validation_result: Validation[_ValidationValue, ValidationIssue],
  *,
  fallback: _ValidationValue,
) -> tuple[_ValidationValue, tuple[ValidationIssue, ...]]:
  """Return an explicit value-plus-issues pair from a validation result."""
  if isinstance(validation_result, Valid):
    return validation_result.value, ()
  if isinstance(validation_result, Invalid):
    return fallback, validation_result.errors
  return fallback, ()


def enforce_strict_validation(issues: Sequence[ValidationIssue]) -> None:
  """Raise a validation error when blocking issues are present."""
  blocking_issues = tuple(issue for issue in issues if issue.severity == "error")
  if blocking_issues:
    raise ValidationError(blocking_issues)


def _required_subject_fields(model_spec: ModelSpec) -> tuple[str, ...]:
  """Return subject fields that are required for the resolved model."""
  if model_spec.family in {"cms_hcc", "ahrq_elixhauser"}:
    return ()
  if model_spec.version_id == "esrd_v21_2026":
    return ("medicaid_flag", "new_enrollee_medicaid_flag")
  if model_spec.version_id == "esrd_v24_2026":
    return (
      "full_benefit_dual_flag",
      "partial_benefit_dual_flag",
      "long_term_institutional_flag",
    )
  if model_spec.family == "rxhcc":
    return ("concurrent_esrd_flag",)
  return ()


@validation.block
def _validate_scoring_request(
  request: ScoringRequest,
  model_spec: ModelSpec,
) -> Generator[Validation[ScoringRequest, ValidationIssue], object, ScoringRequest]:
  """Compose independent request checks while preserving the request value."""
  subject_ids = _valid_subject_ids(request.subjects)
  yield _validate_request_presence(request)
  yield _validate_subjects(request, model_spec)
  yield _validate_diagnoses(request, subject_ids)
  return request


def _validate_request_presence(request: ScoringRequest) -> Validation[ScoringRequest, ValidationIssue]:
  """Validate request-level empty-input warnings."""
  issues = (
    (() if request.subjects else (_empty_subject_issue(),))
    + (() if request.diagnoses else (_empty_diagnosis_issue(),))
  )
  return _validation_for(request, issues)


def _validate_subjects(
  request: ScoringRequest,
  model_spec: ModelSpec,
) -> Validation[ScoringRequest, ValidationIssue]:
  """Validate subject records and accumulate every independent issue."""
  required_fields = _required_subject_fields(model_spec)
  return _validation_for(
    request,
    _subject_issues(request.subjects, required_fields, model_spec),
  )


def _validate_diagnoses(
  request: ScoringRequest,
  subject_ids: frozenset[str],
) -> Validation[ScoringRequest, ValidationIssue]:
  """Validate diagnosis records against the known subject ids."""
  return _validation_for(
    request,
    (
      issue
      for diagnosis in request.diagnoses
      for issue in _diagnosis_issues(diagnosis, subject_ids)
    ),
  )


def _validation_for(
  value: ScoringRequest,
  issues: Iterable[ValidationIssue],
) -> Validation[ScoringRequest, ValidationIssue]:
  """Return a valid value or accumulated validation issues."""
  collected_issues = tuple(issues)
  if collected_issues:
    return Invalid(collected_issues)
  return Valid(value)


def _valid_subject_ids(subjects: Sequence[SubjectRecord]) -> frozenset[str]:
  """Return non-empty subject ids available to diagnosis validation."""
  return frozenset(
    subject.subject_id.strip()
    for subject in subjects
    if subject.subject_id.strip()
  )


def _subject_issues(
  subjects: Sequence[SubjectRecord],
  required_fields: Sequence[str],
  model_spec: ModelSpec,
) -> tuple[ValidationIssue, ...]:
  """Validate subjects with explicit duplicate-id state."""
  seen_ids: set[str] = set()
  issues: list[ValidationIssue] = []
  for subject in subjects:
    subject_id = subject.subject_id.strip()
    issues.extend(
      _subject_record_issues(
        subject,
        subject_id=subject_id,
        seen_ids=frozenset(seen_ids),
        required_fields=required_fields,
        model_spec=model_spec,
      ),
    )
    if subject_id:
      seen_ids.add(subject_id)
  return tuple(issues)


def _subject_record_issues(
  subject: SubjectRecord,
  *,
  subject_id: str,
  seen_ids: frozenset[str],
  required_fields: Sequence[str],
  model_spec: ModelSpec,
) -> tuple[ValidationIssue, ...]:
  """Return all validation issues for one subject record."""
  if not subject_id:
    return (
      ValidationIssue(
        severity="error",
        code="missing_subject_id",
        message="Subject records must include a non-empty subject_id.",
        field_name="subject_id",
      ),
    )
  return _discard_absent_issues(
    (
      _duplicate_subject_issue(subject_id) if subject_id in seen_ids else None,
      (
        _missing_date_of_birth_issue(subject_id)
        if model_spec.family != "ahrq_elixhauser" and subject.date_of_birth is None
        else None
      ),
      (
        _invalid_sex_issue(subject_id)
        if model_spec.family != "ahrq_elixhauser" and subject.sex not in _VALID_SEX_VALUES
        else None
      ),
      (
        _invalid_orec_issue(subject_id)
        if model_spec.family != "ahrq_elixhauser"
        and subject.original_reason_entitlement_code not in _VALID_OREC_VALUES
        else None
      ),
      *_invalid_binary_flag_issues(subject, subject_id),
      *_missing_required_field_issues(subject, subject_id, required_fields, model_spec),
    ),
  )


def _diagnosis_issues(
  diagnosis: DiagnosisRecord,
  subject_ids: frozenset[str],
) -> tuple[ValidationIssue, ...]:
  """Return all validation issues for one diagnosis record."""
  subject_id = diagnosis.subject_id.strip()
  return _discard_absent_issues(
    (
      _diagnosis_subject_id_issue(subject_id, subject_ids),
      _missing_icd10_code_issue(subject_id) if not diagnosis.icd10_code.strip() else None,
    ),
  )


def _invalid_binary_flag_issues(
  subject: SubjectRecord,
  subject_id: str,
) -> tuple[ValidationIssue, ...]:
  """Return invalid binary-flag issues for one subject."""
  return tuple(
    ValidationIssue(
      severity="error",
      code="invalid_binary_flag",
      message=f"{field_name} must be 0, 1, or null.",
      subject_id=subject_id,
      field_name=field_name,
    )
    for field_name in _OPTIONAL_BINARY_SUBJECT_FIELDS
    if (value := getattr(subject, field_name)) is not None and value not in _VALID_BINARY_VALUES
  )


def _missing_required_field_issues(
  subject: SubjectRecord,
  subject_id: str,
  required_fields: Sequence[str],
  model_spec: ModelSpec,
) -> tuple[ValidationIssue, ...]:
  """Return model-specific missing-field issues for one subject."""
  return tuple(
    ValidationIssue(
      severity="error",
      code="missing_required_model_field",
      message=f"{field_name} is required for model {model_spec.version_id}.",
      subject_id=subject_id,
      field_name=field_name,
    )
    for field_name in required_fields
    if getattr(subject, field_name) is None
  )


def _discard_absent_issues(
  issues: Sequence[ValidationIssue | None],
) -> tuple[ValidationIssue, ...]:
  """Drop non-issues from expression-oriented validators."""
  return tuple(issue for issue in issues if issue is not None)


def _empty_subject_issue() -> ValidationIssue:
  return ValidationIssue(
    severity="warning",
    code="empty_subject_input",
    message="No subject records were provided.",
  )


def _empty_diagnosis_issue() -> ValidationIssue:
  return ValidationIssue(
    severity="info",
    code="empty_diagnosis_input",
    message="No diagnosis records were provided.",
  )


def _duplicate_subject_issue(subject_id: str) -> ValidationIssue:
  return ValidationIssue(
    severity="error",
    code="duplicate_subject_id",
    message=f"Duplicate subject_id '{subject_id}' was found.",
    subject_id=subject_id,
    field_name="subject_id",
  )


def _missing_date_of_birth_issue(subject_id: str) -> ValidationIssue:
  return ValidationIssue(
    severity="error",
    code="missing_date_of_birth",
    message="Subject records must include a parseable date_of_birth.",
    subject_id=subject_id,
    field_name="date_of_birth",
  )


def _invalid_sex_issue(subject_id: str) -> ValidationIssue:
  return ValidationIssue(
    severity="error",
    code="invalid_sex",
    message="Subject sex must be 1 or 2.",
    subject_id=subject_id,
    field_name="sex",
  )


def _invalid_orec_issue(subject_id: str) -> ValidationIssue:
  return ValidationIssue(
    severity="error",
    code="invalid_orec",
    message="Subject original_reason_entitlement_code must be 0, 1, 2, or 3.",
    subject_id=subject_id,
    field_name="original_reason_entitlement_code",
  )


def _diagnosis_subject_id_issue(
  subject_id: str,
  subject_ids: frozenset[str],
) -> ValidationIssue | None:
  if not subject_id:
    return ValidationIssue(
      severity="error",
      code="missing_diagnosis_subject_id",
      message="Diagnosis records must include a non-empty subject_id.",
      field_name="subject_id",
    )
  if subject_id not in subject_ids:
    return ValidationIssue(
      severity="error",
      code="unknown_diagnosis_subject_id",
      message=(
        f"Diagnosis subject_id '{subject_id}' does not exist in the subject input."
      ),
      subject_id=subject_id,
      field_name="subject_id",
    )
  return None


def _missing_icd10_code_issue(subject_id: str) -> ValidationIssue:
  return ValidationIssue(
    severity="error",
    code="missing_icd10_code",
    message="Diagnosis records must include a non-empty icd10_code.",
    subject_id=subject_id or None,
    field_name="icd10_code",
  )


def _collect_columns(rows: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
  """Collect all distinct column names from row-oriented input."""
  ordered_columns: list[str] = []
  seen: set[str] = set()
  for row in rows:
    for column in row.keys():
      if column not in seen:
        ordered_columns.append(column)
        seen.add(column)
  return tuple(ordered_columns)


def _build_subject_record(
  row: InputRowMapping,
  mapping: Mapping[str, str],
) -> SubjectRecord:
  """Build a subject record from a row-oriented input mapping."""
  validated_row = SubjectRowSchema.model_validate(
    {
      "subject_id": _value_for(row, mapping, "subject_id"),
      "date_of_birth": _value_for(row, mapping, "date_of_birth"),
      "sex": _value_for(row, mapping, "sex"),
      "original_reason_entitlement_code": _value_for(
        row,
        mapping,
        "original_reason_entitlement_code",
      ),
      "limited_income_medicaid_flag": _value_for(
        row,
        mapping,
        "limited_income_medicaid_flag",
      ),
      "new_enrollee_medicaid_flag": _value_for(
        row,
        mapping,
        "new_enrollee_medicaid_flag",
      ),
      "concurrent_esrd_flag": _value_for(
        row,
        mapping,
        "concurrent_esrd_flag",
      ),
      "medicaid_flag": _value_for(row, mapping, "medicaid_flag"),
      "full_benefit_dual_flag": _value_for(
        row,
        mapping,
        "full_benefit_dual_flag",
      ),
      "partial_benefit_dual_flag": _value_for(
        row,
        mapping,
        "partial_benefit_dual_flag",
      ),
      "long_term_institutional_flag": _value_for(
        row,
        mapping,
        "long_term_institutional_flag",
      ),
    },
  )
  return SubjectRecord(
    subject_id=validated_row.subject_id,
    date_of_birth=validated_row.date_of_birth,
    sex=validated_row.sex,
    original_reason_entitlement_code=validated_row.original_reason_entitlement_code,
    limited_income_medicaid_flag=validated_row.limited_income_medicaid_flag,
    new_enrollee_medicaid_flag=validated_row.new_enrollee_medicaid_flag,
    concurrent_esrd_flag=validated_row.concurrent_esrd_flag,
    medicaid_flag=validated_row.medicaid_flag,
    full_benefit_dual_flag=validated_row.full_benefit_dual_flag,
    partial_benefit_dual_flag=validated_row.partial_benefit_dual_flag,
    long_term_institutional_flag=validated_row.long_term_institutional_flag,
  )


def _build_diagnosis_record(
  row: InputRowMapping,
  mapping: Mapping[str, str],
) -> DiagnosisRecord:
  """Build a diagnosis record from a row-oriented input mapping."""
  validated_row = DiagnosisRowSchema.model_validate(
    {
      "subject_id": _value_for(row, mapping, "subject_id"),
      "icd10_code": _value_for(row, mapping, "icd10_code"),
      "service_date": _value_for(row, mapping, "service_date"),
      "claim_id": _value_for(row, mapping, "claim_id"),
      "source": _value_for(row, mapping, "source"),
      "diagnosis_sequence": _value_for(row, mapping, "diagnosis_sequence"),
      "present_on_admission": _value_for(row, mapping, "present_on_admission"),
    },
  )
  return DiagnosisRecord(
    subject_id=validated_row.subject_id,
    icd10_code=validated_row.icd10_code,
    service_date=validated_row.service_date,
    claim_id=validated_row.claim_id,
    source=validated_row.source,
    diagnosis_sequence=validated_row.diagnosis_sequence,
    present_on_admission=validated_row.present_on_admission,
  )


def _value_for(
  row: InputRowMapping,
  mapping: Mapping[str, str],
  canonical_name: str,
) -> object | None:
  """Return the source value for a canonical field name."""
  source_name = mapping.get(canonical_name)
  if source_name is None:
    return None
  return row.get(source_name)
