"""Shared review-session logic for the terminal and GUI frontends."""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Literal

from risk_compose._typing import ArtifactRow, ArtifactRowMapping
from risk_compose._artifact_io import (
  EXPLAIN_EXPORT_FILENAMES,
  SCORE_EXPORT_FILENAMES,
  read_csv_rows,
  read_table_artifact_csv,
  write_artifact_csv,
)
from risk_compose.core import explain_subject_raf, score_subjects
from risk_compose.registry import DEFAULT_MODEL_VERSION
from risk_compose.types import (
  SubjectExplainResult,
  ScoringOptions,
  ScoringRequest,
  ScoringResult,
  TableArtifact,
  ValidationIssue,
)
from risk_compose.validation import build_request_from_rows

SessionKind = Literal["score", "explain", "bundle_score", "bundle_explain"]

MODEL_VERSIONS = (
  "cms_hcc_v22_2026",
  "cms_hcc_v28_2026",
  "esrd_v21_2026",
  "esrd_v24_2026",
  "rxhcc_v8_t_2026",
  "rxhcc_v8_x_2026",
)

ARTIFACT_LABELS = {
  "subject_summary": "Summary",
  "subject_scores": "Scores",
  "subject_predictors": "Predictors",
  "diagnosis_mappings": "Mappings",
  "score_contributions": "Contributions",
  "validation_issues": "Issues",
  "hierarchy_effects": "Hierarchy",
  "interaction_details": "Interactions",
  "raf_totals": "RAF Totals",
}

SCORE_ARTIFACT_KEYS = (
  "subject_scores",
  "subject_predictors",
  "diagnosis_mappings",
  "score_contributions",
  "validation_issues",
)

EXPLAIN_ARTIFACT_KEYS = (
  "subject_summary",
  "subject_scores",
  "subject_predictors",
  "diagnosis_mappings",
  "hierarchy_effects",
  "interaction_details",
  "score_contributions",
  "raf_totals",
  "validation_issues",
)

ALL_ARTIFACT_KEYS = tuple(ARTIFACT_LABELS)
DEFAULT_PAGE_SIZE = 25
MAX_PREVIEW_COLUMNS = 8
MAX_CELL_WIDTH = 24


@dataclass(frozen=True, slots=True)
class ExplainInputSession:
  """Loaded explicit-file explain input before one subject is selected."""

  request: ScoringRequest
  source_paths: dict[str, Path]
  subject_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BundleLoadResult:
  """Loaded exported-bundle metadata plus tabular artifacts."""

  bundle_kind: Literal["score", "explain"]
  bundle_dir: Path
  artifacts: dict[str, TableArtifact]


@dataclass(frozen=True, slots=True)
class RunSummary:
  """High-level counts rendered by the review surfaces."""

  model_version: str
  subject_count: int
  diagnosis_count: int
  issue_error_count: int
  issue_warning_count: int
  issue_info_count: int
  artifact_row_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class ReviewSession:
  """One in-memory review session rendered by the frontends."""

  kind: SessionKind
  title: str
  source_paths: dict[str, Path]
  export_kind: Literal["score", "explain"] | None
  artifacts: dict[str, TableArtifact]
  summary: RunSummary
  subject_ids: tuple[str, ...]
  selected_subject_id: str | None


@dataclass(frozen=True, slots=True)
class ArtifactView:
  """Filtered and paginated view of one artifact."""

  artifact_key: str
  artifact_label: str
  columns: tuple[str, ...]
  total_row_count: int
  filtered_row_count: int
  page: int
  page_count: int
  page_size: int
  start_index: int
  page_rows: tuple[ArtifactRow, ...]
  selected_subject_id: str | None
  search_query: str | None


def build_review_options(
  *,
  model_version: str = DEFAULT_MODEL_VERSION,
  strict_validation: bool = False,
  disable_mce_edits: bool = False,
) -> ScoringOptions:
  """Build shared scoring options for the review surfaces."""
  return ScoringOptions(
    model_version=model_version,
    apply_mce_edits=not disable_mce_edits,
    strict_validation=strict_validation,
  )


def load_score_session(
  subjects_path: Path,
  diagnoses_path: Path,
  options: ScoringOptions,
) -> ReviewSession:
  """Load explicit files, run scoring, and build a review session."""
  request = _load_scoring_request(subjects_path, diagnoses_path, options)
  result = score_subjects(request)
  return build_score_session(
    result,
    source_paths={
      "subjects": subjects_path,
      "diagnoses": diagnoses_path,
    },
  )


def load_explain_input_session(
  subjects_path: Path,
  diagnoses_path: Path,
  options: ScoringOptions,
) -> ExplainInputSession:
  """Load explicit files for explain review before selecting one subject."""
  request = _load_scoring_request(subjects_path, diagnoses_path, options)
  subject_ids = tuple(
    subject.subject_id
    for subject in request.subjects
  )
  return ExplainInputSession(
    request=request,
    source_paths={
      "subjects": subjects_path,
      "diagnoses": diagnoses_path,
    },
    subject_ids=subject_ids,
  )


def run_explain_session(
  explain_input: ExplainInputSession,
  subject_id: str,
) -> ReviewSession:
  """Run explainability review for one selected subject."""
  matching_subjects = [
    subject
    for subject in explain_input.request.subjects
    if subject.subject_id == subject_id
  ]
  if len(matching_subjects) != 1:
    raise ValueError("Explain workflow requires exactly one matching subject record.")
  matching_diagnoses = [
    diagnosis
    for diagnosis in explain_input.request.diagnoses
    if diagnosis.subject_id == subject_id
  ]
  result = explain_subject_raf(
    matching_subjects[0],
    matching_diagnoses,
    options=explain_input.request.options,
  )
  return build_explain_session(result, source_paths=explain_input.source_paths)


def load_bundle_session(bundle_dir: Path) -> ReviewSession:
  """Open one previously exported bundle as a review session."""
  bundle = load_bundle_directory(bundle_dir)
  return build_bundle_session(
    bundle_kind=bundle.bundle_kind,
    bundle_dir=bundle.bundle_dir,
    artifacts=bundle.artifacts,
  )


def load_bundle_directory(bundle_dir: Path) -> BundleLoadResult:
  """Load one previously exported score or explain bundle directory."""
  resolved_dir = bundle_dir.resolve()
  if not resolved_dir.exists():
    raise ValueError(f"Bundle directory does not exist: {resolved_dir}")
  if not resolved_dir.is_dir():
    raise ValueError(f"Bundle path is not a directory: {resolved_dir}")

  available_filenames = {
    path.name
    for path in resolved_dir.iterdir()
    if path.is_file()
  }
  explain_required = set(EXPLAIN_EXPORT_FILENAMES)
  score_required = set(SCORE_EXPORT_FILENAMES)

  if explain_required.issubset(available_filenames):
    return BundleLoadResult(
      bundle_kind="explain",
      bundle_dir=resolved_dir,
      artifacts=_load_artifacts(resolved_dir, EXPLAIN_EXPORT_FILENAMES),
    )
  if score_required.issubset(available_filenames):
    return BundleLoadResult(
      bundle_kind="score",
      bundle_dir=resolved_dir,
      artifacts=_load_artifacts(resolved_dir, SCORE_EXPORT_FILENAMES),
    )

  missing_score = sorted(score_required - available_filenames)
  missing_explain = sorted(explain_required - available_filenames)
  raise ValueError(
    "Bundle directory is missing the required exported files. "
    f"Missing score files: {missing_score or 'none'}. "
    f"Missing explain files: {missing_explain or 'none'}."
  )


def export_review_session(session: ReviewSession, export_dir: Path) -> None:
  """Write the current in-memory review session to a directory."""
  export_dir.mkdir(parents=True, exist_ok=True)
  for artifact_name, artifact in session.artifacts.items():
    write_artifact_csv(export_dir / f"{artifact_name}.csv", artifact)


def available_artifact_keys(session: ReviewSession) -> tuple[str, ...]:
  """Return the visible artifact order for the current session."""
  if session.export_kind == "explain":
    return EXPLAIN_ARTIFACT_KEYS
  return SCORE_ARTIFACT_KEYS


def build_artifact_view(
  session: ReviewSession,
  artifact_key: str,
  *,
  subject_id: str | None = None,
  search_query: str | None = None,
  page: int = 1,
  page_size: int = DEFAULT_PAGE_SIZE,
) -> ArtifactView:
  """Build a filtered and paginated view for one session artifact."""
  if artifact_key not in session.artifacts:
    raise ValueError(f"Unknown artifact `{artifact_key}` for the current session.")
  artifact = session.artifacts[artifact_key]
  subject_filtered = filter_artifact_by_subject(artifact, subject_id)
  normalized_search = (search_query or "").strip()
  searched_rows = tuple(
    row
    for row in subject_filtered.rows
    if _row_matches_search(row, normalized_search)
  )
  filtered_row_count = len(searched_rows)
  page_count = max(1, ceil(filtered_row_count / page_size)) if filtered_row_count else 1
  normalized_page = min(max(page, 1), page_count)
  start_index = (normalized_page - 1) * page_size
  end_index = start_index + page_size
  return ArtifactView(
    artifact_key=artifact_key,
    artifact_label=ARTIFACT_LABELS.get(artifact_key, artifact_key),
    columns=artifact.columns,
    total_row_count=len(artifact.rows),
    filtered_row_count=filtered_row_count,
    page=normalized_page,
    page_count=page_count,
    page_size=page_size,
    start_index=start_index,
    page_rows=searched_rows[start_index:end_index],
    selected_subject_id=subject_id,
    search_query=normalized_search or None,
  )


def format_session_summary(session: ReviewSession) -> str:
  """Render one review session summary as plain text."""
  source_lines = [
    f"{name}: {path}"
    for name, path in session.source_paths.items()
  ]
  artifact_lines = [
    f"{artifact_name}: {row_count} row(s)"
    for artifact_name, row_count in session.summary.artifact_row_counts.items()
  ]
  sections = [
    session.title,
    "",
    f"model_version: {session.summary.model_version}",
    f"subjects: {session.summary.subject_count}",
    f"diagnosis rows: {session.summary.diagnosis_count}",
    (
      "issues: "
      f"{session.summary.issue_error_count} error, "
      f"{session.summary.issue_warning_count} warning, "
      f"{session.summary.issue_info_count} info"
    ),
    "",
    "Sources:",
    *source_lines,
    "",
    "Artifacts:",
    *artifact_lines,
  ]
  return "\n".join(sections)


def format_artifact_preview(view: ArtifactView) -> str:
  """Render the current artifact page as a compact command-line table."""
  lines = [
    f"{view.artifact_label} [{view.artifact_key}]",
    (
      f"rows: {view.filtered_row_count}/{view.total_row_count} "
      f"| page {view.page}/{view.page_count} "
      f"| subject: {view.selected_subject_id or 'all'} "
      f"| search: {view.search_query or 'none'}"
    ),
    "",
  ]
  if not view.columns:
    lines.append("This artifact has no columns.")
    return "\n".join(lines)
  if not view.page_rows:
    lines.append("No rows matched the current filters.")
    return "\n".join(lines)

  preview_columns = view.columns[:MAX_PREVIEW_COLUMNS]
  hidden_columns = len(view.columns) - len(preview_columns)
  if hidden_columns > 0:
    lines.append(
      f"Previewing {len(preview_columns)} of {len(view.columns)} columns. "
      "Use `row <n>` for full row detail."
    )
    lines.append("")

  widths = {
    column: min(
      MAX_CELL_WIDTH,
      max(
        len(column),
        *(len(_display_value(row.get(column))) for row in view.page_rows),
      ),
    )
    for column in preview_columns
  }
  header = " # | " + " | ".join(column.ljust(widths[column]) for column in preview_columns)
  separator = "---+-" + "-+-".join("-" * widths[column] for column in preview_columns)
  lines.extend((header, separator))
  for row_number, row in enumerate(view.page_rows, start=view.start_index + 1):
    row_cells = [
      _truncate_cell(_display_value(row.get(column)), widths[column]).ljust(widths[column])
      for column in preview_columns
    ]
    lines.append(f"{row_number:>2} | " + " | ".join(row_cells))
  return "\n".join(lines)


def format_row_detail(view: ArtifactView, row_number: int) -> str:
  """Render one row from the current artifact page as full JSON detail."""
  page_offset = row_number - 1
  if page_offset < 0 or page_offset >= len(view.page_rows):
    raise ValueError(f"Row {row_number} is out of range for the current page.")
  absolute_row_number = view.start_index + row_number
  row = view.page_rows[page_offset]
  return (
    f"Row {absolute_row_number} [{view.artifact_key}]\n\n"
    f"{json.dumps(row, indent=2, default=str, sort_keys=True)}"
  )


def build_score_session(
  result: ScoringResult,
  *,
  source_paths: dict[str, Path],
) -> ReviewSession:
  """Build a review session from the explicit-file score workflow."""
  artifacts = {
    "subject_predictors": result.predictors.subject_predictors,
    "subject_scores": result.scores.subject_scores,
    "diagnosis_mappings": result.predictors.diagnosis_mappings,
    "score_contributions": result.scores.score_contributions,
    "validation_issues": _validation_issues_to_artifact(result.validation_issues),
  }
  return _build_session(
    kind="score",
    title=f"Score Review: {source_paths['subjects'].name}",
    source_paths=source_paths,
    export_kind="score",
    artifacts=artifacts,
    model_version=result.model_spec.version_id,
  )


def build_explain_session(
  result: SubjectExplainResult,
  *,
  source_paths: dict[str, Path],
) -> ReviewSession:
  """Build a review session from the explicit-file explain workflow."""
  artifacts = {
    "subject_summary": result.subject_summary,
    "subject_predictors": result.subject_predictors,
    "diagnosis_mappings": result.diagnosis_mappings,
    "hierarchy_effects": result.hierarchy_effects,
    "interaction_details": result.interaction_details,
    "score_contributions": result.score_contributions,
    "subject_scores": result.subject_scores,
    "raf_totals": result.raf_totals,
    "validation_issues": _validation_issues_to_artifact(result.validation_issues),
  }
  return _build_session(
    kind="explain",
    title=f"Subject Explain: {source_paths['subjects'].name}",
    source_paths=source_paths,
    export_kind="explain",
    artifacts=artifacts,
    model_version=result.model_spec.version_id,
  )


def build_bundle_session(
  *,
  bundle_kind: Literal["score", "explain"],
  bundle_dir: Path,
  artifacts: dict[str, TableArtifact],
) -> ReviewSession:
  """Build a review session from a previously exported bundle directory."""
  return _build_session(
    kind="bundle_score" if bundle_kind == "score" else "bundle_explain",
    title=f"Opened Bundle: {bundle_dir.name}",
    source_paths={"bundle_dir": bundle_dir},
    export_kind=bundle_kind,
    artifacts=artifacts,
    model_version=_model_version_from_artifacts(artifacts),
  )


def filter_artifact_by_subject(
  artifact: TableArtifact,
  subject_id: str | None,
) -> TableArtifact:
  """Return the filtered artifact when the artifact carries subject IDs."""
  if subject_id is None or "subject_id" not in artifact.columns:
    return artifact
  return TableArtifact(
    name=artifact.name,
    columns=artifact.columns,
    rows=tuple(
      row
      for row in artifact.rows
      if str(row.get("subject_id", "")) == subject_id
    ),
  )


def artifact_has_subject_id(artifact: TableArtifact) -> bool:
  """Return whether the artifact is subject-addressable in the UI."""
  return "subject_id" in artifact.columns


def _load_scoring_request(
  subjects_path: Path,
  diagnoses_path: Path,
  options: ScoringOptions,
) -> ScoringRequest:
  return build_request_from_rows(
    read_csv_rows(subjects_path),
    read_csv_rows(diagnoses_path),
    options=options,
  )


def _load_artifacts(
  bundle_dir: Path,
  filenames: tuple[str, ...],
) -> dict[str, TableArtifact]:
  artifacts: dict[str, TableArtifact] = {}
  for filename in filenames:
    artifact_name = filename.removesuffix(".csv")
    artifacts[artifact_name] = read_table_artifact_csv(
      bundle_dir / filename,
      name=artifact_name,
    )
  return artifacts


def _build_session(
  *,
  kind: SessionKind,
  title: str,
  source_paths: dict[str, Path],
  export_kind: Literal["score", "explain"] | None,
  artifacts: dict[str, TableArtifact],
  model_version: str,
) -> ReviewSession:
  subject_ids = _extract_subject_ids(artifacts)
  selected_subject_id = subject_ids[0] if subject_ids else None
  return ReviewSession(
    kind=kind,
    title=title,
    source_paths=source_paths,
    export_kind=export_kind,
    artifacts=artifacts,
    summary=_build_summary(artifacts, model_version),
    subject_ids=subject_ids,
    selected_subject_id=selected_subject_id,
  )


def _build_summary(
  artifacts: dict[str, TableArtifact],
  model_version: str,
) -> RunSummary:
  issue_rows = artifacts.get("validation_issues", TableArtifact.empty("validation_issues", ())).rows
  error_count = sum(1 for row in issue_rows if str(row.get("severity", "")) == "error")
  warning_count = sum(1 for row in issue_rows if str(row.get("severity", "")) == "warning")
  info_count = sum(1 for row in issue_rows if str(row.get("severity", "")) == "info")
  subject_count = len(_extract_subject_ids(artifacts))
  diagnosis_count = len(artifacts.get("diagnosis_mappings", TableArtifact.empty("diagnosis_mappings", ())).rows)
  return RunSummary(
    model_version=model_version,
    subject_count=subject_count,
    diagnosis_count=diagnosis_count,
    issue_error_count=error_count,
    issue_warning_count=warning_count,
    issue_info_count=info_count,
    artifact_row_counts={name: len(artifact.rows) for name, artifact in artifacts.items()},
  )


def _extract_subject_ids(artifacts: dict[str, TableArtifact]) -> tuple[str, ...]:
  subject_ids: set[str] = set()
  for artifact_name in (
    "subject_summary",
    "subject_scores",
    "subject_predictors",
    "raf_totals",
    "diagnosis_mappings",
    "score_contributions",
    "validation_issues",
  ):
    artifact = artifacts.get(artifact_name)
    if artifact is None or "subject_id" not in artifact.columns:
      continue
    subject_ids.update(
      str(row.get("subject_id", "")).strip()
      for row in artifact.rows
      if str(row.get("subject_id", "")).strip()
    )
  return tuple(sorted(subject_ids))


def _model_version_from_artifacts(artifacts: dict[str, TableArtifact]) -> str:
  for artifact_name in ("subject_scores", "subject_predictors", "subject_summary"):
    artifact = artifacts.get(artifact_name)
    if artifact is None:
      continue
    for row in artifact.rows:
      value = str(row.get("model_version", "")).strip()
      if value:
        return value
  return "unknown"


def _display_value(value: object) -> str:
  if value is None:
    return ""
  return str(value)


def _truncate_cell(value: str, width: int) -> str:
  if len(value) <= width:
    return value
  if width <= 1:
    return value[:width]
  return f"{value[: width - 1]}…"


def _row_matches_search(row: ArtifactRowMapping, search_query: str) -> bool:
  if not search_query:
    return True
  search_lower = search_query.lower()
  return any(search_lower in _display_value(value).lower() for value in row.values())


def _validation_issues_to_artifact(validation_issues: tuple[ValidationIssue, ...]) -> TableArtifact:
  return TableArtifact(
    name="validation_issues",
    columns=("severity", "code", "message", "subject_id", "field_name"),
    rows=tuple(
      {
        "severity": issue.severity,
        "code": issue.code,
        "message": issue.message,
        "subject_id": issue.subject_id,
        "field_name": issue.field_name,
      }
      for issue in validation_issues
    ),
  )
