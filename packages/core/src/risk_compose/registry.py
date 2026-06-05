"""Model registry and archived CMS reference-table metadata."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from risk_compose.types import ModelSpec

DEFAULT_MODEL_VERSION = "cms_hcc_v28_2026"

_PACKAGE_DATA_ROOT = Path(__file__).resolve().parent / "data"
_CMS_V28_BASE = (
  _PACKAGE_DATA_ROOT
  / "cms_software"
  / "2026"
  / "CMS_HCC_v28_2026_T_package_v3"
  / "software"
  / "CMS_HCC_v28"
  / "data"
  / "input"
)
_CMS_V22_BASE = (
  _PACKAGE_DATA_ROOT
  / "cms_software"
  / "2026"
  / "CMS_HCC_v22_2026_O_package_v3"
  / "software"
  / "CMS_HCC_v22"
  / "data"
  / "input"
)
_ESRD_V21_BASE = (
  _PACKAGE_DATA_ROOT
  / "cms_software"
  / "2026"
  / "ESRD_v21_2026_P_package_v3"
  / "software"
  / "ESRD_v21"
  / "data"
  / "input"
)
_ESRD_V24_BASE = (
  _PACKAGE_DATA_ROOT
  / "cms_software"
  / "2026"
  / "ESRD_v24_2026_T_package_v2"
  / "software"
  / "ESRD_v24"
  / "data"
  / "input"
)
_RXHCC_T_BASE = (
  _PACKAGE_DATA_ROOT
  / "cms_software"
  / "2026"
  / "RxHCC_v8_2026_T_package_v5"
  / "software"
  / "RxHCC"
  / "data"
  / "input"
)
_RXHCC_X_BASE = (
  _PACKAGE_DATA_ROOT
  / "cms_software"
  / "2026"
  / "RxHCC_v8_2026_X_package_v5"
  / "software"
  / "RxHCC"
  / "data"
  / "input"
)
_ELIXHAUSER_V2026_1_BASE = _PACKAGE_DATA_ROOT / "ahrq_elixhauser" / "v2026_1"

_CMS_CE_FACTOR_COLUMNS = {
  "COMMUNITY_NA": "community_na",
  "COMMUNITY_PBA": "community_pba",
  "COMMUNITY_FBA": "community_fba",
  "COMMUNITY_ND": "community_nd",
  "COMMUNITY_PBD": "community_pbd",
  "COMMUNITY_FBD": "community_fbd",
  "INSTITUTIONAL": "institutional",
}

_CMS_NE_FACTOR_COLUMNS = {
  "NE": "ne",
  "NE_SNP": "ne_snp",
}

_ESRD_V21_CE_FACTOR_COLUMNS = {
  "DIAL": "dial",
  "GRAFT_COMM": "graft_comm",
  "GRAFT_INST": "graft_inst",
}

_ESRD_V21_NE_DIAL_FACTOR_COLUMNS = {
  "DIAL_NE": "dial_ne",
}

_ESRD_V21_NE_GRAFT_FACTOR_COLUMNS = {
  "GRAFT_NE": "graft_ne",
}

_ESRD_V24_CE_FACTOR_COLUMNS = {
  "DIAL": "dial",
  "G_COMM_ND_PBD_GE65": "g_comm_nd_pbd_ge65",
  "G_COMM_ND_PBD_LT65": "g_comm_nd_pbd_lt65",
  "G_COMM_FBD_GE65": "g_comm_fbd_ge65",
  "G_COMM_FBD_LT65": "g_comm_fbd_lt65",
  "GRAFT_INST": "graft_inst",
}

_ESRD_V24_NE_DIAL_FACTOR_COLUMNS = {
  "DIAL_NE": "dial_ne",
}

_ESRD_V24_NE_GRAFT_FACTOR_COLUMNS = {
  "GRAFT_NE": "graft_ne",
}

_RXHCC_CE_FACTOR_COLUMNS = {
  "CE_NonLow_Aged": "ce_nonlow_aged",
  "CE_NonLow_NonAged": "ce_nonlow_nonaged",
  "CE_Low_Aged": "ce_low_aged",
  "CE_Low_NonAged": "ce_low_nonaged",
  "CE_LTI": "ce_lti",
}

_RXHCC_NE_FACTOR_COLUMNS = {
  "NE_NonLow_Community": "ne_nonlow_community",
  "NE_Low_Community": "ne_low_community",
  "NE_LTI": "ne_lti",
}


@dataclass(frozen=True, slots=True)
class ScoreTableSpec:
  """Reference one factor table and its score-family column mapping."""

  reference_path_key: str
  factor_columns: dict[str, str]


@dataclass(frozen=True, slots=True)
class ModelRuntimeSpec:
  """Internal runtime metadata for one supported scoring model."""

  family: str
  cc_prefix: str
  hcc_prefix: str
  hierarchy_column: str = "HCC"
  hierarchy_secondary_prefix: str = "SecondaryHCC"
  mapping_icd10_column: str = "ICD10"
  mapping_cc_column: str = "CC"
  diagnosis_categories_key: str | None = "diagnosis_categories"
  interactions_key: str | None = "interactions"
  score_tables: tuple[ScoreTableSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class MappingRule:
  """One ICD-10 to CC/HCC mapping rule loaded from archived CMS tables."""

  icd10_code: str
  cc: str
  hcc: str
  mce_age_condition: str | None
  age_edit_condition: str | None
  sex_edit_condition: int | None


@dataclass(frozen=True, slots=True)
class InteractionRule:
  """One interaction rule between predictor variables."""

  name: str
  left_variable: str
  right_variable: str


@dataclass(frozen=True, slots=True)
class ScoreFactor:
  """One factor-table row used during score assembly."""

  variable: str
  coefficient: float


@dataclass(frozen=True, slots=True)
class ModelTables:
  """Normalized reference tables for one supported model version."""

  mapping_rules_by_icd10: dict[str, tuple[MappingRule, ...]]
  hierarchy_rules: dict[str, tuple[str, ...]]
  diagnosis_categories: dict[str, tuple[str, ...]]
  interaction_rules: tuple[InteractionRule, ...]
  score_factors: dict[str, tuple[ScoreFactor, ...]]
  factor_variables: tuple[str, ...]
  hcc_variables: tuple[str, ...]
  diagnosis_category_variables: tuple[str, ...]
  interaction_variables: tuple[str, ...]
  count_variables: tuple[str, ...]
  ne_factor_variables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ElixhauserMappingRule:
  """One ICD-10-CM to Elixhauser comorbidity mapping rule."""

  icd10_code: str
  description: str
  measure: str


@dataclass(frozen=True, slots=True)
class ElixhauserMeasure:
  """One public Elixhauser comorbidity measure."""

  measure: str
  description: str
  uses_poa: bool


@dataclass(frozen=True, slots=True)
class ElixhauserIndexWeight:
  """Readmission and mortality index weights for one measure."""

  measure: str
  readmission_weight: int
  mortality_weight: int


@dataclass(frozen=True, slots=True)
class ElixhauserTables:
  """Normalized AHRQ Elixhauser reference tables."""

  measures: tuple[ElixhauserMeasure, ...]
  mappings_by_icd10: dict[str, tuple[ElixhauserMappingRule, ...]]
  weights_by_measure: dict[str, ElixhauserIndexWeight]
  poa_exemptions_by_version: dict[int, frozenset[str]]


_CMS_HCC_RUNTIME = ModelRuntimeSpec(
  family="cms_hcc",
  cc_prefix="CC",
  hcc_prefix="HCC",
  score_tables=(
    ScoreTableSpec(
      reference_path_key="ce_relative_factors",
      factor_columns=_CMS_CE_FACTOR_COLUMNS,
    ),
    ScoreTableSpec(
      reference_path_key="ne_relative_factors",
      factor_columns=_CMS_NE_FACTOR_COLUMNS,
    ),
  ),
)

_ESRD_V21_RUNTIME = ModelRuntimeSpec(
  family="esrd",
  cc_prefix="CC",
  hcc_prefix="HCC",
  score_tables=(
    ScoreTableSpec(
      reference_path_key="ce_relative_factors",
      factor_columns=_ESRD_V21_CE_FACTOR_COLUMNS,
    ),
    ScoreTableSpec(
      reference_path_key="ne_dial_relative_factors",
      factor_columns=_ESRD_V21_NE_DIAL_FACTOR_COLUMNS,
    ),
    ScoreTableSpec(
      reference_path_key="ne_graft_relative_factors",
      factor_columns=_ESRD_V21_NE_GRAFT_FACTOR_COLUMNS,
    ),
  ),
)

_ESRD_V24_RUNTIME = ModelRuntimeSpec(
  family="esrd",
  cc_prefix="CC",
  hcc_prefix="HCC",
  score_tables=(
    ScoreTableSpec(
      reference_path_key="ce_relative_factors",
      factor_columns=_ESRD_V24_CE_FACTOR_COLUMNS,
    ),
    ScoreTableSpec(
      reference_path_key="ne_dial_relative_factors",
      factor_columns=_ESRD_V24_NE_DIAL_FACTOR_COLUMNS,
    ),
    ScoreTableSpec(
      reference_path_key="ne_graft_relative_factors",
      factor_columns=_ESRD_V24_NE_GRAFT_FACTOR_COLUMNS,
    ),
  ),
)

_RXHCC_RUNTIME = ModelRuntimeSpec(
  family="rxhcc",
  cc_prefix="RXCC",
  hcc_prefix="RXHCC",
  hierarchy_column="RXHCC",
  hierarchy_secondary_prefix="SecondaryRxHCC",
  diagnosis_categories_key=None,
  interactions_key=None,
  score_tables=(
    ScoreTableSpec(
      reference_path_key="ce_relative_factors",
      factor_columns=_RXHCC_CE_FACTOR_COLUMNS,
    ),
    ScoreTableSpec(
      reference_path_key="ne_relative_factors",
      factor_columns=_RXHCC_NE_FACTOR_COLUMNS,
    ),
  ),
)

_ESRD_V21_SCORE_FAMILIES = (
  "dial",
  "graft_comm_dur4_9_lt65",
  "graft_comm_dur4_9_ge65",
  "graft_comm_dur10pl_lt65",
  "graft_comm_dur10pl_ge65",
  "graft_inst_dur4_9_lt65",
  "graft_inst_dur4_9_ge65",
  "graft_inst_dur10pl_lt65",
  "graft_inst_dur10pl_ge65",
  "dial_ne",
  "graft_ne_dur4_9_lt65",
  "graft_ne_dur4_9_ge65",
  "graft_ne_dur10pl_lt65",
  "graft_ne_dur10pl_ge65",
  "transplant_kidney_only_1m",
  "transplant_kidney_only_2m",
  "transplant_kidney_only_3m",
)

_ESRD_V24_SCORE_FAMILIES = (
  "dial",
  "g_comm_nd_pbd_ge65_dur4_9",
  "g_comm_nd_pbd_ge65_dur10pl",
  "g_comm_nd_pbd_lt65_dur4_9",
  "g_comm_nd_pbd_lt65_dur10pl",
  "g_comm_fbd_ge65_dur4_9",
  "g_comm_fbd_ge65_dur10pl",
  "g_comm_fbd_lt65_dur4_9",
  "g_comm_fbd_lt65_dur10pl",
  "graft_inst_nd_pbd_lt65_dur4_9",
  "graft_inst_fbd_lt65_dur4_9",
  "graft_inst_nd_pbd_ge65_dur4_9",
  "graft_inst_fbd_ge65_dur4_9",
  "graft_inst_nd_pbd_lt65_dur10pl",
  "graft_inst_fbd_lt65_dur10pl",
  "graft_inst_nd_pbd_ge65_dur10pl",
  "graft_inst_fbd_ge65_dur10pl",
  "dial_ne",
  "graft_ne_ge65_dur4_9_nd_pbd",
  "graft_ne_ge65_dur10pl_nd_pbd",
  "graft_ne_lt65_dur4_9_nd_pbd",
  "graft_ne_lt65_dur10pl_nd_pbd",
  "graft_ne_ge65_dur4_9_fbd",
  "graft_ne_ge65_dur10pl_fbd",
  "graft_ne_lt65_dur4_9_fbd",
  "graft_ne_lt65_dur10pl_fbd",
  "transplant_kidney_only_1m",
  "transplant_kidney_only_2m",
  "transplant_kidney_only_3m",
)

_RXHCC_SCORE_FAMILIES = (
  "ce_nonlow_aged",
  "ce_nonlow_nonaged",
  "ce_low_aged",
  "ce_low_nonaged",
  "ce_lti",
  "ne_nonlow_community",
  "ne_low_community",
  "ne_lti",
)

_MODEL_REGISTRY = {
  "cms_hcc_v22_2026": ModelSpec(
    version_id="cms_hcc_v22_2026",
    payment_year=2026,
    family="cms_hcc",
    model_version="v22",
    package_variant="O",
    cutoff_date=date(2026, 2, 1),
    score_families=(
      "community_na",
      "community_pba",
      "community_fba",
      "community_nd",
      "community_pbd",
      "community_fbd",
      "institutional",
      "ne",
      "ne_snp",
    ),
    reference_paths={
      "subjects_sample": _CMS_V22_BASE / "user_defined" / "beneficiaries.csv",
      "diagnoses_sample": _CMS_V22_BASE / "user_defined" / "diagnoses.csv",
      "icd10_cc_mappings": _CMS_V22_BASE / "internal" / "ICD10_CC_mappings_CMS_HCC_2026_v22.csv",
      "hcc_hierarchies": _CMS_V22_BASE / "internal" / "V22_HCC_Hierarchies.csv",
      "diagnosis_categories": _CMS_V22_BASE / "internal" / "V22_Diagnosis_Categories.csv",
      "interactions": _CMS_V22_BASE / "internal" / "V22_Interactions.csv",
      "ce_relative_factors": _CMS_V22_BASE / "internal" / "V22_CE_Relative_Factors.csv",
      "ne_relative_factors": _CMS_V22_BASE / "internal" / "V22_NE_Relative_Factors.csv",
    },
    notes=(
      "CMS-HCC v22 shares the CMS-HCC family predictor runtime with v28.",
      "Score families mirror CMS v22 CE and NE factor-table groupings.",
    ),
  ),
  DEFAULT_MODEL_VERSION: ModelSpec(
    version_id=DEFAULT_MODEL_VERSION,
    payment_year=2026,
    family="cms_hcc",
    model_version="v28",
    package_variant="T",
    cutoff_date=date(2026, 2, 1),
    score_families=(
      "community_na",
      "community_pba",
      "community_fba",
      "community_nd",
      "community_pbd",
      "community_fbd",
      "institutional",
      "ne",
      "ne_snp",
    ),
    reference_paths={
      "subjects_sample": _CMS_V28_BASE / "user_defined" / "beneficiaries.csv",
      "diagnoses_sample": _CMS_V28_BASE / "user_defined" / "diagnoses.csv",
      "icd10_cc_mappings": _CMS_V28_BASE / "internal" / "ICD10_CC_mappings_CMS_HCC_2026_v28.csv",
      "hcc_hierarchies": _CMS_V28_BASE / "internal" / "V28_HCC_Hierarchies.csv",
      "diagnosis_categories": _CMS_V28_BASE / "internal" / "V28_Diagnosis_Categories.csv",
      "interactions": _CMS_V28_BASE / "internal" / "V28_Interactions.csv",
      "ce_relative_factors": _CMS_V28_BASE / "internal" / "V28_CE_Relative_Factors.csv",
      "ne_relative_factors": _CMS_V28_BASE / "internal" / "V28_NE_Relative_Factors.csv",
    },
    notes=(
      "CMS-HCC v28 shares the CMS-HCC family predictor runtime with v22.",
      "Score families mirror CMS v28 CE and NE factor-table groupings.",
    ),
  ),
  "esrd_v21_2026": ModelSpec(
    version_id="esrd_v21_2026",
    payment_year=2026,
    family="esrd",
    model_version="v21",
    package_variant="P",
    cutoff_date=date(2026, 2, 1),
    score_families=_ESRD_V21_SCORE_FAMILIES,
    reference_paths={
      "subjects_sample": _ESRD_V21_BASE / "user_defined" / "beneficiaries.csv",
      "diagnoses_sample": _ESRD_V21_BASE / "user_defined" / "diagnoses.csv",
      "icd10_cc_mappings": _ESRD_V21_BASE / "internal" / "ICD10_CC_mappings_ESRD_2026_v21.csv",
      "hcc_hierarchies": _ESRD_V21_BASE / "internal" / "V21_HCC_Hierarchies.csv",
      "diagnosis_categories": _ESRD_V21_BASE / "internal" / "V21_Diagnosis_Categories.csv",
      "interactions": _ESRD_V21_BASE / "internal" / "V21_Interactions.csv",
      "ce_relative_factors": _ESRD_V21_BASE / "internal" / "V21_CE_Relative_Factors.csv",
      "ne_dial_relative_factors": _ESRD_V21_BASE / "internal" / "V21_NE_Dialysis_Relative_Factors.csv",
      "ne_graft_relative_factors": _ESRD_V21_BASE / "internal" / "V21_NE_Graft_Relative_Factors.csv",
      "graft_duration_scores": _ESRD_V21_BASE / "internal" / "V21_Graft_Duration_Scores.csv",
      "transplant_scores": _ESRD_V21_BASE / "internal" / "V21_Transplant_Scores.csv",
    },
    notes=(
      "ESRD v21 exposes CE, NE, graft-duration, and transplant public score families.",
      "The v21 package variant is P.",
    ),
  ),
  "esrd_v24_2026": ModelSpec(
    version_id="esrd_v24_2026",
    payment_year=2026,
    family="esrd",
    model_version="v24",
    package_variant="T",
    cutoff_date=date(2026, 2, 1),
    score_families=_ESRD_V24_SCORE_FAMILIES,
    reference_paths={
      "subjects_sample": _ESRD_V24_BASE / "user_defined" / "beneficiaries.csv",
      "diagnoses_sample": _ESRD_V24_BASE / "user_defined" / "diagnoses.csv",
      "icd10_cc_mappings": _ESRD_V24_BASE / "internal" / "ICD10_CC_mappings_ESRD_2026_v24.csv",
      "hcc_hierarchies": _ESRD_V24_BASE / "internal" / "V24_HCC_Hierarchies.csv",
      "diagnosis_categories": _ESRD_V24_BASE / "internal" / "V24_Diagnosis_Categories.csv",
      "interactions": _ESRD_V24_BASE / "internal" / "V24_Interactions.csv",
      "ce_relative_factors": _ESRD_V24_BASE / "internal" / "V24_CE_Relative_Factors.csv",
      "ne_dial_relative_factors": _ESRD_V24_BASE / "internal" / "V24_NE_Dialysis_Relative_Factors.csv",
      "ne_graft_relative_factors": _ESRD_V24_BASE / "internal" / "V24_NE_Graft_Relative_Factors.csv",
      "graft_duration_scores": _ESRD_V24_BASE / "internal" / "V24_Graft_Duration_Scores.csv",
      "transplant_scores": _ESRD_V24_BASE / "internal" / "V24_Transplant_Scores.csv",
      "inst_graft_scores": _ESRD_V24_BASE / "internal" / "V24_CE_Institutional_Graft_Scores.csv",
    },
    notes=(
      "ESRD v24 uses the updated dual and institutional graft adjustments.",
      "The v24 package variant is T.",
    ),
  ),
  "rxhcc_v8_t_2026": ModelSpec(
    version_id="rxhcc_v8_t_2026",
    payment_year=2026,
    family="rxhcc",
    model_version="v8",
    package_variant="T",
    cutoff_date=date(2026, 2, 1),
    score_families=_RXHCC_SCORE_FAMILIES,
    reference_paths={
      "subjects_sample": _RXHCC_T_BASE / "user_defined" / "beneficiaries.csv",
      "diagnoses_sample": _RXHCC_T_BASE / "user_defined" / "diagnoses.csv",
      "icd10_cc_mappings": _RXHCC_T_BASE / "internal" / "ICD10_CC_mappings_RxHCC_2026.csv",
      "hcc_hierarchies": _RXHCC_T_BASE / "internal" / "HCC_Hierarchies.csv",
      "ce_relative_factors": _RXHCC_T_BASE / "internal" / "T" / "T_CE_Relative_Factors.csv",
      "ne_relative_factors": _RXHCC_T_BASE / "internal" / "T" / "T_NE_Relative_Factors.csv",
    },
    notes=(
      "RxHCC v8 T uses shared RxHCC mapping and hierarchy tables with T-specific coefficients.",
    ),
  ),
  "rxhcc_v8_x_2026": ModelSpec(
    version_id="rxhcc_v8_x_2026",
    payment_year=2026,
    family="rxhcc",
    model_version="v8",
    package_variant="X",
    cutoff_date=date(2026, 2, 1),
    score_families=_RXHCC_SCORE_FAMILIES,
    reference_paths={
      "subjects_sample": _RXHCC_X_BASE / "user_defined" / "beneficiaries.csv",
      "diagnoses_sample": _RXHCC_X_BASE / "user_defined" / "diagnoses.csv",
      "icd10_cc_mappings": _RXHCC_X_BASE / "internal" / "ICD10_CC_mappings_RxHCC_2026.csv",
      "hcc_hierarchies": _RXHCC_X_BASE / "internal" / "HCC_Hierarchies.csv",
      "ce_relative_factors": _RXHCC_X_BASE / "internal" / "X" / "X_CE_Relative_Factors.csv",
      "ne_relative_factors": _RXHCC_X_BASE / "internal" / "X" / "X_NE_Relative_Factors.csv",
    },
    notes=(
      "RxHCC v8 X uses shared RxHCC mapping and hierarchy tables with X-specific coefficients.",
    ),
  ),
  "elixhauser_v2026_1": ModelSpec(
    version_id="elixhauser_v2026_1",
    payment_year=2026,
    family="ahrq_elixhauser",
    model_version="v2026.1",
    package_variant="refined",
    cutoff_date=date(2026, 9, 30),
    score_families=(
      "readmission_index",
      "mortality_index",
    ),
    reference_paths={
      "comorbidity_measures": _ELIXHAUSER_V2026_1_BASE / "comorbidity_measures.csv",
      "dx_to_comorbidity": _ELIXHAUSER_V2026_1_BASE / "dx_to_comorbidity.csv",
      "index_weights": _ELIXHAUSER_V2026_1_BASE / "index_weights.csv",
      "poa_exemptions": _ELIXHAUSER_V2026_1_BASE / "poa_exemptions.csv",
    },
    notes=(
      "AHRQ Elixhauser Comorbidity Software Refined for ICD-10-CM v2026.1.",
      "Runtime artifacts are derived from archived official AHRQ workbook and SAS programs.",
    ),
  ),
}

_MODEL_RUNTIME_REGISTRY = {
  "cms_hcc_v22_2026": _CMS_HCC_RUNTIME,
  DEFAULT_MODEL_VERSION: _CMS_HCC_RUNTIME,
  "esrd_v21_2026": _ESRD_V21_RUNTIME,
  "esrd_v24_2026": _ESRD_V24_RUNTIME,
  "rxhcc_v8_t_2026": _RXHCC_RUNTIME,
  "rxhcc_v8_x_2026": _RXHCC_RUNTIME,
}


def get_model_spec(version_id: str = DEFAULT_MODEL_VERSION) -> ModelSpec:
  """Return the registered model spec for a supported release."""
  try:
    return _MODEL_REGISTRY[version_id]
  except KeyError as exc:
    raise KeyError(f"Unsupported model version: {version_id}") from exc


def get_model_runtime_spec(version_id: str = DEFAULT_MODEL_VERSION) -> ModelRuntimeSpec:
  """Return internal runtime metadata for a supported model version."""
  try:
    return _MODEL_RUNTIME_REGISTRY[version_id]
  except KeyError as exc:
    raise KeyError(f"Unsupported model version: {version_id}") from exc


@lru_cache(maxsize=None)
def get_model_tables(version_id: str = DEFAULT_MODEL_VERSION) -> ModelTables:
  """Return cached normalized reference tables for a supported model version."""
  model_spec = get_model_spec(version_id)
  runtime_spec = get_model_runtime_spec(version_id)
  mapping_rules_by_icd10 = _load_mapping_rules(
    model_spec.reference_paths["icd10_cc_mappings"],
    runtime_spec=runtime_spec,
  )
  hierarchy_rules = _load_hierarchy_rules(
    model_spec.reference_paths["hcc_hierarchies"],
    runtime_spec=runtime_spec,
  )
  if runtime_spec.diagnosis_categories_key:
    diagnosis_categories = _load_diagnosis_categories(
      model_spec.reference_paths[runtime_spec.diagnosis_categories_key],
    )
  else:
    diagnosis_categories = {}
  if runtime_spec.interactions_key:
    interaction_rules = _load_interaction_rules(
      model_spec.reference_paths[runtime_spec.interactions_key],
    )
  else:
    interaction_rules = ()
  score_factors, factor_variables_by_path = _load_score_factors_for_model(model_spec, runtime_spec)
  ce_factor_variables = factor_variables_by_path.get("ce_relative_factors", ())
  ne_factor_variables = _ordered_unique(
    variable
    for path_key, variables in factor_variables_by_path.items()
    if path_key != "ce_relative_factors"
    for variable in variables
  )
  hierarchy_hccs = _ordered_unique(
    hcc
    for parent, secondaries in hierarchy_rules.items()
    for hcc in (parent, *secondaries)
  )
  factor_hccs = _ordered_unique(
    variable
    for variable in _ordered_unique((*ce_factor_variables, *ne_factor_variables))
    if variable.startswith(runtime_spec.hcc_prefix)
  )
  interaction_hccs = _ordered_unique(
    variable
    for rule in interaction_rules
    for variable in (rule.left_variable, rule.right_variable)
    if variable.startswith(runtime_spec.hcc_prefix)
  )
  hcc_variables = _ordered_unique((*hierarchy_hccs, *factor_hccs, *interaction_hccs))
  factor_variables = _ordered_unique((*ce_factor_variables, *ne_factor_variables))
  count_variables = tuple(
    variable
    for variable in factor_variables
    if variable.startswith("D") and (variable[1:].isdigit() or variable.endswith("P"))
  )
  return ModelTables(
    mapping_rules_by_icd10=mapping_rules_by_icd10,
    hierarchy_rules=hierarchy_rules,
    diagnosis_categories=diagnosis_categories,
    interaction_rules=interaction_rules,
    score_factors=score_factors,
    factor_variables=factor_variables,
    hcc_variables=hcc_variables,
    diagnosis_category_variables=tuple(diagnosis_categories.keys()),
    interaction_variables=tuple(rule.name for rule in interaction_rules),
    count_variables=count_variables,
    ne_factor_variables=ne_factor_variables,
  )


def list_model_specs() -> tuple[ModelSpec, ...]:
  """Return the registered model specs in a deterministic order."""
  return tuple(_MODEL_REGISTRY.values())


@lru_cache(maxsize=None)
def get_elixhauser_tables(version_id: str = "elixhauser_v2026_1") -> ElixhauserTables:
  """Return cached normalized AHRQ Elixhauser reference tables."""
  model_spec = get_model_spec(version_id)
  if model_spec.family != "ahrq_elixhauser":
    raise KeyError(f"Model version is not an AHRQ Elixhauser release: {version_id}")
  measures = tuple(
    ElixhauserMeasure(
      measure=_clean_text(row.get("measure")) or "",
      description=_clean_text(row.get("description")) or "",
      uses_poa=(row.get("uses_poa") == "1"),
    )
    for row in read_reference_rows(model_spec.reference_paths["comorbidity_measures"])
  )
  mapping_rows = tuple(
    ElixhauserMappingRule(
      icd10_code=_clean_text(row.get("icd10_code")) or "",
      description=_clean_text(row.get("description")) or "",
      measure=_clean_text(row.get("measure")) or "",
    )
    for row in read_reference_rows(model_spec.reference_paths["dx_to_comorbidity"])
  )
  mappings_by_icd10: dict[str, list[ElixhauserMappingRule]] = {}
  for mapping_row in mapping_rows:
    if mapping_row.icd10_code and mapping_row.measure:
      mappings_by_icd10.setdefault(mapping_row.icd10_code, []).append(mapping_row)
  weights_by_measure = {
    row["measure"]: ElixhauserIndexWeight(
      measure=row["measure"],
      readmission_weight=int(row["readmission_weight"]),
      mortality_weight=int(row["mortality_weight"]),
    )
    for row in read_reference_rows(model_spec.reference_paths["index_weights"])
  }
  poa_exemptions_by_version: dict[int, set[str]] = {}
  for row in read_reference_rows(model_spec.reference_paths["poa_exemptions"]):
    poa_exemptions_by_version.setdefault(int(row["icd_version"]), set()).add(row["icd10_code"])
  return ElixhauserTables(
    measures=measures,
    mappings_by_icd10={code: tuple(rules) for code, rules in mappings_by_icd10.items()},
    weights_by_measure=weights_by_measure,
    poa_exemptions_by_version={
      version: frozenset(codes)
      for version, codes in poa_exemptions_by_version.items()
    },
  )


@lru_cache(maxsize=None)
def read_reference_rows(path: Path) -> tuple[dict[str, str], ...]:
  """Read one archived CMS CSV file with BOM-tolerant UTF-8 handling."""
  with path.open("r", encoding="utf-8-sig", newline="") as handle:
    return tuple(csv.DictReader(handle))


def _load_mapping_rules(
  path: Path,
  *,
  runtime_spec: ModelRuntimeSpec,
) -> dict[str, tuple[MappingRule, ...]]:
  """Load ICD-10 to CC/HCC mapping rules from archived CMS reference data."""
  rows_by_icd10: dict[str, list[MappingRule]] = {}
  for row in read_reference_rows(path):
    icd10_code = _clean_text(row.get(runtime_spec.mapping_icd10_column))
    cc_token = _normalize_numeric_token(row.get(runtime_spec.mapping_cc_column))
    if not icd10_code or not cc_token:
      continue
    rule = MappingRule(
      icd10_code=icd10_code,
      cc=f"{runtime_spec.cc_prefix}{cc_token}",
      hcc=f"{runtime_spec.hcc_prefix}{cc_token}",
      mce_age_condition=_clean_text(row.get("MCE_AGE_CONDITION")),
      age_edit_condition=_clean_text(row.get("AGE_EDIT_CONDITION")),
      sex_edit_condition=_parse_nullable_int(row.get("SEX_EDIT_CONDITION")),
    )
    rows_by_icd10.setdefault(icd10_code, []).append(rule)
  return {icd10_code: tuple(rules) for icd10_code, rules in rows_by_icd10.items()}


def _load_hierarchy_rules(
  path: Path,
  *,
  runtime_spec: ModelRuntimeSpec,
) -> dict[str, tuple[str, ...]]:
  """Load HCC hierarchy suppression rules keyed by parent HCC."""
  hierarchy_rules: dict[str, tuple[str, ...]] = {}
  for row in read_reference_rows(path):
    parent_hcc = _normalize_hcc_identifier(
      row.get(runtime_spec.hierarchy_column),
      runtime_spec=runtime_spec,
    )
    if not parent_hcc:
      continue
    secondaries = tuple(
      secondary_hcc
      for key, value in row.items()
      if key.startswith(runtime_spec.hierarchy_secondary_prefix)
      for secondary_hcc in [
        _normalize_hcc_identifier(
          value,
          runtime_spec=runtime_spec,
        ),
      ]
      if secondary_hcc
    )
    hierarchy_rules[parent_hcc] = secondaries
  return hierarchy_rules


def _load_diagnosis_categories(path: Path) -> dict[str, tuple[str, ...]]:
  """Load diagnosis category to HCC membership rules."""
  diagnosis_categories: dict[str, tuple[str, ...]] = {}
  for row in read_reference_rows(path):
    category_name = _clean_text(row.get("diag_category"))
    if not category_name:
      continue
    diagnosis_categories[category_name] = tuple(
      hcc_name
      for key, value in row.items()
      if key != "diag_category"
      for hcc_name in [_clean_text(value)]
      if hcc_name
    )
  return diagnosis_categories


def _load_interaction_rules(path: Path) -> tuple[InteractionRule, ...]:
  """Load interaction rules in declared CMS order."""
  interaction_rules = []
  for row in read_reference_rows(path):
    name = _clean_text(row.get("interaction"))
    left_variable = _clean_text(row.get("var_1"))
    right_variable = _clean_text(row.get("var_2"))
    if not name or not left_variable or not right_variable:
      continue
    interaction_rules.append(
      InteractionRule(
        name=name,
        left_variable=left_variable,
        right_variable=right_variable,
      ),
    )
  return tuple(interaction_rules)


def _load_score_factors(
  path: Path,
  factor_columns: dict[str, str],
) -> tuple[dict[str, tuple[ScoreFactor, ...]], tuple[str, ...]]:
  """Load score factors from one archived CMS factor table."""
  loaded_factors: dict[str, list[ScoreFactor]] = {
    public_family: [] for public_family in factor_columns.values()
  }
  variables_in_order: list[str] = []
  seen_variables: set[str] = set()
  for row in read_reference_rows(path):
    variable_name = _clean_text(row.get("Variable"))
    if not variable_name:
      continue
    if variable_name not in seen_variables:
      variables_in_order.append(variable_name)
      seen_variables.add(variable_name)
    for csv_column, public_family in factor_columns.items():
      coefficient_text = _clean_text(row.get(csv_column))
      if coefficient_text is None:
        continue
      loaded_factors[public_family].append(
        ScoreFactor(variable=variable_name, coefficient=float(coefficient_text)),
      )
  return (
    {public_family: tuple(factors) for public_family, factors in loaded_factors.items()},
    tuple(variables_in_order),
  )


def _load_score_factors_for_model(
  model_spec: ModelSpec,
  runtime_spec: ModelRuntimeSpec,
) -> tuple[dict[str, tuple[ScoreFactor, ...]], dict[str, tuple[str, ...]]]:
  """Load and merge all factor tables declared for a model runtime."""
  merged_score_factors: dict[str, tuple[ScoreFactor, ...]] = {}
  factor_variables_by_path: dict[str, tuple[str, ...]] = {}
  for score_table in runtime_spec.score_tables:
    loaded_score_factors, factor_variables = _load_score_factors(
      model_spec.reference_paths[score_table.reference_path_key],
      score_table.factor_columns,
    )
    merged_score_factors.update(loaded_score_factors)
    factor_variables_by_path[score_table.reference_path_key] = factor_variables
  return merged_score_factors, factor_variables_by_path


def _normalize_numeric_token(value: object | None) -> str | None:
  """Normalize numeric-looking CMS CC/HCC identifiers to stable tokens."""
  text = _clean_text(value)
  if text is None:
    return None
  normalized = text.replace("_", ".")
  try:
    number = float(normalized)
  except ValueError:
    return normalized
  if number.is_integer():
    return str(int(number))
  return ("%f" % number).rstrip("0").rstrip(".").replace(".", "_")


def _normalize_hcc_identifier(
  value: object | None,
  *,
  runtime_spec: ModelRuntimeSpec,
) -> str | None:
  """Normalize hierarchy-table HCC identifiers to the runtime HCC prefix."""
  token = _normalize_numeric_token(value)
  if token is None:
    return None
  if token.startswith(runtime_spec.hcc_prefix):
    return token
  if token[:1].isdigit():
    return f"{runtime_spec.hcc_prefix}{token}"
  return token


def _parse_nullable_int(value: object | None) -> int | None:
  """Parse nullable integer-like values used by CMS edit tables."""
  text = _clean_text(value)
  if text is None:
    return None
  try:
    return int(text)
  except ValueError:
    return int(float(text))


def _clean_text(value: object | None) -> str | None:
  """Normalize nullable CSV string values."""
  if value is None:
    return None
  text = str(value).strip()
  if not text:
    return None
  return text


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
  """Return unique string values while preserving first-seen order."""
  ordered: list[str] = []
  seen: set[str] = set()
  for value in values:
    if value not in seen:
      ordered.append(value)
      seen.add(value)
  return tuple(ordered)
