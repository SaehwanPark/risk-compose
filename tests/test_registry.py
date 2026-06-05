from __future__ import annotations

import pytest

from risk_compose.registry import DEFAULT_MODEL_VERSION, get_model_spec, list_model_specs


def test_get_model_spec_returns_registered_version() -> None:
  model_spec = get_model_spec()
  assert model_spec.version_id == DEFAULT_MODEL_VERSION
  assert model_spec.reference_paths["icd10_cc_mappings"].name == "ICD10_CC_mappings_CMS_HCC_2026_v28.csv"
  assert model_spec.reference_paths["icd10_cc_mappings"].exists()


def test_get_model_spec_supports_cms_hcc_v22_2026() -> None:
  model_spec = get_model_spec("cms_hcc_v22_2026")
  assert model_spec.version_id == "cms_hcc_v22_2026"
  assert model_spec.family == "cms_hcc"
  assert model_spec.reference_paths["icd10_cc_mappings"].name == "ICD10_CC_mappings_CMS_HCC_2026_v22.csv"


@pytest.mark.parametrize(
  ("version_id", "family", "reference_name"),
  (
    ("esrd_v21_2026", "esrd", "ICD10_CC_mappings_ESRD_2026_v21.csv"),
    ("esrd_v24_2026", "esrd", "ICD10_CC_mappings_ESRD_2026_v24.csv"),
    ("rxhcc_v8_t_2026", "rxhcc", "ICD10_CC_mappings_RxHCC_2026.csv"),
    ("rxhcc_v8_x_2026", "rxhcc", "ICD10_CC_mappings_RxHCC_2026.csv"),
  ),
)
def test_get_model_spec_supports_additional_2026_models(
  version_id: str,
  family: str,
  reference_name: str,
) -> None:
  model_spec = get_model_spec(version_id)
  assert model_spec.version_id == version_id
  assert model_spec.family == family
  assert model_spec.reference_paths["icd10_cc_mappings"].name == reference_name


def test_get_model_spec_supports_elixhauser_v2026_1() -> None:
  model_spec = get_model_spec("elixhauser_v2026_1")
  assert model_spec.version_id == "elixhauser_v2026_1"
  assert model_spec.family == "ahrq_elixhauser"
  assert model_spec.reference_paths["dx_to_comorbidity"].name == "dx_to_comorbidity.csv"
  assert model_spec.score_families == ("readmission_index", "mortality_index")


def test_list_model_specs_includes_all_supported_2026_models() -> None:
  version_ids = {model_spec.version_id for model_spec in list_model_specs()}
  assert {
    "cms_hcc_v22_2026",
    "cms_hcc_v28_2026",
    "esrd_v21_2026",
    "esrd_v24_2026",
    "rxhcc_v8_t_2026",
    "rxhcc_v8_x_2026",
    "elixhauser_v2026_1",
  } <= version_ids


def test_registered_model_reference_paths_are_packaged() -> None:
  for model_spec in list_model_specs():
    for reference_key, reference_path in model_spec.reference_paths.items():
      assert reference_path.exists(), f"{model_spec.version_id}:{reference_key} missing {reference_path}"
      assert "risk_compose/data" in reference_path.as_posix()


def test_get_model_spec_rejects_unknown_version() -> None:
  with pytest.raises(KeyError, match="Unsupported model version"):
    get_model_spec("unknown_version")
