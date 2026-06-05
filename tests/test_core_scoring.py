from __future__ import annotations

from datetime import date

import pytest

from risk_compose._typing import ArtifactRow, ArtifactValue
from risk_compose.core import explain_subject_raf, generate_predictors, score_subjects
from risk_compose.types import SubjectRecord, DiagnosisRecord, ScoringOptions, ScoringRequest


def _subject(
  subject_id: str,
  *,
  date_of_birth: date,
  sex: int,
  orec: int,
  ltimcaid: int = 0,
  nemcaid: int = 0,
) -> SubjectRecord:
  return SubjectRecord(
    subject_id=subject_id,
    date_of_birth=date_of_birth,
    sex=sex,
    original_reason_entitlement_code=orec,
    limited_income_medicaid_flag=ltimcaid,
    new_enrollee_medicaid_flag=nemcaid,
  )


def _diagnosis(subject_id: str, icd10_code: str) -> DiagnosisRecord:
  return DiagnosisRecord(subject_id=subject_id, icd10_code=icd10_code)


def _elixhauser_subject(subject_id: str) -> SubjectRecord:
  return SubjectRecord(
    subject_id=subject_id,
    date_of_birth=None,
    sex=None,
    original_reason_entitlement_code=None,
  )


def _contribution_row(
  rows: tuple[ArtifactRow, ...],
  *,
  score_family: str,
  variable_name: str,
) -> ArtifactRow:
  return next(
    row
    for row in rows
    if row["score_family"] == score_family and row["variable_name"] == variable_name
  )


def _numeric(value: ArtifactValue) -> float:
  assert isinstance(value, (int, float))
  return float(value)


def test_score_subjects_supports_ahrq_elixhauser_measures_and_indices() -> None:
  request = ScoringRequest(
    subjects=(_elixhauser_subject("CASE-1"),),
    diagnoses=(
      DiagnosisRecord("CASE-1", "E119", diagnosis_sequence=2),
      DiagnosisRecord("CASE-1", "I509", diagnosis_sequence=2, present_on_admission="Y"),
      DiagnosisRecord("CASE-1", "D500", diagnosis_sequence=2, present_on_admission="Y"),
      DiagnosisRecord("CASE-1", "C7951", diagnosis_sequence=1, present_on_admission="Y"),
    ),
    options=ScoringOptions(model_version="elixhauser_v2026_1"),
  )

  result = score_subjects(request)
  predictor_row = result.predictors.subject_predictors.rows[0]
  score_row = result.scores.subject_scores.rows[0]

  assert predictor_row["CMR_DIAB_UNCX"] == 1
  assert predictor_row["CMR_HF"] == 1
  assert predictor_row["CMR_BLDLOSS"] == 1
  assert predictor_row["CMR_CANCER_METS"] == 0
  assert predictor_row["mapped_comorbidity_count"] == 3
  assert score_row["score_readmission_index"] == pytest.approx(9.0)
  assert score_row["score_mortality_index"] == pytest.approx(10.0)
  assert any(
    row["icd10_code"] == "C7951" and row["mapping_status"] == "primary_diagnosis_excluded"
    for row in result.predictors.diagnosis_mappings.rows
  )


def test_score_subjects_marks_elixhauser_poa_dependent_outputs_missing_without_poa() -> None:
  request = ScoringRequest(
    subjects=(_elixhauser_subject("CASE-2"),),
    diagnoses=(DiagnosisRecord("CASE-2", "I509", diagnosis_sequence=2),),
    options=ScoringOptions(model_version="elixhauser_v2026_1"),
  )

  result = score_subjects(request)
  predictor_row = result.predictors.subject_predictors.rows[0]
  score_row = result.scores.subject_scores.rows[0]

  assert predictor_row["CMR_HF"] is None
  assert score_row["score_readmission_index"] is None
  assert score_row["score_mortality_index"] is None
  assert result.predictors.diagnosis_mappings.rows[0]["mapping_status"] == "poa_unavailable"


def test_explain_subject_supports_elixhauser_interaction_details() -> None:
  explain_result = explain_subject_raf(
    _elixhauser_subject("CASE-3"),
    (
      DiagnosisRecord("CASE-3", "E119", diagnosis_sequence=2),
      DiagnosisRecord("CASE-3", "I509", diagnosis_sequence=2, present_on_admission="Y"),
    ),
    options=ScoringOptions(model_version="elixhauser_v2026_1"),
  )

  rows = explain_result.interaction_details.rows
  assert {row["detail_type"] for row in rows} == {"comorbidity_measure"}
  assert {row["detail_name"] for row in rows} == {"CMR_DIAB_UNCX", "CMR_HF"}


def test_score_subjects_uses_real_v28_reference_tables() -> None:
  request = ScoringRequest(
    subjects=(
      _subject(
        "BENE-1",
        date_of_birth=date(1953, 5, 1),
        sex=2,
        orec=0,
      ),
    ),
    diagnoses=(
      _diagnosis("BENE-1", "E119"),
      _diagnosis("BENE-1", "I509"),
      _diagnosis("BENE-1", "J449"),
    ),
  )

  result = score_subjects(request)
  predictor_row = result.predictors.subject_predictors.rows[0]
  score_row = result.scores.subject_scores.rows[0]

  assert predictor_row["ce_age_sex_cell"] == "F70_74"
  assert predictor_row["mapped_cc_count"] == 3
  assert predictor_row["active_hcc_count"] == 3
  assert predictor_row["diagnosis_category_count"] == 3
  assert predictor_row["interaction_count"] == 2
  assert predictor_row["payment_hcc_count_bucket"] == "3"
  assert predictor_row["HCC38"] == 1
  assert predictor_row["HCC226"] == 1
  assert predictor_row["HCC280"] == 1
  assert predictor_row["DIABETES_V28"] == 1
  assert predictor_row["HF_V28"] == 1
  assert predictor_row["CHR_LUNG_V28"] == 1
  assert predictor_row["DIABETES_HF_V28"] == 1
  assert predictor_row["HF_CHR_LUNG_V28"] == 1

  assert score_row["score_community_na"] == pytest.approx(1.43)
  assert score_row["score_institutional"] == pytest.approx(2.282)

  community_na_interaction = next(
    row
    for row in result.scores.score_contributions.rows
    if row["score_family"] == "community_na" and row["variable_name"] == "DIABETES_HF_V28"
  )
  assert community_na_interaction["contribution"] == pytest.approx(0.112)
  assert community_na_interaction["contribution_status"] == "applied"

  explain_result = explain_subject_raf(request.subjects[0], request.diagnoses)
  assert len(explain_result.interaction_details.rows) == 10
  assert explain_result.raf_totals.rows[0]["raf_total"] == score_row["score_community_na"]


def test_score_subjects_supports_real_v22_reference_tables() -> None:
  request = ScoringRequest(
    subjects=(
      _subject(
        "BENE-V22-1",
        date_of_birth=date(1953, 5, 1),
        sex=2,
        orec=0,
      ),
    ),
    diagnoses=(
      _diagnosis("BENE-V22-1", "E119"),
      _diagnosis("BENE-V22-1", "I509"),
      _diagnosis("BENE-V22-1", "J449"),
    ),
    options=ScoringOptions(model_version="cms_hcc_v22_2026"),
  )

  result = score_subjects(request)
  predictor_row = result.predictors.subject_predictors.rows[0]
  score_row = result.scores.subject_scores.rows[0]

  assert predictor_row["ce_age_sex_cell"] == "F70_74"
  assert predictor_row["mapped_cc_count"] == 3
  assert predictor_row["active_hcc_count"] == 3
  assert predictor_row["diagnosis_category_count"] == 3
  assert predictor_row["interaction_count"] == 4
  assert predictor_row["payment_hcc_count_bucket"] == "3"
  assert predictor_row["HCC19"] == 1
  assert predictor_row["HCC85"] == 1
  assert predictor_row["HCC111"] == 1
  assert predictor_row["DIABETES"] == 1
  assert predictor_row["CHF"] == 1
  assert predictor_row["gCopdCF"] == 1
  assert predictor_row["HCC85_gDiabetesMellit"] == 1
  assert predictor_row["HCC85_gCopdCF"] == 1
  assert predictor_row["CHF_gCopdCF"] == 1
  assert predictor_row["DIABETES_CHF"] == 1

  assert score_row["score_community_na"] == pytest.approx(1.473)
  assert score_row["score_institutional"] == pytest.approx(2.066)

  community_na_interaction = next(
    row
    for row in result.scores.score_contributions.rows
    if row["score_family"] == "community_na" and row["variable_name"] == "HCC85_gDiabetesMellit"
  )
  assert community_na_interaction["contribution"] == pytest.approx(0.154)
  assert community_na_interaction["contribution_status"] == "applied"

  explain_result = explain_subject_raf(
    request.subjects[0],
    request.diagnoses,
    options=request.options,
  )
  assert len(explain_result.interaction_details.rows) == 14
  assert explain_result.raf_totals.rows[0]["raf_total"] == score_row["score_community_na"]


def test_score_subjects_supports_real_esrd_v21_reference_tables() -> None:
  request = ScoringRequest(
    subjects=(
      SubjectRecord(
        subject_id="ESRD-V21-1",
        date_of_birth=date(1953, 5, 1),
        sex=2,
        original_reason_entitlement_code=0,
        medicaid_flag=1,
        new_enrollee_medicaid_flag=0,
      ),
    ),
    diagnoses=(
      _diagnosis("ESRD-V21-1", "A0103"),
    ),
    options=ScoringOptions(model_version="esrd_v21_2026"),
  )

  result = score_subjects(request)
  predictor_row = result.predictors.subject_predictors.rows[0]
  score_row = result.scores.subject_scores.rows[0]

  assert predictor_row["ce_age_sex_cell"] == "F70_74"
  assert predictor_row["ne_age_sex_cell"] == "NEF70_74"
  assert predictor_row["ne_graft_age_sex_cell"] == "NEF70_74"
  assert predictor_row["mapped_cc_count"] == 1
  assert predictor_row["active_hcc_count"] == 1
  assert predictor_row["HCC115"] == 1

  assert score_row["score_dial"] == pytest.approx(0.733)
  assert score_row["score_graft_comm_dur4_9_ge65"] == pytest.approx(3.342)
  assert score_row["score_graft_inst_dur10pl_ge65"] == pytest.approx(2.458)
  assert score_row["score_graft_ne_dur4_9_ge65"] == pytest.approx(3.252)
  assert score_row["score_transplant_kidney_only_1m"] == pytest.approx(6.03)
  assert score_row["score_transplant_kidney_only_2m"] == pytest.approx(0.895)

  graft_comm_rows = [
    row
    for row in result.scores.score_contributions.rows
    if row["score_family"] == "graft_comm_dur4_9_ge65"
  ]
  assert sum(_numeric(row["contribution"]) for row in graft_comm_rows) == pytest.approx(
    _numeric(score_row["score_graft_comm_dur4_9_ge65"]),
  )
  assert _contribution_row(
    result.scores.score_contributions.rows,
    score_family="graft_comm_dur4_9_ge65",
    variable_name="dur4_9_ge65",
  )["coefficient"] == pytest.approx(2.562)


def test_score_subjects_supports_real_esrd_v24_reference_tables() -> None:
  request = ScoringRequest(
    subjects=(
      SubjectRecord(
        subject_id="ESRD-V24-1",
        date_of_birth=date(1953, 5, 1),
        sex=2,
        original_reason_entitlement_code=0,
        full_benefit_dual_flag=1,
        partial_benefit_dual_flag=0,
        long_term_institutional_flag=0,
      ),
    ),
    diagnoses=(
      _diagnosis("ESRD-V24-1", "A0103"),
    ),
    options=ScoringOptions(model_version="esrd_v24_2026"),
  )

  result = score_subjects(request)
  predictor_row = result.predictors.subject_predictors.rows[0]
  score_row = result.scores.subject_scores.rows[0]

  assert predictor_row["ce_age_sex_cell"] == "F70_74"
  assert predictor_row["ne_age_sex_cell"] == "NEF70_74"
  assert predictor_row["ne_graft_age_sex_cell"] == "NEF70_74"
  assert predictor_row["mapped_cc_count"] == 1
  assert predictor_row["active_hcc_count"] == 1
  assert predictor_row["HCC115"] == 1
  assert predictor_row["FBDual_Female_Aged"] == 1
  assert predictor_row["PBDual_Female_Aged"] == 0
  assert predictor_row["LTI_Aged"] == 0

  assert score_row["score_dial"] == pytest.approx(0.714)
  assert score_row["score_g_comm_fbd_ge65_dur4_9"] == pytest.approx(3.317)
  assert score_row["score_graft_inst_fbd_ge65_dur4_9"] == pytest.approx(3.961)
  assert score_row["score_graft_ne_ge65_dur4_9_fbd"] == pytest.approx(4.021)
  assert score_row["score_transplant_kidney_only_1m"] == pytest.approx(5.985)

  graft_ne_rows = [
    row
    for row in result.scores.score_contributions.rows
    if row["score_family"] == "graft_ne_ge65_dur4_9_fbd"
  ]
  assert sum(_numeric(row["contribution"]) for row in graft_ne_rows) == pytest.approx(
    _numeric(score_row["score_graft_ne_ge65_dur4_9_fbd"]),
  )
  assert _contribution_row(
    result.scores.score_contributions.rows,
    score_family="graft_ne_ge65_dur4_9_fbd",
    variable_name="FBD_NORIGDIS_G_NEF70_74",
  )["coefficient"] == pytest.approx(1.1425414364640885)
  assert _contribution_row(
    result.scores.score_contributions.rows,
    score_family="graft_ne_ge65_dur4_9_fbd",
    variable_name="ge65_dur4_9_fbd",
  )["coefficient"] == pytest.approx(2.8784530386740332)


@pytest.mark.parametrize("model_version", ("esrd_v21_2026", "esrd_v24_2026"))
def test_generate_predictors_applies_esrd_hierarchies(model_version: str) -> None:
  if model_version == "esrd_v21_2026":
    subject = SubjectRecord(
      subject_id="ESRD-HIER",
      date_of_birth=date(1950, 1, 1),
      sex=1,
      original_reason_entitlement_code=0,
      medicaid_flag=1,
      new_enrollee_medicaid_flag=0,
    )
  else:
    subject = SubjectRecord(
      subject_id="ESRD-HIER",
      date_of_birth=date(1950, 1, 1),
      sex=1,
      original_reason_entitlement_code=0,
      full_benefit_dual_flag=1,
      partial_benefit_dual_flag=0,
      long_term_institutional_flag=0,
    )

  explain_result = explain_subject_raf(
    subject,
    (
      _diagnosis("ESRD-HIER", "E0800"),
      _diagnosis("ESRD-HIER", "E119"),
    ),
    options=ScoringOptions(model_version=model_version),
  )
  hierarchy_rows = {
    row["mapped_hcc"]: row
    for row in explain_result.hierarchy_effects.rows
    if row["mapped_hcc"]
  }

  assert hierarchy_rows["HCC17"]["hierarchy_status"] == "active"
  assert hierarchy_rows["HCC19"]["hierarchy_status"] == "suppressed"
  assert hierarchy_rows["HCC19"]["recode_note"] == "suppressed_by_HCC17"
  assert explain_result.subject_predictors.rows[0]["active_hcc_count"] == 1
  assert explain_result.subject_predictors.rows[0]["HCC17"] == 1
  assert explain_result.subject_predictors.rows[0]["HCC19"] == 0


@pytest.mark.parametrize(
  ("model_version", "expected_ce_lti", "expected_ne_lti"),
  (
    ("rxhcc_v8_t_2026", 2.529, 2.358),
    ("rxhcc_v8_x_2026", 2.695, 2.316),
  ),
)
def test_score_subjects_supports_real_rxhcc_reference_tables(
  model_version: str,
  expected_ce_lti: float,
  expected_ne_lti: float,
) -> None:
  request = ScoringRequest(
    subjects=(
      SubjectRecord(
        subject_id=f"RX-{model_version}",
        date_of_birth=date(1970, 1, 1),
        sex=1,
        original_reason_entitlement_code=0,
        concurrent_esrd_flag=1,
      ),
    ),
    diagnoses=(
      _diagnosis(f"RX-{model_version}", "F200"),
    ),
    options=ScoringOptions(model_version=model_version),
  )

  result = score_subjects(request)
  predictor_row = result.predictors.subject_predictors.rows[0]
  mapping_row = result.predictors.diagnosis_mappings.rows[0]
  score_row = result.scores.subject_scores.rows[0]
  explain_result = explain_subject_raf(
    request.subjects[0],
    request.diagnoses,
    options=request.options,
  )

  assert mapping_row["mapped_cc"] == "RXCC130"
  assert mapping_row["mapped_hcc"] == "RXHCC130"
  assert predictor_row["ce_age_sex_cell"] == "M55_59"
  assert predictor_row["ne_age_sex_cell"] == "NEM55_59"
  assert predictor_row["mapped_cc_count"] == 1
  assert predictor_row["active_hcc_count"] == 1
  assert predictor_row["RXHCC130"] == 1
  assert predictor_row["NONAGED_RXHCC130"] == 1

  assert score_row["score_ce_lti"] == pytest.approx(expected_ce_lti)
  assert score_row["score_ne_lti"] == pytest.approx(expected_ne_lti)
  assert _contribution_row(
    result.scores.score_contributions.rows,
    score_family="ce_lti",
    variable_name="NONAGED_RXHCC130",
  )["contribution_status"] == "applied"
  assert {row["detail_type"] for row in explain_result.interaction_details.rows} == {
    "active_hcc",
    "summary",
  }


@pytest.mark.parametrize("model_version", ("rxhcc_v8_t_2026", "rxhcc_v8_x_2026"))
def test_generate_predictors_applies_rxhcc_hierarchies(model_version: str) -> None:
  explain_result = explain_subject_raf(
    SubjectRecord(
      subject_id="RX-HIER",
      date_of_birth=date(1953, 5, 1),
      sex=2,
      original_reason_entitlement_code=0,
      concurrent_esrd_flag=1,
    ),
    (
      _diagnosis("RX-HIER", "C9210"),
      _diagnosis("RX-HIER", "C7900"),
    ),
    options=ScoringOptions(model_version=model_version),
  )
  hierarchy_rows = {
    row["mapped_hcc"]: row
    for row in explain_result.hierarchy_effects.rows
    if row["mapped_hcc"]
  }

  assert hierarchy_rows["RXHCC15"]["hierarchy_status"] == "active"
  assert hierarchy_rows["RXHCC17"]["hierarchy_status"] == "suppressed"
  assert hierarchy_rows["RXHCC17"]["recode_note"] == "suppressed_by_RXHCC15"
  assert explain_result.subject_predictors.rows[0]["active_hcc_count"] == 1
  assert explain_result.subject_predictors.rows[0]["RXHCC15"] == 1
  assert explain_result.subject_predictors.rows[0]["RXHCC17"] == 0


def test_generate_predictors_derives_rxhcc_count_buckets_and_nonaged_overlays() -> None:
  five_hcc_request = ScoringRequest(
    subjects=(
      SubjectRecord(
        subject_id="RX-COUNT-5",
        date_of_birth=date(1970, 1, 1),
        sex=1,
        original_reason_entitlement_code=0,
        concurrent_esrd_flag=0,
      ),
    ),
    diagnoses=tuple(
      _diagnosis("RX-COUNT-5", code)
      for code in ("F200", "G300", "D693", "G7000", "B0082")
    ),
    options=ScoringOptions(model_version="rxhcc_v8_t_2026"),
  )
  ten_hcc_request = ScoringRequest(
    subjects=(
      SubjectRecord(
        subject_id="RX-COUNT-10",
        date_of_birth=date(1970, 1, 1),
        sex=1,
        original_reason_entitlement_code=0,
        concurrent_esrd_flag=0,
      ),
    ),
    diagnoses=tuple(
      _diagnosis("RX-COUNT-10", code)
      for code in (
        "B20",
        "D693",
        "G300",
        "F200",
        "F72",
        "C9210",
        "G7000",
        "G1220",
        "B0082",
        "G6181",
      )
    ),
    options=ScoringOptions(model_version="rxhcc_v8_t_2026"),
  )

  five_hcc_predictors = score_subjects(five_hcc_request).predictors.subject_predictors.rows[0]
  ten_hcc_predictors = score_subjects(ten_hcc_request).predictors.subject_predictors.rows[0]

  assert five_hcc_predictors["NONAGED"] == 1
  assert five_hcc_predictors["NONAGED_RXHCC130"] == 1
  assert five_hcc_predictors["mapped_cc_count"] == 5
  assert five_hcc_predictors["active_hcc_count"] == 5
  assert five_hcc_predictors["RXHCC_COUNT5"] == 1
  assert five_hcc_predictors["RXHCC_COUNT10P"] == 0

  assert ten_hcc_predictors["mapped_cc_count"] == 10
  assert ten_hcc_predictors["active_hcc_count"] == 10
  assert ten_hcc_predictors["RXHCC_COUNT5"] == 0
  assert ten_hcc_predictors["RXHCC_COUNT10P"] == 1


def test_generate_predictors_applies_mce_edits_and_hierarchies() -> None:
  mce_request = ScoringRequest(
    subjects=(
      _subject(
        "CHILD-1",
        date_of_birth=date(2015, 1, 1),
        sex=2,
        orec=0,
      ),
    ),
    diagnoses=(_diagnosis("CHILD-1", "E8411"),),
    options=ScoringOptions(apply_mce_edits=True),
  )
  no_mce_request = ScoringRequest(
    subjects=mce_request.subjects,
    diagnoses=mce_request.diagnoses,
    options=ScoringOptions(apply_mce_edits=False),
  )

  with_mce = generate_predictors(mce_request)
  without_mce = generate_predictors(no_mce_request)

  assert with_mce.diagnosis_mappings.rows[0]["mapping_status"] == "mce_age_rejected"
  assert with_mce.diagnosis_mappings.rows[0]["applied_mce_edits"] is True
  assert without_mce.diagnosis_mappings.rows[0]["mapping_status"] == "mapped"
  assert without_mce.diagnosis_mappings.rows[0]["applied_mce_edits"] is False

  hierarchy_subject = _subject(
    "BENE-2",
    date_of_birth=date(1950, 1, 1),
    sex=1,
    orec=0,
  )
  hierarchy_result = explain_subject_raf(
    hierarchy_subject,
    (
      _diagnosis("BENE-2", "I509"),
      _diagnosis("BENE-2", "T8620"),
    ),
  )
  hierarchy_rows = {
    row["mapped_hcc"]: row
    for row in hierarchy_result.hierarchy_effects.rows
    if row["mapped_hcc"]
  }

  assert hierarchy_rows["HCC221"]["hierarchy_status"] == "active"
  assert hierarchy_rows["HCC226"]["hierarchy_status"] == "suppressed"
  assert hierarchy_rows["HCC226"]["recode_note"] == "suppressed_by_HCC221"
  assert hierarchy_result.subject_predictors.rows[0]["active_hcc_count"] == 1
  assert hierarchy_result.subject_predictors.rows[0]["HCC221"] == 1
  assert hierarchy_result.subject_predictors.rows[0]["HCC226"] == 0


def test_generate_predictors_applies_v22_hierarchies() -> None:
  hierarchy_subject = _subject(
    "BENE-V22-2",
    date_of_birth=date(1950, 1, 1),
    sex=1,
    orec=0,
  )
  hierarchy_result = explain_subject_raf(
    hierarchy_subject,
    (
      _diagnosis("BENE-V22-2", "E0800"),
      _diagnosis("BENE-V22-2", "E119"),
    ),
    options=ScoringOptions(model_version="cms_hcc_v22_2026"),
  )
  hierarchy_rows = {
    row["mapped_hcc"]: row
    for row in hierarchy_result.hierarchy_effects.rows
    if row["mapped_hcc"]
  }

  assert hierarchy_rows["HCC17"]["hierarchy_status"] == "active"
  assert hierarchy_rows["HCC19"]["hierarchy_status"] == "suppressed"
  assert hierarchy_rows["HCC19"]["recode_note"] == "suppressed_by_HCC17"
  assert hierarchy_result.subject_predictors.rows[0]["active_hcc_count"] == 1
  assert hierarchy_result.subject_predictors.rows[0]["HCC17"] == 1
  assert hierarchy_result.subject_predictors.rows[0]["HCC19"] == 0


def test_score_subjects_can_hide_optional_artifacts() -> None:
  request = ScoringRequest(
    subjects=(
      _subject(
        "BENE-3",
        date_of_birth=date(1954, 1, 1),
        sex=1,
        orec=0,
      ),
    ),
    diagnoses=(_diagnosis("BENE-3", "E119"),),
    options=ScoringOptions(
      include_diagnosis_mappings=False,
      include_score_contributions=False,
    ),
  )

  result = score_subjects(request)

  assert result.predictors.diagnosis_mappings.rows == ()
  assert result.predictors.diagnosis_mappings.name == "diagnosis_mappings"
  assert result.scores.score_contributions.rows == ()
  assert result.scores.score_contributions.name == "score_contributions"
  assert _numeric(result.scores.subject_scores.rows[0]["score_community_na"]) > 0
