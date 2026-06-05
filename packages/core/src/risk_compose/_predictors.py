"""Predictor-stage logic split into shared helpers and family-specific hooks."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from risk_compose._typing import ArtifactRow, ArtifactValue
from risk_compose.registry import MappingRule, get_elixhauser_tables, get_model_tables
from risk_compose.types import SubjectRecord, ModelSpec, ScoringRequest, TableArtifact

CMS_HCC_PREDICTOR_BASE_COLUMNS = (
  "subject_id",
  "model_version",
  "age",
  "sex",
  "original_reason_entitlement_code",
  "limited_income_medicaid_flag",
  "new_enrollee_medicaid_flag",
  "is_disabled",
  "is_originally_disabled",
  "ce_age_sex_cell",
  "ne_age_sex_cell",
  "mapped_cc_count",
  "active_hcc_count",
  "diagnosis_category_count",
  "interaction_count",
  "payment_hcc_count",
  "payment_hcc_count_bucket",
  "DISABL",
  "ORIGDIS",
  "LTIMCAID",
  "OriginallyDisabled_Female",
  "OriginallyDisabled_Male",
)

ESRD_PREDICTOR_BASE_COLUMNS = (
  "subject_id",
  "model_version",
  "age",
  "sex",
  "original_reason_entitlement_code",
  "medicaid_flag",
  "new_enrollee_medicaid_flag",
  "full_benefit_dual_flag",
  "partial_benefit_dual_flag",
  "long_term_institutional_flag",
  "is_disabled",
  "is_originally_disabled",
  "ce_age_sex_cell",
  "ne_age_sex_cell",
  "ne_graft_age_sex_cell",
  "mapped_cc_count",
  "active_hcc_count",
  "diagnosis_category_count",
  "interaction_count",
  "payment_hcc_count",
  "payment_hcc_count_bucket",
  "DISABL",
  "ORIGDIS",
  "ORIGESRD",
  "Aged",
  "NonAged",
  "OriginallyDisabled_Female",
  "OriginallyDisabled_Male",
  "Originally_ESRD_Female",
  "Originally_ESRD_Male",
)

RXHCC_PREDICTOR_BASE_COLUMNS = (
  "subject_id",
  "model_version",
  "age",
  "sex",
  "original_reason_entitlement_code",
  "concurrent_esrd_flag",
  "is_disabled",
  "is_originally_disabled",
  "ce_age_sex_cell",
  "ne_age_sex_cell",
  "mapped_cc_count",
  "active_hcc_count",
  "diagnosis_category_count",
  "interaction_count",
  "payment_hcc_count",
  "payment_hcc_count_bucket",
  "DISABLED",
  "ORIGDIS",
  "NONAGED",
  "OD65",
  "M65OD",
  "F65OD",
  "RXHCC_COUNT5",
  "RXHCC_COUNT6",
  "RXHCC_COUNT7",
  "RXHCC_COUNT8",
  "RXHCC_COUNT9",
  "RXHCC_COUNT10P",
)

ELIXHAUSER_PREDICTOR_BASE_COLUMNS = (
  "subject_id",
  "model_version",
  "mapped_comorbidity_count",
  "poa_available",
)

DIAGNOSIS_MAPPING_COLUMNS = (
  "subject_id",
  "icd10_code",
  "service_date",
  "claim_id",
  "source",
  "mapped_cc",
  "mapped_hcc",
  "mapping_status",
  "applied_mce_edits",
  "applied_age_edit",
  "applied_sex_edit",
)

ELIXHAUSER_DIAGNOSIS_MAPPING_COLUMNS = (
  "subject_id",
  "icd10_code",
  "service_date",
  "claim_id",
  "source",
  "diagnosis_sequence",
  "present_on_admission",
  "mapped_comorbidity",
  "mapping_status",
  "poa_required",
  "poa_exempt",
)

HIERARCHY_COLUMNS = (
  "subject_id",
  "mapped_cc",
  "mapped_hcc",
  "mapping_status",
  "hierarchy_status",
  "recode_note",
  "is_active_hcc",
)

INTERACTION_DETAIL_COLUMNS = (
  "subject_id",
  "detail_type",
  "detail_name",
  "detail_value",
  "detail_status",
)


def derive_subject_flags(
  request: ScoringRequest,
  model_spec: ModelSpec,
) -> TableArtifact:
  """Derive subject demographic scaffolding and stable predictor columns."""
  if model_spec.family == "cms_hcc":
    return _derive_cms_hcc_subject_flags(request, model_spec)
  if model_spec.family == "esrd":
    return _derive_esrd_subject_flags(request, model_spec)
  if model_spec.family == "rxhcc":
    return _derive_rxhcc_subject_flags(request, model_spec)
  if model_spec.family == "ahrq_elixhauser":
    return _derive_elixhauser_subject_flags(request, model_spec)
  raise NotImplementedError(f"Unsupported predictor family: {model_spec.family}")


def _derive_cms_hcc_subject_flags(
  request: ScoringRequest,
  model_spec: ModelSpec,
) -> TableArtifact:
  """Derive subject demographic scaffolding for the CMS-HCC family."""
  model_tables = get_model_tables(model_spec.version_id)
  predictor_columns = _predictor_columns(model_spec)
  rows: list[ArtifactRow] = []
  for subject in request.subjects:
    age = _calculate_age(subject.date_of_birth, model_spec.cutoff_date)
    is_disabled = _is_disabled(subject, model_spec.cutoff_date)
    is_originally_disabled = _is_originally_disabled(subject, model_spec.cutoff_date)
    ce_age_sex_cell = _derive_ce_age_sex_cell(subject, model_spec.cutoff_date)
    ne_age_sex_cell = _derive_ne_age_sex_cell(subject, model_spec.cutoff_date)
    row: ArtifactRow = {column: 0 for column in predictor_columns}
    row.update(
      {
        "subject_id": subject.subject_id,
        "model_version": model_spec.version_id,
        "age": age,
        "sex": subject.sex,
        "original_reason_entitlement_code": subject.original_reason_entitlement_code,
        "limited_income_medicaid_flag": subject.limited_income_medicaid_flag,
        "new_enrollee_medicaid_flag": subject.new_enrollee_medicaid_flag,
        "is_disabled": is_disabled,
        "is_originally_disabled": is_originally_disabled,
        "ce_age_sex_cell": ce_age_sex_cell,
        "ne_age_sex_cell": ne_age_sex_cell,
        "mapped_cc_count": 0,
        "active_hcc_count": 0,
        "diagnosis_category_count": 0,
        "interaction_count": 0,
        "payment_hcc_count": 0,
        "payment_hcc_count_bucket": "0",
        "DISABL": int(is_disabled),
        "ORIGDIS": int(is_originally_disabled),
        "LTIMCAID": int(subject.limited_income_medicaid_flag or 0),
        "OriginallyDisabled_Female": int(subject.sex == 2 and is_originally_disabled),
        "OriginallyDisabled_Male": int(subject.sex == 1 and is_originally_disabled),
      },
    )
    _set_flag_if_exists(row, ce_age_sex_cell)
    row.update(_derive_cms_hcc_ne_factor_flags(subject, model_spec, model_tables.ne_factor_variables))
    rows.append(row)
  return TableArtifact(
    name="subject_predictors",
    columns=predictor_columns,
    rows=tuple(rows),
  )


def _derive_esrd_subject_flags(
  request: ScoringRequest,
  model_spec: ModelSpec,
) -> TableArtifact:
  """Derive subject demographic scaffolding for the ESRD family."""
  model_tables = get_model_tables(model_spec.version_id)
  predictor_columns = _predictor_columns(model_spec)
  rows: list[ArtifactRow] = []
  for subject in request.subjects:
    age = _calculate_age(subject.date_of_birth, model_spec.cutoff_date)
    is_disabled = _is_disabled(subject, model_spec.cutoff_date)
    is_originally_disabled = _is_originally_disabled(subject, model_spec.cutoff_date)
    ce_age_sex_cell = _derive_ce_age_sex_cell(subject, model_spec.cutoff_date)
    ne_age_sex_cell = _derive_esrd_ne_age_sex_cell(subject, model_spec.cutoff_date)
    ne_graft_age_sex_cell = _derive_esrd_ne_graft_age_sex_cell(subject, model_spec.cutoff_date)
    is_aged = int(age is not None and age >= 65)
    is_nonaged = int(age is not None and age < 65)
    is_original_esrd = int(subject.original_reason_entitlement_code in {2, 3})
    row: ArtifactRow = {column: 0 for column in predictor_columns}
    row.update(
      {
        "subject_id": subject.subject_id,
        "model_version": model_spec.version_id,
        "age": age,
        "sex": subject.sex,
        "original_reason_entitlement_code": subject.original_reason_entitlement_code,
        "medicaid_flag": subject.medicaid_flag,
        "new_enrollee_medicaid_flag": subject.new_enrollee_medicaid_flag,
        "full_benefit_dual_flag": subject.full_benefit_dual_flag,
        "partial_benefit_dual_flag": subject.partial_benefit_dual_flag,
        "long_term_institutional_flag": subject.long_term_institutional_flag,
        "is_disabled": is_disabled,
        "is_originally_disabled": is_originally_disabled,
        "ce_age_sex_cell": ce_age_sex_cell,
        "ne_age_sex_cell": ne_age_sex_cell,
        "ne_graft_age_sex_cell": ne_graft_age_sex_cell,
        "mapped_cc_count": 0,
        "active_hcc_count": 0,
        "diagnosis_category_count": 0,
        "interaction_count": 0,
        "payment_hcc_count": 0,
        "payment_hcc_count_bucket": "0",
        "DISABL": int(is_disabled),
        "ORIGDIS": int(is_originally_disabled),
        "ORIGESRD": is_original_esrd,
        "Aged": is_aged,
        "NonAged": is_nonaged,
        "OriginallyDisabled_Female": int(subject.sex == 2 and is_originally_disabled),
        "OriginallyDisabled_Male": int(subject.sex == 1 and is_originally_disabled),
        "Originally_ESRD_Female": int(subject.sex == 2 and is_original_esrd and is_aged),
        "Originally_ESRD_Male": int(subject.sex == 1 and is_original_esrd and is_aged),
      },
    )
    _set_flag_if_exists(row, ce_age_sex_cell)
    if model_spec.version_id == "esrd_v21_2026":
      row.update(_derive_esrd_v21_ce_flags(subject, is_aged, is_nonaged))
      row.update(
        _derive_esrd_v21_ne_factor_flags(
          subject,
          model_spec,
          model_tables.ne_factor_variables,
          ne_age_sex_cell=ne_age_sex_cell,
          ne_graft_age_sex_cell=ne_graft_age_sex_cell,
        ),
      )
    else:
      row.update(_derive_esrd_v24_ce_flags(subject, is_aged, is_nonaged))
      row.update(
        _derive_esrd_v24_ne_factor_flags(
          subject,
          model_spec,
          model_tables.ne_factor_variables,
          ne_age_sex_cell=ne_age_sex_cell,
          ne_graft_age_sex_cell=ne_graft_age_sex_cell,
        ),
      )
    rows.append(row)
  return TableArtifact(
    name="subject_predictors",
    columns=predictor_columns,
    rows=tuple(rows),
  )


def _derive_rxhcc_subject_flags(
  request: ScoringRequest,
  model_spec: ModelSpec,
) -> TableArtifact:
  """Derive subject demographic scaffolding for the RxHCC family."""
  predictor_columns = _predictor_columns(model_spec)
  rows: list[ArtifactRow] = []
  for subject in request.subjects:
    age = _calculate_age(subject.date_of_birth, model_spec.cutoff_date)
    is_disabled = _is_disabled(subject, model_spec.cutoff_date)
    is_originally_disabled = _is_originally_disabled(subject, model_spec.cutoff_date)
    ce_age_sex_cell = _derive_ce_age_sex_cell(subject, model_spec.cutoff_date)
    ne_age_sex_cell = _derive_ne_age_sex_cell(subject, model_spec.cutoff_date)
    row: ArtifactRow = {column: 0 for column in predictor_columns}
    row.update(
      {
        "subject_id": subject.subject_id,
        "model_version": model_spec.version_id,
        "age": age,
        "sex": subject.sex,
        "original_reason_entitlement_code": subject.original_reason_entitlement_code,
        "concurrent_esrd_flag": subject.concurrent_esrd_flag,
        "is_disabled": is_disabled,
        "is_originally_disabled": is_originally_disabled,
        "ce_age_sex_cell": ce_age_sex_cell,
        "ne_age_sex_cell": ne_age_sex_cell,
        "mapped_cc_count": 0,
        "active_hcc_count": 0,
        "diagnosis_category_count": 0,
        "interaction_count": 0,
        "payment_hcc_count": 0,
        "payment_hcc_count_bucket": "0",
        "DISABLED": int(is_disabled),
        "ORIGDIS": int(is_originally_disabled),
        "NONAGED": int(age is not None and age < 65),
        "OD65": int(age is not None and age >= 65 and is_originally_disabled),
      },
    )
    _set_flag_if_exists(row, ce_age_sex_cell)
    if row["OD65"]:
      _set_flag_if_exists(row, "M65OD", int(subject.sex == 1))
      _set_flag_if_exists(row, "F65OD", int(subject.sex == 2))
    ne_variable = _derive_rxhcc_ne_factor_variable(subject, model_spec)
    _set_flag_if_exists(row, ne_variable)
    rows.append(row)
  return TableArtifact(
    name="subject_predictors",
    columns=predictor_columns,
    rows=tuple(rows),
  )


def _derive_elixhauser_subject_flags(
  request: ScoringRequest,
  model_spec: ModelSpec,
) -> TableArtifact:
  """Build the base subject rows for AHRQ Elixhauser measure assignment."""
  model_tables = get_elixhauser_tables(model_spec.version_id)
  columns = _predictor_columns(model_spec)
  rows: list[ArtifactRow] = []
  for subject in request.subjects:
    row: ArtifactRow = {column: 0 for column in columns}
    row.update(
      {
        "subject_id": subject.subject_id,
        "model_version": model_spec.version_id,
        "mapped_comorbidity_count": 0,
        "poa_available": int(
          any(
            diagnosis.subject_id == subject.subject_id
            and diagnosis.present_on_admission is not None
            for diagnosis in request.diagnoses
          ),
        ),
      },
    )
    for measure in model_tables.measures:
      if measure.uses_poa and not row["poa_available"]:
        row[measure.measure] = None
    rows.append(row)
  return TableArtifact(
    name="subject_predictors",
    columns=columns,
    rows=tuple(rows),
  )


def map_diagnoses_to_ccs(
  request: ScoringRequest,
  model_spec: ModelSpec,
) -> TableArtifact:
  """Produce the long diagnosis mapping audit artifact."""
  if model_spec.family == "ahrq_elixhauser":
    return _map_diagnoses_to_elixhauser(request, model_spec)
  model_tables = get_model_tables(model_spec.version_id)
  subjects_by_id = {subject.subject_id: subject for subject in request.subjects}
  rows: list[ArtifactRow] = []
  for diagnosis in request.diagnoses:
    subject = subjects_by_id.get(diagnosis.subject_id)
    if subject is None:
      rows.append(
        {
          "subject_id": diagnosis.subject_id,
          "icd10_code": diagnosis.icd10_code,
          "service_date": diagnosis.service_date,
          "claim_id": diagnosis.claim_id,
          "source": diagnosis.source,
          "mapped_cc": None,
          "mapped_hcc": None,
          "mapping_status": "unknown_subject",
          "applied_mce_edits": False,
          "applied_age_edit": False,
          "applied_sex_edit": False,
        },
      )
      continue
    age = _calculate_age(subject.date_of_birth, model_spec.cutoff_date)
    sex = subject.sex
    rules = model_tables.mapping_rules_by_icd10.get(diagnosis.icd10_code.upper(), ())
    if not rules:
      rows.append(
        {
          "subject_id": diagnosis.subject_id,
          "icd10_code": diagnosis.icd10_code,
          "service_date": diagnosis.service_date,
          "claim_id": diagnosis.claim_id,
          "source": diagnosis.source,
          "mapped_cc": None,
          "mapped_hcc": None,
          "mapping_status": "unmapped_icd10",
          "applied_mce_edits": False,
          "applied_age_edit": False,
          "applied_sex_edit": False,
        },
      )
      continue
    for rule in rules:
      mapping_status = _evaluate_mapping_status(rule, age, sex, request.options.apply_mce_edits)
      rows.append(
        {
          "subject_id": diagnosis.subject_id,
          "icd10_code": diagnosis.icd10_code,
          "service_date": diagnosis.service_date,
          "claim_id": diagnosis.claim_id,
          "source": diagnosis.source,
          "mapped_cc": rule.cc,
          "mapped_hcc": rule.hcc,
          "mapping_status": mapping_status,
          "applied_mce_edits": bool(request.options.apply_mce_edits and rule.mce_age_condition),
          "applied_age_edit": rule.age_edit_condition is not None,
          "applied_sex_edit": rule.sex_edit_condition is not None,
        },
      )
  return TableArtifact(
    name="diagnosis_mappings",
    columns=DIAGNOSIS_MAPPING_COLUMNS,
    rows=tuple(rows),
  )


def _map_diagnoses_to_elixhauser(
  request: ScoringRequest,
  model_spec: ModelSpec,
) -> TableArtifact:
  """Produce the long AHRQ Elixhauser diagnosis-to-comorbidity mapping audit."""
  model_tables = get_elixhauser_tables(model_spec.version_id)
  subject_ids = {subject.subject_id for subject in request.subjects}
  measures_by_name = {measure.measure: measure for measure in model_tables.measures}
  rows: list[ArtifactRow] = []
  for diagnosis in request.diagnoses:
    base_row: ArtifactRow = {
      "subject_id": diagnosis.subject_id,
      "icd10_code": diagnosis.icd10_code,
      "service_date": diagnosis.service_date,
      "claim_id": diagnosis.claim_id,
      "source": diagnosis.source,
      "diagnosis_sequence": diagnosis.diagnosis_sequence,
      "present_on_admission": diagnosis.present_on_admission,
      "mapped_comorbidity": None,
      "mapping_status": "mapped",
      "poa_required": False,
      "poa_exempt": False,
    }
    if diagnosis.subject_id not in subject_ids:
      rows.append({**base_row, "mapping_status": "unknown_subject"})
      continue
    if diagnosis.diagnosis_sequence == 1:
      rows.append({**base_row, "mapping_status": "primary_diagnosis_excluded"})
      continue
    rules = model_tables.mappings_by_icd10.get(diagnosis.icd10_code.upper(), ())
    if not rules:
      rows.append({**base_row, "mapping_status": "unmapped_icd10"})
      continue
    icd_version = _icd10_version_for_service_date(diagnosis.service_date)
    poa_exempt = diagnosis.icd10_code.upper() in model_tables.poa_exemptions_by_version.get(
      icd_version,
      frozenset(),
    )
    for rule in rules:
      measure = measures_by_name[rule.measure]
      rows.append(
        {
          **base_row,
          "mapped_comorbidity": rule.measure,
          "mapping_status": _elixhauser_mapping_status(
            uses_poa=measure.uses_poa,
            poa_value=diagnosis.present_on_admission,
            poa_exempt=poa_exempt,
          ),
          "poa_required": measure.uses_poa,
          "poa_exempt": poa_exempt,
        },
      )
  return TableArtifact(
    name="diagnosis_mappings",
    columns=ELIXHAUSER_DIAGNOSIS_MAPPING_COLUMNS,
    rows=tuple(rows),
  )


def resolve_hcc_hierarchies(
  diagnosis_mappings: TableArtifact,
  model_spec: ModelSpec,
) -> TableArtifact:
  """Produce hierarchy and recode state from diagnosis mappings."""
  if model_spec.family == "ahrq_elixhauser":
    return TableArtifact.empty("hierarchy_effects", HIERARCHY_COLUMNS)
  model_tables = get_model_tables(model_spec.version_id)
  mapped_hccs_by_subject: dict[str, set[str]] = defaultdict(set)
  for row in diagnosis_mappings.rows:
    if row.get("mapping_status") == "mapped" and row.get("mapped_hcc"):
      mapped_hccs_by_subject[str(row["subject_id"])].add(str(row["mapped_hcc"]))

  active_hccs_by_subject = {
    subject_id: _resolve_active_hccs(mapped_hccs, model_tables.hierarchy_rules)
    for subject_id, mapped_hccs in mapped_hccs_by_subject.items()
  }
  suppressors_by_subject = {
    subject_id: _suppressed_hcc_sources(mapped_hccs, model_tables.hierarchy_rules)
    for subject_id, mapped_hccs in mapped_hccs_by_subject.items()
  }

  rows: list[ArtifactRow] = []
  for mapping_row in diagnosis_mappings.rows:
    subject_id = str(mapping_row["subject_id"])
    mapped_cc = mapping_row.get("mapped_cc")
    mapped_hcc = mapping_row.get("mapped_hcc")
    mapping_status = str(mapping_row.get("mapping_status"))
    if mapping_status != "mapped" or mapped_hcc is None:
      rows.append(
        {
          "subject_id": subject_id,
          "mapped_cc": mapped_cc,
          "mapped_hcc": mapped_hcc,
          "mapping_status": mapping_status,
          "hierarchy_status": "not_applicable",
          "recode_note": mapping_status,
          "is_active_hcc": False,
        },
      )
      continue
    active_hccs = active_hccs_by_subject.get(subject_id, set())
    suppressors = suppressors_by_subject.get(subject_id, {})
    if mapped_hcc in active_hccs:
      hierarchy_status = "active"
      recode_note = "retained"
      is_active_hcc = True
    else:
      suppressor = suppressors.get(str(mapped_hcc))
      hierarchy_status = "suppressed"
      recode_note = f"suppressed_by_{suppressor}" if suppressor else "suppressed"
      is_active_hcc = False
    rows.append(
      {
        "subject_id": subject_id,
        "mapped_cc": mapped_cc,
        "mapped_hcc": mapped_hcc,
        "mapping_status": mapping_status,
        "hierarchy_status": hierarchy_status,
        "recode_note": recode_note,
        "is_active_hcc": is_active_hcc,
      },
    )
  return TableArtifact(
    name="hierarchy_effects",
    columns=HIERARCHY_COLUMNS,
    rows=tuple(rows),
  )


def derive_interactions(
  subject_flags: TableArtifact,
  hierarchy_artifact: TableArtifact,
  model_spec: ModelSpec,
) -> TableArtifact:
  """Add stable derived-count and interaction summary columns."""
  if model_spec.family in {"cms_hcc", "esrd"}:
    return _derive_hcc_family_interactions(subject_flags, hierarchy_artifact, model_spec)
  if model_spec.family == "rxhcc":
    return _derive_rxhcc_predictors(subject_flags, hierarchy_artifact, model_spec)
  if model_spec.family == "ahrq_elixhauser":
    return _derive_elixhauser_predictors(subject_flags, hierarchy_artifact, model_spec)
  raise NotImplementedError(f"Unsupported predictor family: {model_spec.family}")


def _derive_hcc_family_interactions(
  subject_flags: TableArtifact,
  hierarchy_artifact: TableArtifact,
  model_spec: ModelSpec,
) -> TableArtifact:
  """Add HCC-family category, interaction, and count predictor columns."""
  model_tables = get_model_tables(model_spec.version_id)
  predictor_columns = _predictor_columns(model_spec)
  mapped_ccs_by_subject, active_hccs_by_subject = _mapped_and_active_sets(hierarchy_artifact)

  rows: list[ArtifactRow] = []
  for row in subject_flags.rows:
    subject_id = str(row["subject_id"])
    updated_row: ArtifactRow = dict(row)
    mapped_ccs = mapped_ccs_by_subject.get(subject_id, set())
    active_hccs = active_hccs_by_subject.get(subject_id, set())
    for hcc in model_tables.hcc_variables:
      updated_row[hcc] = int(hcc in active_hccs)
    for category_name, hccs in model_tables.diagnosis_categories.items():
      updated_row[category_name] = int(any(hcc in active_hccs for hcc in hccs))
    _set_count_variables(updated_row, model_tables.count_variables, len(active_hccs))
    for interaction_rule in model_tables.interaction_rules:
      updated_row[interaction_rule.name] = int(
        bool(updated_row.get(interaction_rule.left_variable, 0))
        and bool(updated_row.get(interaction_rule.right_variable, 0))
      )
    updated_row["mapped_cc_count"] = len(mapped_ccs)
    updated_row["active_hcc_count"] = len(active_hccs)
    updated_row["diagnosis_category_count"] = sum(
      1
      for category_name in model_tables.diagnosis_category_variables
      if bool(updated_row.get(category_name, 0))
    )
    updated_row["interaction_count"] = sum(
      1
      for interaction_name in model_tables.interaction_variables
      if bool(updated_row.get(interaction_name, 0))
    )
    updated_row["payment_hcc_count"] = len(active_hccs)
    updated_row["payment_hcc_count_bucket"] = _payment_hcc_count_bucket(len(active_hccs))
    rows.append({column: updated_row.get(column) for column in predictor_columns})

  return TableArtifact(
    name="subject_predictors",
    columns=predictor_columns,
    rows=tuple(rows),
  )


def _derive_rxhcc_predictors(
  subject_flags: TableArtifact,
  hierarchy_artifact: TableArtifact,
  model_spec: ModelSpec,
) -> TableArtifact:
  """Add RxHCC active HCC flags, count buckets, and nonaged overlays."""
  model_tables = get_model_tables(model_spec.version_id)
  predictor_columns = _predictor_columns(model_spec)
  mapped_ccs_by_subject, active_hccs_by_subject = _mapped_and_active_sets(hierarchy_artifact)
  nonaged_overlay_variables = tuple(
    variable for variable in model_tables.factor_variables if variable.startswith("NONAGED_RXHCC")
  )

  rows: list[ArtifactRow] = []
  for row in subject_flags.rows:
    subject_id = str(row["subject_id"])
    updated_row: ArtifactRow = dict(row)
    mapped_ccs = mapped_ccs_by_subject.get(subject_id, set())
    active_hccs = active_hccs_by_subject.get(subject_id, set())
    for hcc in model_tables.hcc_variables:
      updated_row[hcc] = int(hcc in active_hccs)
    for overlay_variable in nonaged_overlay_variables:
      base_hcc = overlay_variable.removeprefix("NONAGED_")
      updated_row[overlay_variable] = int(
        bool(updated_row.get("NONAGED", 0)) and base_hcc in active_hccs
      )
    _set_rxhcc_count_variables(updated_row, len(active_hccs))
    updated_row["mapped_cc_count"] = len(mapped_ccs)
    updated_row["active_hcc_count"] = len(active_hccs)
    updated_row["diagnosis_category_count"] = 0
    updated_row["interaction_count"] = 0
    updated_row["payment_hcc_count"] = len(active_hccs)
    updated_row["payment_hcc_count_bucket"] = _payment_hcc_count_bucket(len(active_hccs))
    rows.append({column: updated_row.get(column) for column in predictor_columns})

  return TableArtifact(
    name="subject_predictors",
    columns=predictor_columns,
    rows=tuple(rows),
  )


def _derive_elixhauser_predictors(
  subject_flags: TableArtifact,
  diagnosis_mappings: TableArtifact,
  model_spec: ModelSpec,
) -> TableArtifact:
  """Aggregate mapped diagnosis rows into AHRQ Elixhauser comorbidity flags."""
  del model_spec
  columns = subject_flags.columns
  mapped_measures_by_subject: dict[str, set[str]] = defaultdict(set)
  for row in diagnosis_mappings.rows:
    if row.get("mapping_status") == "mapped" and row.get("mapped_comorbidity"):
      mapped_measures_by_subject[str(row["subject_id"])].add(str(row["mapped_comorbidity"]))

  rows: list[ArtifactRow] = []
  for row in subject_flags.rows:
    subject_id = str(row["subject_id"])
    updated_row = dict(row)
    active_measures = _apply_elixhauser_exclusions(
      mapped_measures_by_subject.get(subject_id, set()),
    )
    for measure in active_measures:
      updated_row[measure] = 1
    updated_row["mapped_comorbidity_count"] = len(active_measures)
    rows.append({column: updated_row.get(column) for column in columns})
  return TableArtifact(
    name="subject_predictors",
    columns=columns,
    rows=tuple(rows),
  )


def build_interaction_details(
  subject_predictors: TableArtifact,
  model_spec: ModelSpec,
) -> TableArtifact:
  """Build a subject-level interaction and derived-detail artifact."""
  if model_spec.family in {"cms_hcc", "esrd"}:
    return _build_hcc_family_interaction_details(subject_predictors, model_spec)
  if model_spec.family == "rxhcc":
    return _build_rxhcc_interaction_details(subject_predictors, model_spec)
  if model_spec.family == "ahrq_elixhauser":
    return _build_elixhauser_interaction_details(subject_predictors, model_spec)
  raise NotImplementedError(f"Unsupported predictor family: {model_spec.family}")


def _build_hcc_family_interaction_details(
  subject_predictors: TableArtifact,
  model_spec: ModelSpec,
) -> TableArtifact:
  """Build interaction details for HCC-based families."""
  model_tables = get_model_tables(model_spec.version_id)
  rows: list[ArtifactRow] = []
  for row in subject_predictors.rows:
    subject_id = row["subject_id"]
    for hcc in model_tables.hcc_variables:
      if row.get(hcc):
        rows.append(
          {
            "subject_id": subject_id,
            "detail_type": "active_hcc",
            "detail_name": hcc,
            "detail_value": row[hcc],
            "detail_status": "active",
          },
        )
    for category_name in model_tables.diagnosis_category_variables:
      if row.get(category_name):
        rows.append(
          {
            "subject_id": subject_id,
            "detail_type": "diagnosis_category",
            "detail_name": category_name,
            "detail_value": row[category_name],
            "detail_status": "active",
          },
        )
    for interaction_name in model_tables.interaction_variables:
      if row.get(interaction_name):
        rows.append(
          {
            "subject_id": subject_id,
            "detail_type": "interaction",
            "detail_name": interaction_name,
            "detail_value": row[interaction_name],
            "detail_status": "active",
          },
        )
    rows.extend(_summary_detail_rows(row))
  return TableArtifact(
    name="interaction_details",
    columns=INTERACTION_DETAIL_COLUMNS,
    rows=tuple(rows),
  )


def _build_rxhcc_interaction_details(
  subject_predictors: TableArtifact,
  model_spec: ModelSpec,
) -> TableArtifact:
  """Build active-HCC and summary details for RxHCC explanation outputs."""
  model_tables = get_model_tables(model_spec.version_id)
  rows: list[ArtifactRow] = []
  for row in subject_predictors.rows:
    subject_id = row["subject_id"]
    for hcc in model_tables.hcc_variables:
      if row.get(hcc):
        rows.append(
          {
            "subject_id": subject_id,
            "detail_type": "active_hcc",
            "detail_name": hcc,
            "detail_value": row[hcc],
            "detail_status": "active",
          },
        )
    rows.extend(_summary_detail_rows(row))
  return TableArtifact(
    name="interaction_details",
    columns=INTERACTION_DETAIL_COLUMNS,
    rows=tuple(rows),
  )


def _build_elixhauser_interaction_details(
  subject_predictors: TableArtifact,
  model_spec: ModelSpec,
) -> TableArtifact:
  """Build active comorbidity details for AHRQ Elixhauser explanation outputs."""
  model_tables = get_elixhauser_tables(model_spec.version_id)
  rows: list[ArtifactRow] = []
  for row in subject_predictors.rows:
    subject_id = row["subject_id"]
    for measure in model_tables.measures:
      if row.get(measure.measure):
        rows.append(
          {
            "subject_id": subject_id,
            "detail_type": "comorbidity_measure",
            "detail_name": measure.measure,
            "detail_value": row[measure.measure],
            "detail_status": "active",
          },
        )
  return TableArtifact(
    name="interaction_details",
    columns=INTERACTION_DETAIL_COLUMNS,
    rows=tuple(rows),
  )


def _predictor_columns(model_spec: ModelSpec) -> tuple[str, ...]:
  """Return stable subject predictor columns for the resolved model version."""
  if model_spec.family == "ahrq_elixhauser":
    return (
      *ELIXHAUSER_PREDICTOR_BASE_COLUMNS,
      *(measure.measure for measure in get_elixhauser_tables(model_spec.version_id).measures),
    )
  model_tables = get_model_tables(model_spec.version_id)
  base_columns = _predictor_base_columns(model_spec)
  dynamic_columns = []
  for column in (
    *model_tables.factor_variables,
    *model_tables.hcc_variables,
    *model_tables.diagnosis_category_variables,
    *model_tables.interaction_variables,
    *model_tables.count_variables,
  ):
    if column not in base_columns and column not in dynamic_columns:
      dynamic_columns.append(column)
  return (*base_columns, *dynamic_columns)


def _predictor_base_columns(model_spec: ModelSpec) -> tuple[str, ...]:
  """Return the family-specific stable predictor columns."""
  if model_spec.family == "cms_hcc":
    return CMS_HCC_PREDICTOR_BASE_COLUMNS
  if model_spec.family == "esrd":
    return ESRD_PREDICTOR_BASE_COLUMNS
  if model_spec.family == "rxhcc":
    return RXHCC_PREDICTOR_BASE_COLUMNS
  if model_spec.family == "ahrq_elixhauser":
    return ELIXHAUSER_PREDICTOR_BASE_COLUMNS
  raise NotImplementedError(f"Unsupported predictor family: {model_spec.family}")


def _derive_cms_hcc_ne_factor_flags(
  subject: SubjectRecord,
  model_spec: ModelSpec,
  ne_factor_variables: tuple[str, ...],
) -> ArtifactRow:
  """Derive CMS-HCC new-enrollee factor flags in factor-table naming."""
  flags: ArtifactRow = {variable_name: 0 for variable_name in ne_factor_variables}
  ne_age_sex_cell = _derive_ne_age_sex_cell(subject, model_spec.cutoff_date)
  if ne_age_sex_cell is None:
    return flags
  age = _calculate_age(subject.date_of_birth, model_spec.cutoff_date)
  if age is None:
    return flags
  is_ne_originally_disabled = int(
    subject.original_reason_entitlement_code == 1 and age >= 65,
  )
  has_new_enrollee_medicaid = int(subject.new_enrollee_medicaid_flag or 0)
  interaction_prefix = (
    "MCAID_ORIGDIS"
    if has_new_enrollee_medicaid and is_ne_originally_disabled
    else "NMCAID_ORIGDIS"
    if is_ne_originally_disabled
    else "MCAID_NORIGDIS"
    if has_new_enrollee_medicaid
    else "NMCAID_NORIGDIS"
  )
  _set_flag_if_exists(flags, f"{interaction_prefix}_{ne_age_sex_cell}")
  return flags


def _derive_esrd_v21_ce_flags(
  subject: SubjectRecord,
  is_aged: int,
  is_nonaged: int,
) -> ArtifactRow:
  """Derive ESRD v21 CE-only demographic interaction flags."""
  medicaid_flag = int(subject.medicaid_flag or 0)
  sex_label = _sex_label(subject.sex)
  flags: ArtifactRow = {
    "MCAID": medicaid_flag,
  }
  if sex_label is not None:
    flags[f"MCAID_{sex_label}_{'Aged' if is_aged else 'NonAged'}"] = medicaid_flag
  return flags


def _derive_esrd_v24_ce_flags(
  subject: SubjectRecord,
  is_aged: int,
  is_nonaged: int,
) -> ArtifactRow:
  """Derive ESRD v24 CE-only demographic interaction flags."""
  sex_label = _sex_label(subject.sex)
  full_dual = int(subject.full_benefit_dual_flag or 0)
  partial_dual = int(subject.partial_benefit_dual_flag or 0)
  lti = int(subject.long_term_institutional_flag or 0)
  flags: ArtifactRow = {
    "LTI_Aged": lti * is_aged,
    "LTI_NonAged": lti * is_nonaged,
  }
  if sex_label is not None:
    flags[f"FBDual_{sex_label}_{'Aged' if is_aged else 'NonAged'}"] = full_dual
    flags[f"PBDual_{sex_label}_{'Aged' if is_aged else 'NonAged'}"] = partial_dual
  return flags


def _derive_esrd_v21_ne_factor_flags(
  subject: SubjectRecord,
  model_spec: ModelSpec,
  ne_factor_variables: tuple[str, ...],
  *,
  ne_age_sex_cell: str | None,
  ne_graft_age_sex_cell: str | None,
) -> ArtifactRow:
  """Derive ESRD v21 NE dialysis and graft factor flags."""
  flags: ArtifactRow = {variable_name: 0 for variable_name in ne_factor_variables}
  age = _calculate_age(subject.date_of_birth, model_spec.cutoff_date)
  if age is None:
    return flags
  has_new_enrollee_medicaid = int(subject.new_enrollee_medicaid_flag or 0)
  is_ne_originally_disabled = int(subject.original_reason_entitlement_code == 1)
  is_ne_graft_originally_disabled = int(subject.original_reason_entitlement_code == 1 and age >= 65)
  if ne_age_sex_cell is not None:
    prefix = _esrd_v21_ne_prefix(has_new_enrollee_medicaid, is_ne_originally_disabled, graft=False)
    _set_flag_if_exists(flags, f"{prefix}_{ne_age_sex_cell}")
  if ne_graft_age_sex_cell is not None:
    prefix = _esrd_v21_ne_prefix(has_new_enrollee_medicaid, is_ne_graft_originally_disabled, graft=True)
    _set_flag_if_exists(flags, f"{prefix}_{ne_graft_age_sex_cell}")
  return flags


def _derive_esrd_v24_ne_factor_flags(
  subject: SubjectRecord,
  model_spec: ModelSpec,
  ne_factor_variables: tuple[str, ...],
  *,
  ne_age_sex_cell: str | None,
  ne_graft_age_sex_cell: str | None,
) -> ArtifactRow:
  """Derive ESRD v24 NE dialysis and graft factor flags."""
  flags: ArtifactRow = {variable_name: 0 for variable_name in ne_factor_variables}
  age = _calculate_age(subject.date_of_birth, model_spec.cutoff_date)
  if age is None:
    return flags
  has_full_dual = int(subject.full_benefit_dual_flag or 0)
  is_ne_originally_disabled = int(subject.original_reason_entitlement_code == 1)
  is_ne_graft_originally_disabled = int(subject.original_reason_entitlement_code == 1 and age >= 65)
  if ne_age_sex_cell is not None:
    prefix = _esrd_v24_ne_prefix(has_full_dual, is_ne_originally_disabled, graft=False)
    _set_flag_if_exists(flags, f"{prefix}_{ne_age_sex_cell}")
  if ne_graft_age_sex_cell is not None:
    prefix = _esrd_v24_ne_prefix(has_full_dual, is_ne_graft_originally_disabled, graft=True)
    _set_flag_if_exists(flags, f"{prefix}_{ne_graft_age_sex_cell}")
  return flags


def _derive_rxhcc_ne_factor_variable(
  subject: SubjectRecord,
  model_spec: ModelSpec,
) -> str | None:
  """Return the one active RxHCC NE demographic factor variable."""
  ne_age_sex_cell = _derive_ne_age_sex_cell(subject, model_spec.cutoff_date)
  age = _calculate_age(subject.date_of_birth, model_spec.cutoff_date)
  if ne_age_sex_cell is None or age is None:
    return None
  recoded_age = 65 if age == 64 and subject.original_reason_entitlement_code == 0 else age
  concurrent_esrd = int(subject.concurrent_esrd_flag or 0)
  originally_disabled = int(
    subject.original_reason_entitlement_code == 1 and recoded_age >= 65
  )
  if recoded_age < 65:
    prefix = "ESRD_NORIGDIS_X" if concurrent_esrd else "NESRD_NORIGDIS_X"
  elif concurrent_esrd and originally_disabled:
    prefix = "ESRD_ORIGDIS_X"
  elif originally_disabled:
    prefix = "NESRD_ORIGDIS_X"
  elif concurrent_esrd:
    prefix = "ESRD_NORIGDIS_X"
  else:
    prefix = "NESRD_NORIGDIS_X"
  return f"{prefix}_{ne_age_sex_cell.removeprefix('NE')}"


def _mapped_and_active_sets(
  hierarchy_artifact: TableArtifact,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
  """Return mapped CC and active HCC sets keyed by subject."""
  mapped_ccs_by_subject: dict[str, set[str]] = defaultdict(set)
  active_hccs_by_subject: dict[str, set[str]] = defaultdict(set)
  for row in hierarchy_artifact.rows:
    subject_id = str(row["subject_id"])
    if row.get("mapping_status") == "mapped" and row.get("mapped_cc"):
      mapped_ccs_by_subject[subject_id].add(str(row["mapped_cc"]))
    if row.get("is_active_hcc") and row.get("mapped_hcc"):
      active_hccs_by_subject[subject_id].add(str(row["mapped_hcc"]))
  return mapped_ccs_by_subject, active_hccs_by_subject


def _set_count_variables(
  row: ArtifactRow,
  count_variables: tuple[str, ...],
  active_hcc_count: int,
) -> None:
  """Set CMS-HCC count-bucket variables when the model exposes them."""
  for variable in count_variables:
    if variable == "D10P":
      row[variable] = int(active_hcc_count >= 10)
      continue
    if variable.startswith("D") and variable[1:].isdigit():
      row[variable] = int(active_hcc_count == int(variable[1:]))


def _set_rxhcc_count_variables(row: ArtifactRow, active_hcc_count: int) -> None:
  """Set RxHCC count-bucket variables for 5 through 10+ active HCCs."""
  row["RXHCC_COUNT5"] = int(active_hcc_count == 5)
  row["RXHCC_COUNT6"] = int(active_hcc_count == 6)
  row["RXHCC_COUNT7"] = int(active_hcc_count == 7)
  row["RXHCC_COUNT8"] = int(active_hcc_count == 8)
  row["RXHCC_COUNT9"] = int(active_hcc_count == 9)
  row["RXHCC_COUNT10P"] = int(active_hcc_count >= 10)


def _summary_detail_rows(row: ArtifactRow) -> tuple[ArtifactRow, ...]:
  """Return the stable summary detail rows for one subject predictor row."""
  return (
    {
      "subject_id": row["subject_id"],
      "detail_type": "summary",
      "detail_name": "payment_hcc_count",
      "detail_value": row["payment_hcc_count"],
      "detail_status": "derived",
    },
    {
      "subject_id": row["subject_id"],
      "detail_type": "summary",
      "detail_name": "payment_hcc_count_bucket",
      "detail_value": row["payment_hcc_count_bucket"],
      "detail_status": "derived",
    },
  )


def _set_flag_if_exists(row: ArtifactRow, variable_name: str | None, value: int = 1) -> None:
  """Set a factor flag only when the variable is present in the predictor row."""
  if variable_name and variable_name in row:
    row[variable_name] = int(value)


def _sex_label(sex: int | None) -> str | None:
  """Return the factor-table sex label used by ESRD demographic flags."""
  if sex == 1:
    return "Male"
  if sex == 2:
    return "Female"
  return None


def _esrd_v21_ne_prefix(
  has_new_enrollee_medicaid: int,
  is_ne_originally_disabled: int,
  *,
  graft: bool,
) -> str:
  """Return the ESRD v21 NE interaction prefix."""
  prefix = (
    "MCAID_ORIGDIS"
    if has_new_enrollee_medicaid and is_ne_originally_disabled
    else "NMCAID_ORIGDIS"
    if is_ne_originally_disabled
    else "MCAID_NORIGDIS"
    if has_new_enrollee_medicaid
    else "NMCAID_NORIGDIS"
  )
  return f"{prefix}_G" if graft else prefix


def _esrd_v24_ne_prefix(
  has_full_dual: int,
  is_ne_originally_disabled: int,
  *,
  graft: bool,
) -> str:
  """Return the ESRD v24 NE interaction prefix."""
  prefix = (
    "FBD_ORIGDIS"
    if has_full_dual and is_ne_originally_disabled
    else "ND_PBD_ORIGDIS"
    if is_ne_originally_disabled
    else "FBD_NORIGDIS"
    if has_full_dual
    else "ND_PBD_NORIGDIS"
  )
  return f"{prefix}_G" if graft else prefix


def _evaluate_mapping_status(
  rule: MappingRule,
  age: int | None,
  sex: int | None,
  apply_mce_edits: bool,
) -> str:
  """Evaluate one CMS mapping rule for a subject demographic profile."""
  if apply_mce_edits and rule.mce_age_condition and not _age_rule_matches(rule.mce_age_condition, age):
    return "mce_age_rejected"
  if rule.age_edit_condition and not _age_rule_matches(rule.age_edit_condition, age):
    return "age_edit_rejected"
  if rule.sex_edit_condition is not None and sex != rule.sex_edit_condition:
    return "sex_edit_rejected"
  return "mapped"


def _elixhauser_mapping_status(
  *,
  uses_poa: bool,
  poa_value: str | None,
  poa_exempt: bool,
) -> str:
  """Evaluate AHRQ Elixhauser POA-sensitive mapping status."""
  if not uses_poa:
    return "mapped"
  if poa_exempt:
    return "mapped"
  if poa_value is None:
    return "poa_unavailable"
  if poa_value in {"Y", "W"}:
    return "mapped"
  if poa_value in {"N", "U"}:
    return "not_present_on_admission"
  return "invalid_poa"


def _apply_elixhauser_exclusions(measures: set[str]) -> set[str]:
  """Apply AHRQ final comorbidity exclusion rules."""
  active_measures = set(measures)
  if "CMR_DIAB_CX" in active_measures:
    active_measures.discard("CMR_DIAB_UNCX")
  if "CMR_HTN_CX" in active_measures:
    active_measures.discard("CMR_HTN_UNCX")
  if "CMR_CANCER_METS" in active_measures:
    active_measures.discard("CMR_CANCER_SOLID")
    active_measures.discard("CMR_CANCER_NSITU")
  if "CMR_CANCER_SOLID" in active_measures:
    active_measures.discard("CMR_CANCER_NSITU")
  if "CMR_LIVER_SEV" in active_measures:
    active_measures.discard("CMR_LIVER_MLD")
  if "CMR_RENLFL_SEV" in active_measures:
    active_measures.discard("CMR_RENLFL_MOD")
  if "CMR_CBVD_POA" in active_measures or "CMR_CBVD_SQLA" in active_measures:
    active_measures.add("CMR_CBVD")
  active_measures.discard("CMR_CBVD_POA")
  active_measures.discard("CMR_CBVD_SQLA")
  return active_measures


def _icd10_version_for_service_date(service_date: date | None) -> int:
  """Return the AHRQ ICD-10-CM version bucket for a diagnosis service date."""
  if service_date is None:
    return 43
  year = service_date.year
  quarter = ((service_date.month - 1) // 3) + 1
  if year <= 2015:
    return 33
  if year >= 2026:
    return 43
  return year - 1982 if quarter == 4 else year - 1983


def _resolve_active_hccs(
  mapped_hccs: set[str],
  hierarchy_rules: dict[str, tuple[str, ...]],
) -> set[str]:
  """Return the active HCC set after hierarchy suppression."""
  active_hccs = set(mapped_hccs)
  for parent_hcc, suppressed_hccs in hierarchy_rules.items():
    if parent_hcc not in mapped_hccs:
      continue
    for suppressed_hcc in suppressed_hccs:
      active_hccs.discard(suppressed_hcc)
  return active_hccs


def _suppressed_hcc_sources(
  mapped_hccs: set[str],
  hierarchy_rules: dict[str, tuple[str, ...]],
) -> dict[str, str]:
  """Return the first suppressing parent HCC for each suppressed HCC."""
  suppressors: dict[str, str] = {}
  for parent_hcc, suppressed_hccs in hierarchy_rules.items():
    if parent_hcc not in mapped_hccs:
      continue
    for suppressed_hcc in suppressed_hccs:
      if suppressed_hcc in mapped_hccs and suppressed_hcc not in suppressors:
        suppressors[suppressed_hcc] = parent_hcc
  return suppressors


def _payment_hcc_count_bucket(active_hcc_count: int) -> str:
  """Return the stable payment HCC count bucket label."""
  return "10+" if active_hcc_count >= 10 else str(active_hcc_count)


def _age_rule_matches(expression: str, age: int | None) -> bool:
  """Evaluate a CMS age rule expression for one subject age."""
  if age is None:
    return False
  normalized_expression = expression.strip().lower()
  normalized_expression = re.sub(r"age\s*(\d+)\s*\+", r"age >= \1", normalized_expression)
  normalized_expression = re.sub(r"(?<![<>!])=", "==", normalized_expression)
  normalized_expression = re.sub(r"([<>=!]=?)", r" \1 ", normalized_expression)
  normalized_expression = re.sub(r"\s+", " ", normalized_expression).strip()
  return bool(eval(normalized_expression, {"__builtins__": {}}, {"age": age}))


def _calculate_age(date_of_birth: date | None, cutoff_date: date) -> int | None:
  """Calculate age at the model cutoff date."""
  if date_of_birth is None:
    return None
  years = cutoff_date.year - date_of_birth.year
  if (cutoff_date.month, cutoff_date.day) < (date_of_birth.month, date_of_birth.day):
    years -= 1
  return years


def _is_disabled(subject: SubjectRecord, cutoff_date: date) -> bool:
  """Return the disabled flag for a subject."""
  age = _calculate_age(subject.date_of_birth, cutoff_date)
  return bool(age is not None and age < 65 and subject.original_reason_entitlement_code in {1, 2, 3})


def _is_originally_disabled(subject: SubjectRecord, cutoff_date: date) -> bool:
  """Return the originally-disabled flag for a subject."""
  age = _calculate_age(subject.date_of_birth, cutoff_date)
  return bool(
    subject.original_reason_entitlement_code == 1
    and age is not None
    and age >= 65
  )


def _derive_ce_age_sex_cell(subject: SubjectRecord, cutoff_date: date) -> str | None:
  """Derive a CE age-sex cell label aligned to the CMS factor table."""
  age = _calculate_age(subject.date_of_birth, cutoff_date)
  sex = subject.sex
  if age is None or sex not in {1, 2}:
    return None
  sex_prefix = "M" if sex == 1 else "F"
  for start, stop in (
    (0, 34),
    (35, 44),
    (45, 54),
    (55, 59),
    (60, 64),
    (65, 69),
    (70, 74),
    (75, 79),
    (80, 84),
    (85, 89),
    (90, 94),
    (95, None),
  ):
    if age >= start and (stop is None or age <= stop):
      suffix = "GT" if stop is None else str(stop)
      return f"{sex_prefix}{start}_{suffix}"
  return None


def _derive_ne_age_sex_cell(subject: SubjectRecord, cutoff_date: date) -> str | None:
  """Derive the graft-style new-enrollee age-sex cell label."""
  age = _calculate_age(subject.date_of_birth, cutoff_date)
  sex = subject.sex
  orec = subject.original_reason_entitlement_code
  if age is None or sex not in {1, 2}:
    return None
  sex_prefix = "M" if sex == 1 else "F"
  if age == 64:
    return f"NE{sex_prefix}60_64" if orec not in {0, None} else f"NE{sex_prefix}65"
  for start, stop in (
    (0, 34),
    (35, 44),
    (45, 54),
    (55, 59),
    (60, 64),
    (65, 65),
    (66, 66),
    (67, 67),
    (68, 68),
    (69, 69),
    (70, 74),
    (75, 79),
    (80, 84),
    (85, 89),
    (90, 94),
    (95, None),
  ):
    if age >= start and (stop is None or age <= stop):
      if stop is None:
        return f"NE{sex_prefix}{start}_GT"
      if start == stop:
        return f"NE{sex_prefix}{start}"
      return f"NE{sex_prefix}{start}_{stop}"
  return None


def _derive_esrd_ne_age_sex_cell(subject: SubjectRecord, cutoff_date: date) -> str | None:
  """Derive the ESRD dialysis new-enrollee age-sex cell label."""
  age = _calculate_age(subject.date_of_birth, cutoff_date)
  sex = subject.sex
  orec = subject.original_reason_entitlement_code
  if age is None or sex not in {1, 2}:
    return None
  sex_prefix = "M" if sex == 1 else "F"
  if age == 64:
    return f"NE{sex_prefix}60_64" if orec not in {0, None} else f"NE{sex_prefix}65_69"
  for start, stop in (
    (0, 34),
    (35, 44),
    (45, 54),
    (55, 59),
    (60, 64),
    (65, 69),
    (70, 74),
    (75, 79),
    (80, 84),
    (85, None),
  ):
    if age >= start and (stop is None or age <= stop):
      suffix = "GT" if stop is None else str(stop)
      return f"NE{sex_prefix}{start}_{suffix}"
  return None


def _derive_esrd_ne_graft_age_sex_cell(
  subject: SubjectRecord,
  cutoff_date: date,
) -> str | None:
  """Derive the ESRD graft new-enrollee age-sex cell label."""
  return _derive_ne_age_sex_cell(subject, cutoff_date)
