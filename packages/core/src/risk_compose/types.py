"""Public types for the typed RAF scoring scaffold."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Generic, Literal, TypeVar

from risk_compose._typing import ArtifactRow

ValidationSeverity = Literal["error", "warning", "info"]
SourceProfile = Literal["cms_purchased_files_ffs_2026", "ccw_vrdc_ffs_2026"]
SourceRole = Literal[
  "subject",
  "hospital_inpatient",
  "hospital_outpatient",
  "professional",
  "dme",
  "hha",
  "snf",
  "hospice",
]
FrameT = TypeVar("FrameT")


@dataclass(frozen=True, slots=True)
class ModelSpec:
  """Metadata and reference paths for a supported scoring model version."""

  version_id: str
  payment_year: int
  family: str
  model_version: str
  package_variant: str
  cutoff_date: date
  score_families: tuple[str, ...]
  reference_paths: dict[str, Path]
  notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SubjectRecord:
  """Canonical subject input for the scoring core."""

  subject_id: str
  date_of_birth: date | None
  sex: int | None
  original_reason_entitlement_code: int | None
  limited_income_medicaid_flag: int | None = None
  new_enrollee_medicaid_flag: int | None = None
  concurrent_esrd_flag: int | None = None
  medicaid_flag: int | None = None
  full_benefit_dual_flag: int | None = None
  partial_benefit_dual_flag: int | None = None
  long_term_institutional_flag: int | None = None


@dataclass(frozen=True, slots=True)
class DiagnosisRecord:
  """Canonical diagnosis input for the scoring core."""

  subject_id: str
  icd10_code: str
  service_date: date | None = None
  claim_id: str | None = None
  source: str | None = None
  diagnosis_sequence: int | None = None
  present_on_admission: str | None = None


@dataclass(frozen=True, slots=True)
class ScoringOptions:
  """Run-level switches for the scoring pipeline."""

  model_version: str = "cms_hcc_v28_2026"
  apply_mce_edits: bool = True
  strict_validation: bool = False
  include_diagnosis_mappings: bool = True
  include_score_contributions: bool = True
  score_round_digits: int = 3


@dataclass(frozen=True, slots=True)
class ScoringRequest:
  """Canonical typed request for predictor generation and scoring."""

  subjects: tuple[SubjectRecord, ...]
  diagnoses: tuple[DiagnosisRecord, ...]
  options: ScoringOptions = field(default_factory=ScoringOptions)

  def __post_init__(self) -> None:
    object.__setattr__(self, "subjects", tuple(self.subjects))
    object.__setattr__(self, "diagnoses", tuple(self.diagnoses))


@dataclass(frozen=True, slots=True)
class FlatFileTableSpec:
  """Declarative flat-file table source for one logical role."""

  path: Path
  columns: dict[str, str] = field(default_factory=dict)
  filter: str | None = None


@dataclass(frozen=True, slots=True)
class DatabaseTableSpec:
  """Declarative database table or view source for one logical role."""

  locator: str
  columns: dict[str, str] = field(default_factory=dict)
  schema_name: str | None = None
  filter: str | None = None


@dataclass(frozen=True, slots=True)
class FlatFileSourceSpec:
  """Declarative manifest of flat-file sources keyed by logical role."""

  source_profile: SourceProfile | str
  sources: dict[SourceRole | str, FlatFileTableSpec]
  file_format: str = "csv"


@dataclass(frozen=True, slots=True)
class DatabaseSourceSpec:
  """Declarative manifest of database sources keyed by logical role."""

  source_profile: SourceProfile | str
  sources: dict[SourceRole | str, DatabaseTableSpec]


@dataclass(frozen=True, slots=True)
class SourcePreparationRequest:
  """Request for preparing canonical scoring inputs from a declared source."""

  source_spec: FlatFileSourceSpec | DatabaseSourceSpec
  options: ScoringOptions = field(default_factory=ScoringOptions)


@dataclass(frozen=True, slots=True)
class TableArtifact:
  """Deterministic row-and-column artifact returned by the scoring core."""

  name: str
  columns: tuple[str, ...]
  rows: tuple[ArtifactRow, ...] = ()

  @classmethod
  def empty(cls, name: str, columns: tuple[str, ...]) -> "TableArtifact":
    """Create an empty artifact with a stable schema."""
    return cls(name=name, columns=columns, rows=())


@dataclass(frozen=True, slots=True)
class ValidationIssue:
  """Structured validation issue surfaced by the core and CLI."""

  severity: ValidationSeverity
  code: str
  message: str
  subject_id: str | None = None
  field_name: str | None = None


@dataclass(frozen=True, slots=True)
class PreparedScoringInputs:
  """Prepared canonical scoring inputs derived from a declared source."""

  scoring_request: ScoringRequest
  prepared_subjects: TableArtifact
  prepared_diagnoses: TableArtifact
  rejected_diagnosis_candidates: TableArtifact
  source_lineage: TableArtifact
  preparation_issues: tuple[ValidationIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class PredictorArtifacts:
  """Predictor-stage artifacts returned by the core."""

  model_spec: ModelSpec
  subject_predictors: TableArtifact
  diagnosis_mappings: TableArtifact
  validation_issues: tuple[ValidationIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class ScoreArtifacts:
  """Score-stage artifacts returned by the core."""

  model_spec: ModelSpec
  subject_scores: TableArtifact
  score_contributions: TableArtifact
  validation_issues: tuple[ValidationIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class ScoringResult:
  """End-to-end result bundle for subject scoring."""

  model_spec: ModelSpec
  predictors: PredictorArtifacts
  scores: ScoreArtifacts
  validation_issues: tuple[ValidationIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class SubjectExplainResult:
  """Structured one-subject RAF explanation bundle."""

  model_spec: ModelSpec
  subject_summary: TableArtifact
  subject_predictors: TableArtifact
  diagnosis_mappings: TableArtifact
  hierarchy_effects: TableArtifact
  interaction_details: TableArtifact
  score_contributions: TableArtifact
  subject_scores: TableArtifact
  raf_totals: TableArtifact
  validation_issues: tuple[ValidationIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class EngineArtifacts(Generic[FrameT]):
  """Engine-native artifact bundle returned by dataframe adapters."""

  subject_predictors: FrameT
  subject_scores: FrameT
  diagnosis_mappings: FrameT
  score_contributions: FrameT
  validation_issues: FrameT
