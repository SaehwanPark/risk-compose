"""Typed risk-adjustment scoring library."""

from pkgutil import extend_path

from risk_compose.core import (
  explain_subject_raf,
  generate_scores,
  generate_hcc_scores,
  generate_predictors,
  prepare_scoring_inputs,
  score_subjects,
  score_from_source,
)
from risk_compose.registry import DEFAULT_MODEL_VERSION, get_model_spec
from risk_compose.types import (
  SubjectExplainResult,
  SubjectRecord,
  DatabaseTableSpec,
  DatabaseSourceSpec,
  DiagnosisRecord,
  EngineArtifacts,
  FlatFileTableSpec,
  FlatFileSourceSpec,
  ModelSpec,
  PredictorArtifacts,
  PreparedScoringInputs,
  ScoreArtifacts,
  ScoringOptions,
  ScoringRequest,
  ScoringResult,
  SourceRole,
  SourcePreparationRequest,
  SourceProfile,
  TableArtifact,
  ValidationIssue,
)

__path__ = extend_path(__path__, __name__)

__all__ = [
  "DEFAULT_MODEL_VERSION",
  "SubjectExplainResult",
  "SubjectRecord",
  "DatabaseTableSpec",
  "DatabaseSourceSpec",
  "DiagnosisRecord",
  "EngineArtifacts",
  "FlatFileTableSpec",
  "FlatFileSourceSpec",
  "ModelSpec",
  "PredictorArtifacts",
  "PreparedScoringInputs",
  "ScoreArtifacts",
  "ScoringOptions",
  "ScoringRequest",
  "ScoringResult",
  "SourceRole",
  "SourcePreparationRequest",
  "SourceProfile",
  "TableArtifact",
  "ValidationIssue",
  "explain_subject_raf",
  "generate_scores",
  "generate_hcc_scores",
  "generate_predictors",
  "get_model_spec",
  "prepare_scoring_inputs",
  "score_subjects",
  "score_from_source",
]
