"""Public orchestration for the typed RAF scoring core."""

from __future__ import annotations

from risk_compose._predictors import (
  DIAGNOSIS_MAPPING_COLUMNS,
  build_interaction_details,
  derive_subject_flags,
  derive_interactions,
  map_diagnoses_to_ccs,
  resolve_hcc_hierarchies,
)
from risk_compose._scoring import (
  SCORE_CONTRIBUTION_COLUMNS,
  build_raf_totals,
  calculate_scores,
)
from risk_compose.registry import get_model_spec
from risk_compose.source_prep import prepare_scoring_inputs as _prepare_scoring_inputs
from risk_compose.types import (
  SubjectExplainResult,
  SubjectRecord,
  DiagnosisRecord,
  ModelSpec,
  PreparedScoringInputs,
  PredictorArtifacts,
  ScoreArtifacts,
  ScoringOptions,
  ScoringRequest,
  ScoringResult,
  SourcePreparationRequest,
  TableArtifact,
  ValidationIssue,
)
from risk_compose.validation import enforce_strict_validation, validate_scoring_request


def validate_request(
  request: ScoringRequest,
  *,
  model_spec: ModelSpec | None = None,
) -> tuple[ScoringRequest, tuple[ValidationIssue, ...]]:
  """Validate a scoring request and return the collected issues."""
  resolved_model_spec = _resolve_model_spec(request, model_spec)
  return validate_scoring_request(request, resolved_model_spec)


def prepare_scoring_inputs(source_request: SourcePreparationRequest) -> PreparedScoringInputs:
  """Prepare canonical scoring inputs from a declared source specification."""
  return _prepare_scoring_inputs(source_request)


def generate_predictors(
  request: ScoringRequest,
  *,
  model_spec: ModelSpec | None = None,
) -> PredictorArtifacts:
  """Validate a scoring request and derive model-specific predictor artifacts."""
  resolved_model_spec, issues, diagnosis_mappings, _, subject_predictors = _run_predictor_pipeline(
    request,
    model_spec=model_spec,
  )
  return PredictorArtifacts(
    model_spec=resolved_model_spec,
    subject_predictors=subject_predictors,
    diagnosis_mappings=_public_diagnosis_mappings(diagnosis_mappings, request.options),
    validation_issues=issues,
  )


def generate_scores(
  predictors: PredictorArtifacts,
  *,
  options: ScoringOptions | None = None,
) -> ScoreArtifacts:
  """Apply model-specific coefficient families to predictor artifacts."""
  resolved_options = options or ScoringOptions(model_version=predictors.model_spec.version_id)
  score_artifacts = calculate_scores(
    predictors.subject_predictors,
    predictors.model_spec,
    options=resolved_options,
  )
  return ScoreArtifacts(
    model_spec=predictors.model_spec,
    subject_scores=score_artifacts.subject_scores,
    score_contributions=_public_score_contributions(
      score_artifacts.score_contributions,
      resolved_options,
    ),
    validation_issues=predictors.validation_issues + score_artifacts.validation_issues,
  )


def score_subjects(
  request: ScoringRequest,
  *,
  model_spec: ModelSpec | None = None,
) -> ScoringResult:
  """Run end-to-end validation, predictor generation, and score assembly."""
  predictors = generate_predictors(request, model_spec=model_spec)
  scores = generate_scores(predictors, options=request.options)
  return ScoringResult(
    model_spec=predictors.model_spec,
    predictors=predictors,
    scores=scores,
    validation_issues=scores.validation_issues,
  )


def generate_hcc_scores(
  predictors: PredictorArtifacts,
  *,
  options: ScoringOptions | None = None,
) -> ScoreArtifacts:
  """Backward-compatible alias for ``generate_scores``."""
  return generate_scores(predictors, options=options)


def score_from_source(source_request: SourcePreparationRequest) -> ScoringResult:
  """Prepare canonical inputs from a declared source and score them."""
  prepared_inputs = prepare_scoring_inputs(source_request)
  _enforce_supported_source_model(prepared_inputs.preparation_issues)
  return _score_prepared_inputs(prepared_inputs)


def explain_subject_raf(
  subject: SubjectRecord,
  diagnoses: tuple[DiagnosisRecord, ...] | list[DiagnosisRecord],
  *,
  options: ScoringOptions | None = None,
) -> SubjectExplainResult:
  """Build a structured RAF explanation for a single subject."""
  accepted_diagnoses = tuple(
    diagnosis
    for diagnosis in tuple(diagnoses)
    if diagnosis.subject_id == subject.subject_id
  )
  filtered_out_count = len(tuple(diagnoses)) - len(accepted_diagnoses)
  request = ScoringRequest(
    subjects=(subject,),
    diagnoses=accepted_diagnoses,
    options=options or ScoringOptions(),
  )
  resolved_model_spec, issues, diagnosis_mappings, hierarchy_artifact, subject_predictors = _run_predictor_pipeline(
    request,
  )
  score_artifacts = calculate_scores(
    subject_predictors,
    resolved_model_spec,
    options=request.options,
  )
  validation_issues = issues + score_artifacts.validation_issues
  if filtered_out_count:
    validation_issues = validation_issues + (
      ValidationIssue(
        severity="warning",
        code="filtered_explain_diagnoses",
        message=(
          "Ignored diagnoses whose subject_id did not match the requested subject."
        ),
        subject_id=subject.subject_id,
      ),
    )
  return SubjectExplainResult(
    model_spec=resolved_model_spec,
    subject_summary=_build_subject_summary(
      subject_predictors,
      diagnosis_mappings,
    ),
    subject_predictors=subject_predictors,
    diagnosis_mappings=_public_diagnosis_mappings(diagnosis_mappings, request.options),
    hierarchy_effects=hierarchy_artifact,
    interaction_details=build_interaction_details(subject_predictors, resolved_model_spec),
    score_contributions=_public_score_contributions(
      score_artifacts.score_contributions,
      request.options,
    ),
    subject_scores=score_artifacts.subject_scores,
    raf_totals=build_raf_totals(score_artifacts.subject_scores, resolved_model_spec),
    validation_issues=validation_issues,
  )


def _resolve_model_spec(
  request: ScoringRequest,
  model_spec: ModelSpec | None,
) -> ModelSpec:
  """Resolve the model spec from an explicit override or request options."""
  return model_spec or get_model_spec(request.options.model_version)


def _run_predictor_pipeline(
  request: ScoringRequest,
  *,
  model_spec: ModelSpec | None = None,
) -> tuple[ModelSpec, tuple[ValidationIssue, ...], TableArtifact, TableArtifact, TableArtifact]:
  """Run the predictor pipeline and return intermediate artifacts for reuse."""
  resolved_model_spec = _resolve_model_spec(request, model_spec)
  validated_request, issues = validate_scoring_request(request, resolved_model_spec)
  subject_flags = derive_subject_flags(validated_request, resolved_model_spec)
  diagnosis_mappings = map_diagnoses_to_ccs(validated_request, resolved_model_spec)
  hierarchy_artifact = resolve_hcc_hierarchies(diagnosis_mappings, resolved_model_spec)
  interaction_source = diagnosis_mappings if resolved_model_spec.family == "ahrq_elixhauser" else hierarchy_artifact
  subject_predictors = derive_interactions(
    subject_flags,
    interaction_source,
    resolved_model_spec,
  )
  return resolved_model_spec, issues, diagnosis_mappings, hierarchy_artifact, subject_predictors


def _score_prepared_inputs(prepared_inputs: PreparedScoringInputs) -> ScoringResult:
  """Score already-prepared canonical inputs and merge preparation issues."""
  result = score_subjects(prepared_inputs.scoring_request)
  merged_issues = prepared_inputs.preparation_issues + result.validation_issues
  predictors = PredictorArtifacts(
    model_spec=result.predictors.model_spec,
    subject_predictors=result.predictors.subject_predictors,
    diagnosis_mappings=result.predictors.diagnosis_mappings,
    validation_issues=prepared_inputs.preparation_issues + result.predictors.validation_issues,
  )
  scores = ScoreArtifacts(
    model_spec=result.scores.model_spec,
    subject_scores=result.scores.subject_scores,
    score_contributions=result.scores.score_contributions,
    validation_issues=prepared_inputs.preparation_issues + result.scores.validation_issues,
  )
  return ScoringResult(
    model_spec=result.model_spec,
    predictors=predictors,
    scores=scores,
    validation_issues=merged_issues,
  )


def _enforce_supported_source_model(issues: tuple[ValidationIssue, ...]) -> None:
  """Raise when source workflows are asked to run unsupported model families."""
  enforce_strict_validation(
    tuple(
      issue
      for issue in issues
      if issue.code in {"unsupported_source_model_version", "unsupported_source_model_family"}
    ),
  )


def _public_diagnosis_mappings(
  diagnosis_mappings: TableArtifact,
  options: ScoringOptions,
) -> TableArtifact:
  """Return the public diagnosis-mapping artifact for the current options."""
  if options.include_diagnosis_mappings:
    return diagnosis_mappings
  return TableArtifact.empty("diagnosis_mappings", DIAGNOSIS_MAPPING_COLUMNS)


def _public_score_contributions(
  score_contributions: TableArtifact,
  options: ScoringOptions,
) -> TableArtifact:
  """Return the public score-contribution artifact for the current options."""
  if options.include_score_contributions:
    return score_contributions
  return TableArtifact.empty("score_contributions", SCORE_CONTRIBUTION_COLUMNS)


def _build_subject_summary(
  subject_predictors: TableArtifact,
  diagnosis_mappings: TableArtifact,
) -> TableArtifact:
  """Build a single-subject summary artifact for explanation outputs."""
  predictor_row = subject_predictors.rows[0] if subject_predictors.rows else {}
  subject_id = predictor_row.get("subject_id")
  diagnosis_count = sum(
    1
    for mapping_row in diagnosis_mappings.rows
    if mapping_row.get("subject_id") == subject_id
  )
  return TableArtifact(
    name="subject_summary",
    columns=(
      "subject_id",
      "model_version",
      "age",
      "sex",
      "original_reason_entitlement_code",
      "diagnosis_count",
    ),
    rows=(
      {
        "subject_id": subject_id,
        "model_version": predictor_row.get("model_version"),
        "age": predictor_row.get("age"),
        "sex": predictor_row.get("sex"),
        "original_reason_entitlement_code": predictor_row.get("original_reason_entitlement_code"),
        "diagnosis_count": diagnosis_count,
      },
    )
    if predictor_row
    else (),
  )
