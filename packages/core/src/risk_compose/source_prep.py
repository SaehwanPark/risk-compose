"""Source-driven preparation helpers for CMS-HCC scoring inputs."""

from __future__ import annotations

import ast
import csv
import re
from collections.abc import Callable, Generator, Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import TypeVar, cast

from comp_builders import Invalid, Valid, Validation, validation

from risk_compose._typing import ArtifactRow, ArtifactValue, InputRow, InputRowMapping
from risk_compose.registry import get_model_spec
from risk_compose.types import (
  DatabaseSourceSpec,
  DatabaseTableSpec,
  FlatFileSourceSpec,
  FlatFileTableSpec,
  PreparedScoringInputs,
  ScoringOptions,
  ScoringRequest,
  SourcePreparationRequest,
  SourceRole,
  TableArtifact,
  ValidationIssue,
)
from risk_compose.validation import (
  SUBJECT_COLUMN_ALIASES,
  build_request_from_rows,
  enforce_strict_validation,
  resolve_input_columns,
)

SUPPORTED_SOURCE_PROFILES = (
  "cms_purchased_files_ffs_2026",
  "ccw_vrdc_ffs_2026",
)

SUPPORTED_SOURCE_ROLES = (
  "subject",
  "hospital_inpatient",
  "hospital_outpatient",
  "professional",
  "dme",
  "hha",
  "snf",
  "hospice",
)

CANDIDATE_SOURCE_ROLES = (
  "hospital_inpatient",
  "hospital_outpatient",
  "professional",
)

NON_CANDIDATE_SOURCE_ROLES = (
  "dme",
  "hha",
  "snf",
  "hospice",
)

PREPARED_BENEFICIARY_COLUMNS = (
  "subject_id",
  "date_of_birth",
  "sex",
  "original_reason_entitlement_code",
  "limited_income_medicaid_flag",
  "new_enrollee_medicaid_flag",
)

PREPARED_DIAGNOSIS_COLUMNS = (
  "subject_id",
  "icd10_code",
  "service_date",
  "claim_id",
  "source",
  "source_role",
  "acceptance_status",
  "acceptance_reason",
)

REJECTED_DIAGNOSIS_COLUMNS = (
  "source_role",
  "subject_id",
  "icd10_code",
  "service_date",
  "claim_id",
  "source",
  "procedure_code",
  "bill_type",
  "provider_type",
  "telehealth_service",
  "audio_only",
  "rejection_code",
  "rejection_reason",
)

SOURCE_LINEAGE_COLUMNS = (
  "source_profile",
  "source_kind",
  "source_role",
  "source_locator",
  "source_filter",
  "source_field",
  "canonical_field",
  "lineage_status",
)

_REQUIRED_BENEFICIARY_MAPPINGS = (
  "subject_id",
  "date_of_birth",
  "sex",
  "original_reason_entitlement_code",
)

_CLAIM_COLUMN_ALIASES = {
  "subject_id": ("subject_id", "id", "bene_id", "bene_key"),
  "icd10_code": ("icd10_code", "icd10", "dx_code", "line_icd_dgns_cd", "icd_dgns_cd1"),
  "service_date": ("service_date", "service_dt", "clm_from_dt", "from_date"),
  "claim_id": ("claim_id", "clm_id"),
  "source": ("source",),
  "procedure_code": ("procedure_code", "hcpcs_code", "hcpcs_cd", "cpt_hcpcs_code", "cpt_hcpcs"),
  "bill_type": ("bill_type", "type_of_bill", "tob"),
  "provider_type": ("provider_type", "provider_category", "provider_specialty", "prvdr_spclty"),
  "telehealth_service": ("telehealth_service", "telehealth", "telehealth_flag"),
  "audio_only": ("audio_only", "audio_only_flag"),
}

_FILTER_IDENTIFIER_PATTERN = re.compile(r"[^0-9a-zA-Z_]+")
_FILTER_KEYWORD_PATTERN = re.compile(
  r"\b(and|or|not|in|is|none|true|false)\b",
  flags=re.IGNORECASE,
)
_ALLOWED_FILTER_NODES = (
  ast.And,
  ast.BoolOp,
  ast.Compare,
  ast.Constant,
  ast.Eq,
  ast.Expression,
  ast.Gt,
  ast.GtE,
  ast.In,
  ast.Is,
  ast.IsNot,
  ast.List,
  ast.Load,
  ast.Lt,
  ast.LtE,
  ast.Name,
  ast.Not,
  ast.NotEq,
  ast.NotIn,
  ast.Or,
  ast.Tuple,
  ast.UnaryOp,
)

_PROFILE_RULE_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
  "cms_purchased_files_ffs_2026": {
    "hospital_inpatient": ("bill_type",),
    "hospital_outpatient": ("procedure_code", "bill_type", "provider_type", "telehealth_service", "audio_only"),
    "professional": ("procedure_code", "provider_type", "telehealth_service", "audio_only"),
  },
  "ccw_vrdc_ffs_2026": {
    "hospital_inpatient": ("bill_type",),
    "hospital_outpatient": ("procedure_code", "bill_type", "provider_type", "telehealth_service", "audio_only"),
    "professional": ("procedure_code", "provider_type", "telehealth_service", "audio_only"),
  },
}


class FilterSyntaxError(ValueError):
  """Raised when a declared source filter cannot be parsed safely."""


_ValidationValue = TypeVar("_ValidationValue")


def validate_source_request(
  source_request: SourcePreparationRequest,
) -> tuple[SourcePreparationRequest, tuple[ValidationIssue, ...]]:
  """Validate a source-preparation request and return collected issues."""
  validated_request, issues = _unwrap_validation_result(
    _validate_source_request(source_request),
    fallback=source_request,
  )

  if source_request.options.strict_validation:
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


def prepare_scoring_inputs(source_request: SourcePreparationRequest) -> PreparedScoringInputs:
  """Prepare canonical scoring inputs from a declared source."""
  validated_request, initial_issues = validate_source_request(source_request)
  source_spec = validated_request.source_spec

  if _has_blocking_issues(initial_issues):
    return _empty_prepared_inputs(validated_request.options, source_spec, initial_issues)

  if isinstance(source_spec, DatabaseSourceSpec):
    database_issue = ValidationIssue(
      severity="warning",
      code="database_source_read_not_implemented",
      message=(
        "Database source reading is not implemented in the first skeleton. "
        "Use the declared locators and mappings as the contract for a later engine-specific reader."
      ),
    )
    return _empty_prepared_inputs(
      validated_request.options,
      source_spec,
      initial_issues + (database_issue,),
    )

  subject_table = source_spec.sources["subject"]
  subject_source_rows = _read_csv_rows(subject_table.path)
  subject_mapping = _resolve_source_mapping(
    subject_source_rows,
    subject_table.columns,
    SUBJECT_COLUMN_ALIASES,
  )
  subject_rows, subject_filter_issues = _apply_source_filter(
    subject_source_rows,
    subject_table.filter,
    source_role="subject",
    source_locator=str(subject_table.path),
  )

  mapping_issues: list[ValidationIssue] = list(
    _missing_mapping_issues(
      subject_mapping,
      _REQUIRED_BENEFICIARY_MAPPINGS,
      entity="subject",
    ),
  )
  mapping_issues.extend(subject_filter_issues)
  role_rows: dict[str, tuple[InputRow, ...]] = {}
  resolved_mappings: dict[str, dict[str, str]] = {
    "subject": subject_mapping,
  }

  source_profile = str(source_spec.source_profile)
  for role, table_spec in source_spec.sources.items():
    if role == "subject":
      continue
    source_rows = _read_csv_rows(table_spec.path)
    mapping = _resolve_source_mapping(source_rows, table_spec.columns, _CLAIM_COLUMN_ALIASES)
    resolved_mappings[str(role)] = mapping
    mapping_issues.extend(
      _missing_mapping_issues(
        mapping,
        _required_fields_for_role(role),
        entity=str(role),
      ),
    )
    mapping_issues.extend(
      _missing_eligibility_mapping_issues(
        mapping,
        source_profile=source_profile,
        role=str(role),
      ),
    )
    filtered_rows, filter_issues = _apply_source_filter(
      source_rows,
      table_spec.filter,
      source_role=str(role),
      source_locator=str(table_spec.path),
    )
    mapping_issues.extend(filter_issues)
    role_rows[str(role)] = _apply_declared_mapping(filtered_rows, mapping)

  all_issues = initial_issues + tuple(mapping_issues)
  if validated_request.options.strict_validation:
    enforce_strict_validation(all_issues)
  if _has_blocking_issues(all_issues):
    return _empty_prepared_inputs(validated_request.options, source_spec, all_issues, resolved_mappings)

  accepted_rows: list[ArtifactRow] = []
  accepted_metadata: list[ArtifactRow] = []
  rejected_rows: list[ArtifactRow] = []

  for role, rows in role_rows.items():
    source_locator = str(source_spec.sources[role].path)
    for row in rows:
      candidate = _normalize_candidate_row(role, row, source_locator)
      rejection = _candidate_rejection(source_profile, role, candidate)
      if rejection is None:
        accepted_rows.append(
          {
            "subject_id": candidate["subject_id"],
            "icd10_code": candidate["icd10_code"],
            "service_date": candidate["service_date"],
            "claim_id": candidate["claim_id"],
            "source": candidate["source"],
          },
        )
        accepted_metadata.append(
          {
            "source_role": role,
            "acceptance_status": "accepted",
            "acceptance_reason": _acceptance_reason(role),
          },
        )
        continue

      rejection_code, rejection_reason = rejection
      rejected_rows.append(
        {
          "source_role": role,
          "subject_id": candidate["subject_id"],
          "icd10_code": candidate["icd10_code"],
          "service_date": candidate["service_date"],
          "claim_id": candidate["claim_id"],
          "source": candidate["source"],
          "procedure_code": candidate["procedure_code"],
          "bill_type": candidate["bill_type"],
          "provider_type": candidate["provider_type"],
          "telehealth_service": candidate["telehealth_service"],
          "audio_only": candidate["audio_only"],
          "rejection_code": rejection_code,
          "rejection_reason": rejection_reason,
        },
      )

  request = build_request_from_rows(
    _apply_declared_mapping(subject_rows, subject_mapping),
    tuple(accepted_rows),
    options=validated_request.options,
  )
  prepared_diagnoses = _build_prepared_diagnoses_artifact(request, accepted_metadata)
  return PreparedScoringInputs(
    scoring_request=request,
    prepared_subjects=_build_prepared_subjects_artifact(request),
    prepared_diagnoses=prepared_diagnoses,
    rejected_diagnosis_candidates=TableArtifact(
      name="rejected_diagnosis_candidates",
      columns=REJECTED_DIAGNOSIS_COLUMNS,
      rows=tuple(rejected_rows),
    ),
    source_lineage=_build_source_lineage(source_spec, resolved_mappings),
    preparation_issues=all_issues,
  )


@validation.block
def _validate_source_request(
  source_request: SourcePreparationRequest,
) -> Generator[
  Validation[SourcePreparationRequest, ValidationIssue],
  object,
  SourcePreparationRequest,
]:
  """Compose independent source-preparation validation checks."""
  source_spec = source_request.source_spec
  source_roles = tuple(source_spec.sources.keys())
  yield _validate_source_model(source_request)
  yield _validate_source_profile(source_request)
  yield _validate_source_roles(source_request, source_roles)
  yield _validate_source_presence(source_request, source_roles)
  yield _validate_source_kind(source_request)
  return source_request


def _validate_source_model(
  source_request: SourcePreparationRequest,
) -> Validation[SourcePreparationRequest, ValidationIssue]:
  """Validate source-preparation model support."""
  try:
    model_spec = get_model_spec(source_request.options.model_version)
  except KeyError:
    return _validation_for_source(
      source_request,
      (
        ValidationIssue(
          severity="error",
          code="unsupported_source_model_version",
          message=(
            f"Source preparation does not support unknown model version: "
            f"{source_request.options.model_version}"
          ),
          field_name="model_version",
        ),
      ),
    )
  if model_spec.family != "cms_hcc":
    return _validation_for_source(
      source_request,
      (
        ValidationIssue(
          severity="error",
          code="unsupported_source_model_family",
          message=(
            "Source preparation is only implemented for CMS-HCC model versions in this milestone. "
            f"Received model family '{model_spec.family}' for version '{model_spec.version_id}'."
          ),
          field_name="model_version",
        ),
      ),
    )
  return Valid(source_request)


def _validate_source_profile(
  source_request: SourcePreparationRequest,
) -> Validation[SourcePreparationRequest, ValidationIssue]:
  """Validate the declared raw-source profile."""
  source_spec = source_request.source_spec
  if source_spec.source_profile in SUPPORTED_SOURCE_PROFILES:
    return Valid(source_request)
  return _validation_for_source(
    source_request,
    (
      ValidationIssue(
        severity="error",
        code="unsupported_source_profile",
        message=f"Unsupported source profile: {source_spec.source_profile}",
        field_name="source_profile",
      ),
    ),
  )


def _validate_source_roles(
  source_request: SourcePreparationRequest,
  source_roles: Sequence[SourceRole | str],
) -> Validation[SourcePreparationRequest, ValidationIssue]:
  """Validate source roles against supported logical roles."""
  return _validation_for_source(
    source_request,
    (
      ValidationIssue(
        severity="error",
        code="unsupported_source_role",
        message=f"Unsupported source role: {role}",
        field_name="sources",
      )
      for role in source_roles
      if role not in SUPPORTED_SOURCE_ROLES
    ),
  )


def _validate_source_presence(
  source_request: SourcePreparationRequest,
  source_roles: Sequence[SourceRole | str],
) -> Validation[SourcePreparationRequest, ValidationIssue]:
  """Validate required source role presence."""
  return _validation_for_source(
    source_request,
    _discard_absent_source_issues(
      (
        (
          ValidationIssue(
            severity="error",
            code="missing_subject_source",
            message="Source manifests must declare a subject source role.",
            field_name="sources",
          )
          if "subject" not in source_request.source_spec.sources
          else None
        ),
        (
          ValidationIssue(
            severity="error",
            code="missing_candidate_source_role",
            message=(
              "Source manifests must declare at least one candidate-producing claim role: "
              "hospital_inpatient, hospital_outpatient, or professional."
            ),
            field_name="sources",
          )
          if not any(role in CANDIDATE_SOURCE_ROLES for role in source_roles)
          else None
        ),
      ),
    ),
  )


def _validate_source_kind(
  source_request: SourcePreparationRequest,
) -> Validation[SourcePreparationRequest, ValidationIssue]:
  """Validate kind-specific source declarations."""
  source_spec = source_request.source_spec
  if isinstance(source_spec, FlatFileSourceSpec):
    return _validate_flat_file_sources(source_request, source_spec)
  if isinstance(source_spec, DatabaseSourceSpec):
    return _validate_database_sources(source_request, source_spec)
  return Valid(source_request)


def _validate_flat_file_sources(
  source_request: SourcePreparationRequest,
  source_spec: FlatFileSourceSpec,
) -> Validation[SourcePreparationRequest, ValidationIssue]:
  """Validate flat-file source declarations without reading contents."""
  format_issue = (
    ValidationIssue(
      severity="error",
      code="unsupported_source_file_format",
      message="Only CSV flat-file source inputs are implemented in the first skeleton.",
      field_name="file_format",
    )
    if source_spec.file_format != "csv"
    else None
  )
  file_issues = tuple(
    ValidationIssue(
      severity="error",
      code="missing_source_file",
      message=f"Source file does not exist for role '{role}': {flat_file_table_spec.path}",
      field_name="sources",
    )
    for role, flat_file_table_spec in source_spec.sources.items()
    if not flat_file_table_spec.path.exists()
  )
  return _validation_for_source(
    source_request,
    _discard_absent_source_issues((format_issue, *file_issues)),
  )


def _validate_database_sources(
  source_request: SourcePreparationRequest,
  source_spec: DatabaseSourceSpec,
) -> Validation[SourcePreparationRequest, ValidationIssue]:
  """Validate database source declarations without opening connections."""
  return _validation_for_source(
    source_request,
    (
      issue
      for role, database_table_spec in source_spec.sources.items()
      for issue in _database_source_issues(str(role), database_table_spec)
    ),
  )


def _validation_for_source(
  value: SourcePreparationRequest,
  issues: Iterable[ValidationIssue],
) -> Validation[SourcePreparationRequest, ValidationIssue]:
  """Return a valid source request or accumulated validation issues."""
  collected_issues = tuple(issues)
  if collected_issues:
    return Invalid(collected_issues)
  return Valid(value)


def _database_source_issues(
  role: str,
  database_table_spec: DatabaseTableSpec,
) -> tuple[ValidationIssue, ...]:
  """Return validation issues for one database-backed source role."""
  locator_issue = (
    ValidationIssue(
      severity="error",
      code="missing_source_locator",
      message=f"Database source role '{role}' must declare a non-empty locator.",
      field_name="sources",
    )
    if not database_table_spec.locator.strip()
    else None
  )
  return _discard_absent_source_issues(
    (
      locator_issue,
      *_missing_mapping_issues(
        database_table_spec.columns,
        _required_fields_for_role(role),
        entity=role,
      ),
    ),
  )


def _discard_absent_source_issues(
  issues: Sequence[ValidationIssue | None],
) -> tuple[ValidationIssue, ...]:
  """Drop non-issues from expression-oriented source validators."""
  return tuple(issue for issue in issues if issue is not None)


def _empty_prepared_inputs(
  options: ScoringOptions,
  source_spec: FlatFileSourceSpec | DatabaseSourceSpec,
  issues: Sequence[ValidationIssue],
  resolved_mappings: Mapping[str, Mapping[str, str]] | None = None,
) -> PreparedScoringInputs:
  """Return an empty prepared-input bundle for blocked preparation flows."""
  return PreparedScoringInputs(
    scoring_request=ScoringRequest(subjects=(), diagnoses=(), options=options),
    prepared_subjects=TableArtifact.empty("prepared_subjects", PREPARED_BENEFICIARY_COLUMNS),
    prepared_diagnoses=TableArtifact.empty("prepared_diagnoses", PREPARED_DIAGNOSIS_COLUMNS),
    rejected_diagnosis_candidates=TableArtifact.empty(
      "rejected_diagnosis_candidates",
      REJECTED_DIAGNOSIS_COLUMNS,
    ),
    source_lineage=_build_source_lineage(source_spec, resolved_mappings or {}),
    preparation_issues=tuple(issues),
  )


def _required_fields_for_role(role: str) -> tuple[str, ...]:
  """Return required canonical fields for a logical source role."""
  if role == "subject":
    return _REQUIRED_BENEFICIARY_MAPPINGS
  if role == "hospital_inpatient":
    return ("subject_id", "icd10_code", "bill_type")
  if role == "hospital_outpatient":
    return ("subject_id", "icd10_code", "procedure_code", "bill_type")
  if role == "professional":
    return ("subject_id", "icd10_code", "procedure_code")
  if role in NON_CANDIDATE_SOURCE_ROLES:
    return ("subject_id", "icd10_code")
  return ()


def _eligibility_fields_for_role(
  source_profile: str,
  role: str,
) -> tuple[str, ...]:
  """Return fields required to evaluate profile-owned eligibility rules."""
  return _PROFILE_RULE_FIELDS.get(source_profile, {}).get(role, ())


def _missing_eligibility_mapping_issues(
  mapping: Mapping[str, str],
  *,
  source_profile: str,
  role: str,
) -> tuple[ValidationIssue, ...]:
  """Build blocking issues when profile-owned eligibility fields are unavailable."""
  required_fields = tuple(
    field
    for field in _eligibility_fields_for_role(source_profile, role)
    if field not in _required_fields_for_role(role)
  )
  missing_fields = tuple(field for field in required_fields if field not in mapping)
  if not missing_fields:
    return ()
  return (
    ValidationIssue(
      severity="error",
      code=f"missing_{role}_eligibility_mappings",
      message=(
        f"{role.replace('_', ' ').capitalize()} source mappings for profile '{source_profile}' "
        f"must define eligibility fields: {', '.join(missing_fields)}"
      ),
      field_name="sources",
    ),
  )


def _missing_mapping_issues(
  mapping: Mapping[str, str],
  required_fields: Sequence[str],
  *,
  entity: str,
) -> tuple[ValidationIssue, ...]:
  """Build validation issues for missing required canonical mappings."""
  missing_fields = tuple(field for field in required_fields if field not in mapping)
  if not missing_fields:
    return ()
  return (
    ValidationIssue(
      severity="error",
      code=f"missing_{entity}_mappings",
      message=(
        f"{entity.replace('_', ' ').capitalize()} source mappings must define canonical fields: "
        f"{', '.join(missing_fields)}"
      ),
      field_name="sources",
    ),
  )


def _has_blocking_issues(issues: Sequence[ValidationIssue]) -> bool:
  """Return whether a sequence of issues contains blocking errors."""
  return any(issue.severity == "error" for issue in issues)


def _read_csv_rows(path: Path) -> tuple[dict[str, str], ...]:
  """Read a CSV file into row dictionaries."""
  with path.open("r", encoding="utf-8-sig", newline="") as handle:
    return tuple(csv.DictReader(handle))


def _resolve_source_mapping(
  rows: Sequence[InputRowMapping],
  declared_mapping: Mapping[str, str],
  aliases: Mapping[str, tuple[str, ...]],
) -> dict[str, str]:
  """Resolve canonical field names to raw source fields."""
  resolved_mapping = resolve_input_columns(_collect_columns(rows), aliases)
  resolved_mapping.update(dict(declared_mapping))
  return resolved_mapping


def _collect_columns(rows: Sequence[InputRowMapping]) -> tuple[str, ...]:
  """Collect distinct columns from row-oriented data."""
  seen: set[str] = set()
  ordered: list[str] = []
  for row in rows:
    for column in row.keys():
      if column not in seen:
        ordered.append(column)
        seen.add(column)
  return tuple(ordered)


def _apply_declared_mapping(
  rows: Sequence[InputRowMapping],
  mapping: Mapping[str, str],
) -> tuple[InputRow, ...]:
  """Remap source rows into canonical field names."""
  remapped_rows: list[InputRow] = []
  for row in rows:
    remapped_row = dict(row)
    for canonical_field, source_field in mapping.items():
      if source_field in row:
        remapped_row[canonical_field] = row[source_field]
    remapped_rows.append(remapped_row)
  return tuple(remapped_rows)


def _apply_source_filter(
  rows: Sequence[InputRowMapping],
  filter_expression: str | None,
  *,
  source_role: str,
  source_locator: str,
) -> tuple[tuple[InputRow, ...], tuple[ValidationIssue, ...]]:
  """Apply a conservative declared prefilter to raw source rows."""
  if filter_expression is None:
    return tuple(dict(row) for row in rows), ()
  try:
    predicate = _compile_source_filter(filter_expression, _collect_columns(rows))
  except FilterSyntaxError as exc:
    return (
      (),
      (
        ValidationIssue(
          severity="error",
          code="invalid_source_filter",
          message=(
            f"Declared filter for source role '{source_role}' at '{source_locator}' is unsupported: {exc}"
          ),
          field_name="sources",
        ),
      ),
    )
  filtered_rows: list[InputRow] = []
  for row in rows:
    try:
      if predicate(row):
        filtered_rows.append(dict(row))
    except FilterSyntaxError as exc:
      return (
        (),
        (
          ValidationIssue(
            severity="error",
            code="invalid_source_filter",
            message=(
              f"Declared filter for source role '{source_role}' at '{source_locator}' could not be "
              f"evaluated: {exc}"
            ),
            field_name="sources",
          ),
        ),
      )
  return tuple(filtered_rows), ()


def _compile_source_filter(
  filter_expression: str,
  columns: Sequence[str],
) -> Callable[[InputRowMapping], bool]:
  """Compile a declared source filter into a safe row predicate."""
  normalized_expression = _normalize_filter_expression(filter_expression)
  try:
    tree = ast.parse(normalized_expression, mode="eval")
  except SyntaxError as exc:
    raise FilterSyntaxError(str(exc)) from exc
  for node in ast.walk(tree):
    if not isinstance(node, _ALLOWED_FILTER_NODES):
      raise FilterSyntaxError(f"unsupported syntax element '{type(node).__name__}'")
    if isinstance(node, ast.Name):
      node.id = _filter_identifier(node.id)
  available_fields = {
    _filter_identifier(column): column
    for column in columns
    if _filter_identifier(column)
  }
  referenced_fields = {
    node.id
    for node in ast.walk(tree)
    if isinstance(node, ast.Name) and node.id not in {"true", "false", "none"}
  }
  missing_fields = tuple(sorted(field for field in referenced_fields if field not in available_fields))
  if missing_fields:
    raise FilterSyntaxError(
      f"unknown filter field(s): {', '.join(missing_fields)}"
    )
  tree = ast.fix_missing_locations(tree)
  compiled = compile(tree, "<source-filter>", "eval")

  def _predicate(row: InputRowMapping) -> bool:
    environment = {
      _filter_identifier(column): _coerce_filter_value(value)
      for column, value in row.items()
      if _filter_identifier(column)
    }
    environment.update({"true": True, "false": False, "none": None})
    try:
      result = eval(compiled, {"__builtins__": {}}, environment)
    except Exception as exc:  # pragma: no cover - exercised via FilterSyntaxError wrapping
      raise FilterSyntaxError(str(exc)) from exc
    if not isinstance(result, bool):
      raise FilterSyntaxError("filter expressions must evaluate to a boolean result")
    return result

  return _predicate


def _normalize_filter_expression(filter_expression: str) -> str:
  """Normalize a conservative SQL/Python-like filter expression."""
  expression = filter_expression.strip()
  if not expression:
    raise FilterSyntaxError("empty filters are not supported")
  expression = expression.replace("<>", "!=")
  expression = re.sub(r"(?<![<>=!])=(?!=)", "==", expression)
  expression = re.sub(r"\bAND\b", "and", expression, flags=re.IGNORECASE)
  expression = re.sub(r"\bOR\b", "or", expression, flags=re.IGNORECASE)
  expression = re.sub(r"\bNOT\b", "not", expression, flags=re.IGNORECASE)
  expression = re.sub(r"\bIN\b", "in", expression, flags=re.IGNORECASE)
  expression = re.sub(r"\bIS\b", "is", expression, flags=re.IGNORECASE)
  expression = re.sub(r"\bNULL\b", "None", expression, flags=re.IGNORECASE)
  expression = re.sub(r"\bTRUE\b", "True", expression, flags=re.IGNORECASE)
  expression = re.sub(r"\bFALSE\b", "False", expression, flags=re.IGNORECASE)
  return expression


def _filter_identifier(name: str) -> str:
  """Normalize a filter identifier to a stable row-environment key."""
  normalized = _FILTER_IDENTIFIER_PATTERN.sub("_", name.strip()).strip("_").lower()
  normalized = re.sub(r"_+", "_", normalized)
  if not normalized:
    return ""
  if normalized[0].isdigit():
    return f"f_{normalized}"
  if _FILTER_KEYWORD_PATTERN.fullmatch(normalized):
    return f"field_{normalized}"
  return normalized


def _coerce_filter_value(value: object | None) -> object | None:
  """Coerce raw source values into scalar filter operands."""
  text = _stringify(value)
  if not text:
    return None
  lowered = text.lower()
  if lowered in {"true", "t", "yes", "y"}:
    return True
  if lowered in {"false", "f", "no", "n"}:
    return False
  try:
    return int(text)
  except ValueError:
    try:
      return float(text)
    except ValueError:
      return text


def _normalize_candidate_row(
  role: str,
  row: InputRowMapping,
  source_locator: str,
) -> ArtifactRow:
  """Normalize one claim-derived diagnosis candidate row."""
  return {
    "subject_id": _stringify(row.get("subject_id")),
    "icd10_code": _stringify(row.get("icd10_code")).upper(),
    "service_date": cast(ArtifactValue, row.get("service_date")),
    "claim_id": _optional_string(row.get("claim_id")),
    "source": _optional_string(row.get("source")) or source_locator,
    "source_role": role,
    "procedure_code": _optional_string(row.get("procedure_code")),
    "bill_type": _optional_string(row.get("bill_type")),
    "provider_type": _normalize_token(row.get("provider_type")),
    "telehealth_service": _truthy(row.get("telehealth_service")),
    "audio_only": _truthy(row.get("audio_only")),
  }


def _candidate_rejection(
  source_profile: str,
  role: str,
  candidate: InputRowMapping,
) -> tuple[str, str] | None:
  """Return a rejection code and reason when a candidate is ineligible."""
  if source_profile == "cms_purchased_files_ffs_2026":
    return _candidate_rejection_ffs_2026(role, candidate)
  if source_profile == "ccw_vrdc_ffs_2026":
    return _candidate_rejection_ffs_2026(role, candidate)
  return (
    "unsupported_source_profile",
    f"Unsupported source profile for candidate eligibility filtering: {source_profile}",
  )


def _candidate_rejection_ffs_2026(
  role: str,
  candidate: InputRowMapping,
) -> tuple[str, str] | None:
  """Return a rejection code and reason for the first shipped FFS profiles."""
  if not candidate["subject_id"] or not candidate["icd10_code"]:
    return (
      "missing_candidate_fields",
      "Candidate rows must include subject_id and icd10_code before eligibility filtering.",
    )

  if role in NON_CANDIDATE_SOURCE_ROLES:
    return (
      "non_candidate_source_role",
      "This source role is not candidate-producing for the initial raw FFS profiles.",
    )

  if role in {"hospital_outpatient", "professional"}:
    if candidate["telehealth_service"] and candidate["audio_only"]:
      return (
        "audio_only_telehealth_excluded",
        "Audio-only telehealth diagnoses are not accepted in this scaffolded eligibility filter.",
      )

    if candidate["provider_type"] == "diagnostic_radiology":
      return (
        "diagnostic_radiology_excluded",
        "Diagnostic radiology is not an acceptable provider category for this scaffolded eligibility filter.",
      )

  if role == "hospital_inpatient":
    bill_type = _digits_only(candidate["bill_type"])
    if not bill_type:
      return (
        "missing_bill_type",
        "Hospital inpatient candidates must provide a bill_type to apply inpatient eligibility rules.",
      )
    if not bill_type.startswith("11"):
      return (
        "ineligible_inpatient_context",
        "Hospital inpatient candidates must have an eligible inpatient bill type in this scaffolded filter.",
      )
    return None

  procedure_code = _stringify(candidate["procedure_code"]).upper()
  if not procedure_code:
    return (
      "missing_procedure_code",
      "Outpatient and professional candidates must provide a procedure_code for CPT/HCPCS filtering.",
    )
  if procedure_code not in _eligible_procedure_codes():
    return (
      "procedure_code_not_eligible",
      "The procedure_code is not present in the CMS risk-adjustment eligible CPT/HCPCS list.",
    )

  if role == "hospital_outpatient":
    bill_type = _digits_only(candidate["bill_type"])
    if not bill_type:
      return (
        "missing_bill_type",
        "Hospital outpatient candidates must provide a bill_type to apply outpatient eligibility rules.",
      )
    if not bill_type.startswith("13"):
      return (
        "ineligible_outpatient_context",
        "Hospital outpatient candidates must have an eligible outpatient bill type in this scaffolded filter.",
      )

  return None


def _acceptance_reason(role: str) -> str:
  """Return a stable acceptance reason for an eligible candidate role."""
  if role == "hospital_inpatient":
    return "eligible_inpatient_source"
  if role == "hospital_outpatient":
    return "eligible_outpatient_claim"
  if role == "professional":
    return "eligible_professional_claim"
  return "eligible_candidate"


def _build_prepared_subjects_artifact(request: ScoringRequest) -> TableArtifact:
  """Build the canonical prepared subject artifact."""
  return TableArtifact(
    name="prepared_subjects",
    columns=PREPARED_BENEFICIARY_COLUMNS,
    rows=tuple(
      {
        "subject_id": subject.subject_id,
        "date_of_birth": subject.date_of_birth,
        "sex": subject.sex,
        "original_reason_entitlement_code": subject.original_reason_entitlement_code,
        "limited_income_medicaid_flag": subject.limited_income_medicaid_flag,
        "new_enrollee_medicaid_flag": subject.new_enrollee_medicaid_flag,
      }
      for subject in request.subjects
    ),
  )


def _build_prepared_diagnoses_artifact(
  request: ScoringRequest,
  accepted_metadata: Sequence[ArtifactRow],
) -> TableArtifact:
  """Build the accepted canonical diagnosis artifact with filter metadata."""
  rows: list[ArtifactRow] = []
  for diagnosis, metadata in zip(request.diagnoses, accepted_metadata, strict=False):
    rows.append(
      {
        "subject_id": diagnosis.subject_id,
        "icd10_code": diagnosis.icd10_code,
        "service_date": diagnosis.service_date,
        "claim_id": diagnosis.claim_id,
        "source": diagnosis.source,
        "source_role": metadata["source_role"],
        "acceptance_status": metadata["acceptance_status"],
        "acceptance_reason": metadata["acceptance_reason"],
      },
    )
  return TableArtifact(
    name="prepared_diagnoses",
    columns=PREPARED_DIAGNOSIS_COLUMNS,
    rows=tuple(rows),
  )


def _build_source_lineage(
  source_spec: FlatFileSourceSpec | DatabaseSourceSpec,
  resolved_mappings: Mapping[str, Mapping[str, str]],
) -> TableArtifact:
  """Build a lineage artifact for how raw source fields map to canonical inputs."""
  source_kind = "flat_file" if isinstance(source_spec, FlatFileSourceSpec) else "database"
  rows: list[ArtifactRow] = []
  for role, table_spec in source_spec.sources.items():
    mapping = dict(resolved_mappings.get(str(role), table_spec.columns))
    rows.extend(
      _lineage_rows_for_source(
        source_profile=str(source_spec.source_profile),
        source_kind=source_kind,
        source_role=str(role),
        table_spec=table_spec,
        mapping=mapping,
      ),
    )
  return TableArtifact(
    name="source_lineage",
    columns=SOURCE_LINEAGE_COLUMNS,
    rows=tuple(rows),
  )


def _lineage_rows_for_source(
  *,
  source_profile: str,
  source_kind: str,
  source_role: str,
  table_spec: FlatFileTableSpec | DatabaseTableSpec,
  mapping: Mapping[str, str],
) -> list[ArtifactRow]:
  """Build lineage rows for one logical source role."""
  source_locator = (
    str(table_spec.path)
    if isinstance(table_spec, FlatFileTableSpec)
    else _compose_database_locator(table_spec.schema_name, table_spec.locator)
  )
  source_filter = table_spec.filter
  if not mapping:
    return [
      {
        "source_profile": source_profile,
        "source_kind": source_kind,
        "source_role": source_role,
        "source_locator": source_locator,
        "source_filter": source_filter,
        "source_field": None,
        "canonical_field": None,
        "lineage_status": "locator_only",
      },
    ]
  return [
    {
      "source_profile": source_profile,
      "source_kind": source_kind,
      "source_role": source_role,
      "source_locator": source_locator,
      "source_filter": source_filter,
      "source_field": source_field,
      "canonical_field": canonical_field,
      "lineage_status": "mapped",
    }
    for canonical_field, source_field in mapping.items()
  ]


def _compose_database_locator(schema_name: str | None, locator: str) -> str:
  """Compose a display locator for database-backed sources."""
  if schema_name:
    return f"{schema_name}.{locator}"
  return locator


def _stringify(value: object | None) -> str:
  """Normalize string-like source values."""
  if value is None:
    return ""
  text = str(value).strip()
  return "" if text.lower() in {"", "nan", "none"} else text


def _optional_string(value: object | None) -> str | None:
  """Normalize nullable string-like source values."""
  text = _stringify(value)
  return text or None


def _truthy(value: object | None) -> bool:
  """Interpret common truthy source values."""
  return _stringify(value).lower() in {"1", "true", "t", "yes", "y"}


def _normalize_token(value: object | None) -> str | None:
  """Normalize category-like source values to stable lowercase tokens."""
  text = _stringify(value).lower().replace(" ", "_").replace("-", "_")
  return text or None


def _digits_only(value: object | None) -> str:
  """Normalize a bill-type-like value to just digits."""
  return "".join(character for character in _stringify(value) if character.isdigit())


@lru_cache(maxsize=1)
def _eligible_procedure_codes() -> frozenset[str]:
  """Load the archived CMS 2026 eligible CPT/HCPCS code list."""
  path = (
    Path(__file__).resolve().parent
    / "data"
    / "cms_docs"
    / "cms"
    / "cpt-hcpcs"
    / "derived"
    / "2026-medicare-advantage-risk-adjustment-eligible-cpt-hcpcs-codes"
    / "CY2026Q1_CPTHCPCS_finalforposting.csv"
  )
  codes: set[str] = set()
  with path.open("r", encoding="latin-1", newline="") as handle:
    reader = csv.reader(handle)
    for row in reader:
      if row and row[0] == "HCPCS/CPT Code":
        break
    for row in reader:
      if not row or not row[0] or row[0].startswith("Definitions"):
        break
      if len(row) >= 3 and row[2].strip().lower() == "yes":
        codes.add(row[0].strip().upper())
  return frozenset(codes)
