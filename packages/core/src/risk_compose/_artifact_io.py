"""Shared CSV and artifact export helpers for CLI and TUI surfaces."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from risk_compose._typing import ArtifactValue
from risk_compose.types import (
  SubjectExplainResult,
  PreparedScoringInputs,
  ScoringResult,
  TableArtifact,
  ValidationIssue,
)

SCORE_EXPORT_FILENAMES = (
  "subject_predictors.csv",
  "subject_scores.csv",
  "diagnosis_mappings.csv",
  "score_contributions.csv",
  "validation_issues.csv",
)
EXPLAIN_EXPORT_FILENAMES = (
  "subject_summary.csv",
  "subject_predictors.csv",
  "diagnosis_mappings.csv",
  "hierarchy_effects.csv",
  "interaction_details.csv",
  "score_contributions.csv",
  "subject_scores.csv",
  "raf_totals.csv",
  "validation_issues.csv",
)
PREPARE_EXPORT_FILENAMES = (
  "prepared_subjects.csv",
  "prepared_diagnoses.csv",
  "rejected_diagnosis_candidates.csv",
  "source_lineage.csv",
  "preparation_issues.csv",
)


def read_csv_rows(path: Path) -> tuple[dict[str, str], ...]:
  """Read a CSV file into row dictionaries."""
  with path.open("r", encoding="utf-8-sig", newline="") as handle:
    return tuple(csv.DictReader(handle))


def read_table_artifact_csv(path: Path, *, name: str | None = None) -> TableArtifact:
  """Read one CSV artifact into the shared row-and-column container."""
  with path.open("r", encoding="utf-8-sig", newline="") as handle:
    reader = csv.DictReader(handle)
    columns = tuple(reader.fieldnames or ())
    rows = tuple(
      {
        column: row.get(column, "")
        for column in columns
      }
      for row in reader
    )
  return TableArtifact(
    name=name or path.stem,
    columns=columns,
    rows=rows,
  )


def write_artifact_csv(path: Path, artifact: TableArtifact) -> None:
  """Write a table artifact to CSV with deterministic column order."""
  with path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(artifact.columns))
    writer.writeheader()
    for row in artifact.rows:
      writer.writerow({column: _serialize_value(row.get(column)) for column in artifact.columns})


def write_validation_issues_csv(path: Path, validation_issues: tuple[ValidationIssue, ...]) -> None:
  """Write structured validation issues to CSV."""
  write_artifact_csv(path, validation_issues_to_artifact(validation_issues))


def validation_issues_to_artifact(validation_issues: tuple[ValidationIssue, ...]) -> TableArtifact:
  """Normalize structured validation issues into a tabular artifact."""
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


def export_score_bundle(output_dir: Path, result: ScoringResult) -> None:
  """Write the score workflow outputs to one directory."""
  output_dir.mkdir(parents=True, exist_ok=True)
  write_artifact_csv(output_dir / "subject_predictors.csv", result.predictors.subject_predictors)
  write_artifact_csv(output_dir / "subject_scores.csv", result.scores.subject_scores)
  write_artifact_csv(output_dir / "diagnosis_mappings.csv", result.predictors.diagnosis_mappings)
  write_artifact_csv(output_dir / "score_contributions.csv", result.scores.score_contributions)
  write_validation_issues_csv(output_dir / "validation_issues.csv", result.validation_issues)


def export_explain_bundle(output_dir: Path, result: SubjectExplainResult) -> None:
  """Write the subject explainability outputs to one directory."""
  output_dir.mkdir(parents=True, exist_ok=True)
  write_artifact_csv(output_dir / "subject_summary.csv", result.subject_summary)
  write_artifact_csv(output_dir / "subject_predictors.csv", result.subject_predictors)
  write_artifact_csv(output_dir / "diagnosis_mappings.csv", result.diagnosis_mappings)
  write_artifact_csv(output_dir / "hierarchy_effects.csv", result.hierarchy_effects)
  write_artifact_csv(output_dir / "interaction_details.csv", result.interaction_details)
  write_artifact_csv(output_dir / "score_contributions.csv", result.score_contributions)
  write_artifact_csv(output_dir / "subject_scores.csv", result.subject_scores)
  write_artifact_csv(output_dir / "raf_totals.csv", result.raf_totals)
  write_validation_issues_csv(output_dir / "validation_issues.csv", result.validation_issues)


def export_prepare_bundle(output_dir: Path, prepared_inputs: PreparedScoringInputs) -> None:
  """Write the preparation workflow outputs to one directory."""
  output_dir.mkdir(parents=True, exist_ok=True)
  write_artifact_csv(output_dir / "prepared_subjects.csv", prepared_inputs.prepared_subjects)
  write_artifact_csv(output_dir / "prepared_diagnoses.csv", prepared_inputs.prepared_diagnoses)
  write_artifact_csv(
    output_dir / "rejected_diagnosis_candidates.csv",
    prepared_inputs.rejected_diagnosis_candidates,
  )
  write_artifact_csv(output_dir / "source_lineage.csv", prepared_inputs.source_lineage)
  write_validation_issues_csv(output_dir / "preparation_issues.csv", prepared_inputs.preparation_issues)


def export_score_source_bundle(
  output_dir: Path,
  prepared_inputs: PreparedScoringInputs,
  result: ScoringResult,
  *,
  validation_issues: tuple[ValidationIssue, ...] | None = None,
) -> None:
  """Write the source-driven preparation plus score outputs to one directory."""
  export_prepare_bundle(output_dir, prepared_inputs)
  write_artifact_csv(output_dir / "subject_predictors.csv", result.predictors.subject_predictors)
  write_artifact_csv(output_dir / "subject_scores.csv", result.scores.subject_scores)
  write_artifact_csv(output_dir / "diagnosis_mappings.csv", result.predictors.diagnosis_mappings)
  write_artifact_csv(output_dir / "score_contributions.csv", result.scores.score_contributions)
  write_validation_issues_csv(
    output_dir / "validation_issues.csv",
    validation_issues or result.validation_issues,
  )


def _serialize_value(value: ArtifactValue) -> str:
  """Serialize artifact values to CSV-friendly strings."""
  if value is None:
    return ""
  if isinstance(value, date):
    return value.isoformat()
  return str(value)
