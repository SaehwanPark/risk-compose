"""CLI entry points for batch workflows plus review frontends."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TypeAlias, cast

from pydantic import ValidationError as PydanticValidationError

from risk_compose._schemas import (
  DatabaseSourceEntrySchema,
  FlatFileSourceEntrySchema,
  parse_optional_text,
)
from risk_compose._typing import JsonObject, TuiRunner
from risk_compose._artifact_io import (
  export_explain_bundle,
  export_prepare_bundle,
  export_score_bundle,
  export_score_source_bundle,
  read_csv_rows,
)
from risk_compose.core import explain_subject_raf, prepare_scoring_inputs, score_subjects
from risk_compose.types import (
  DatabaseTableSpec,
  DatabaseSourceSpec,
  FlatFileTableSpec,
  FlatFileSourceSpec,
  ScoringOptions,
  SourcePreparationRequest,
  ValidationIssue,
)
from risk_compose.validation import ValidationError, build_request_from_rows, enforce_strict_validation

IssueTuple: TypeAlias = tuple[ValidationIssue, ...]


def build_parser() -> argparse.ArgumentParser:
  """Build the public batch-scoring CLI parser."""
  parser = argparse.ArgumentParser(
    prog="risk-compose",
    description="Run the typed RAF batch scoring workflow.",
  )
  subparsers = parser.add_subparsers(dest="command", required=True)

  score_parser = subparsers.add_parser(
    "score",
    help="Score subjects from explicit input files.",
  )
  _add_explicit_input_arguments(score_parser)
  score_parser.set_defaults(handler=_run_score_command)

  prepare_source_parser = subparsers.add_parser(
    "prepare-source",
    help="Prepare canonical scoring inputs from a declared source.",
  )
  _add_source_workflow_arguments(prepare_source_parser)
  prepare_source_parser.set_defaults(handler=_run_prepare_source_command)

  score_source_parser = subparsers.add_parser(
    "score-source",
    help="Prepare and score subjects from a declared source.",
  )
  _add_source_workflow_arguments(score_source_parser)
  score_source_parser.set_defaults(handler=_run_score_source_command)

  explain_parser = subparsers.add_parser(
    "explain-subject",
    help="Explain RAF results for a single subject.",
  )
  _add_explicit_input_arguments(explain_parser)
  explain_parser.add_argument(
    "--subject-id",
    required=True,
    help="Subject identifier to explain.",
  )
  explain_parser.set_defaults(handler=_run_explain_subject_command)

  tui_parser = subparsers.add_parser(
    "tui",
    help="Launch the command-first review TUI.",
  )
  tui_parser.add_argument(
    "--bundle-dir",
    help="Optional previously exported score or explain bundle to open at startup.",
  )
  tui_parser.set_defaults(handler=_run_tui_command)

  gui_parser = subparsers.add_parser(
    "gui",
    help="Launch the Streamlit review GUI.",
  )
  gui_parser.add_argument(
    "--bundle-dir",
    help="Optional previously exported score or explain bundle to open at startup.",
  )
  gui_parser.set_defaults(handler=_run_gui_command)
  return parser


def main(argv: Sequence[str] | None = None) -> int:
  """Parse CLI args and run the requested scoring workflow."""
  parser = build_parser()
  args = parser.parse_args(list(argv) if argv is not None else None)
  handler = getattr(args, "handler", None)
  if handler is None:
    parser.print_help()
    return 0
  try:
    return int(handler(args))
  except ValidationError as exc:
    print(str(exc), file=sys.stderr)
    return 1


def _run_score_command(args: argparse.Namespace) -> int:
  """Run the explicit batch-scoring workflow for the score subcommand."""
  output_error_code = _validate_csv_only_io(args)
  if output_error_code:
    return output_error_code

  subject_rows = read_csv_rows(Path(args.subjects))
  diagnosis_rows = read_csv_rows(Path(args.diagnoses))
  request = build_request_from_rows(
    subject_rows,
    diagnosis_rows,
    options=_options_from_args(args),
  )
  result = score_subjects(request)
  export_score_bundle(Path(args.output_dir), result)
  return 0


def _run_prepare_source_command(args: argparse.Namespace) -> int:
  """Prepare canonical scoring inputs from a declared source."""
  output_error_code = _validate_output_format(args)
  if output_error_code:
    return output_error_code

  source_request = _source_request_from_manifest(args)
  prepared_inputs = prepare_scoring_inputs(source_request)
  _enforce_supported_source_model(prepared_inputs.preparation_issues)
  export_prepare_bundle(Path(args.output_dir), prepared_inputs)
  return 0


def _run_score_source_command(args: argparse.Namespace) -> int:
  """Prepare canonical inputs from a source and run subject scoring."""
  output_error_code = _validate_output_format(args)
  if output_error_code:
    return output_error_code

  source_request = _source_request_from_manifest(args)
  prepared_inputs = prepare_scoring_inputs(source_request)
  _enforce_supported_source_model(prepared_inputs.preparation_issues)
  result = score_subjects(prepared_inputs.scoring_request)
  merged_validation_issues = prepared_inputs.preparation_issues + result.validation_issues
  export_score_source_bundle(
    Path(args.output_dir),
    prepared_inputs,
    result,
    validation_issues=merged_validation_issues,
  )
  return 0


def _run_explain_subject_command(args: argparse.Namespace) -> int:
  """Explain RAF results for a single subject."""
  output_error_code = _validate_csv_only_io(args)
  if output_error_code:
    return output_error_code

  subject_rows = read_csv_rows(Path(args.subjects))
  diagnosis_rows = read_csv_rows(Path(args.diagnoses))
  request = build_request_from_rows(
    subject_rows,
    diagnosis_rows,
    options=_options_from_args(args),
  )
  matching_subjects = [
    subject
    for subject in request.subjects
    if subject.subject_id == args.subject_id
  ]
  if len(matching_subjects) != 1:
    print(
      "Explain-subject requires exactly one matching subject record.",
      file=sys.stderr,
    )
    return 1

  matching_diagnoses = [
    diagnosis
    for diagnosis in request.diagnoses
    if diagnosis.subject_id == args.subject_id
  ]
  explain_result = explain_subject_raf(
    matching_subjects[0],
    matching_diagnoses,
    options=request.options,
  )
  export_explain_bundle(Path(args.output_dir), explain_result)
  return 0


def _run_tui_command(args: argparse.Namespace) -> int:
  """Launch the interactive TUI if the optional dependency is installed."""
  bundle_dir = Path(args.bundle_dir).resolve() if args.bundle_dir else None
  try:
    run_tui = _import_tui_runner()
  except ModuleNotFoundError as exc:
    if not _is_missing_optional_surface(
      exc,
      dependency_root="textual",
      module_prefix="risk_compose.tui",
    ):
      raise
    print(
      (
        "The `tui` command requires the bundled Textual frontend. "
        "For repo work use `uv sync --group dev`. "
        "For package installs, install or reinstall `risk-compose` with its "
        "default dependencies."
      ),
      file=sys.stderr,
    )
    return 1
  return int(run_tui(bundle_dir=bundle_dir))


def _run_gui_command(args: argparse.Namespace) -> int:
  """Launch the interactive GUI if the optional dependency is installed."""
  bundle_dir = Path(args.bundle_dir).resolve() if args.bundle_dir else None
  try:
    run_gui = _import_gui_runner()
  except ModuleNotFoundError as exc:
    if not _is_missing_optional_surface(
      exc,
      dependency_root="streamlit",
      module_prefix="risk_compose.gui",
    ):
      raise
    print(
      (
        "The `gui` command requires the bundled Streamlit frontend. "
        "For repo work use `uv sync --group dev`. "
        "For package installs, install or reinstall `risk-compose` with its "
        "default dependencies."
      ),
      file=sys.stderr,
    )
    return 1
  return int(run_gui(bundle_dir=bundle_dir))


def _import_tui_runner() -> TuiRunner:
  """Import the optional TUI runner lazily so batch CLI stays lightweight."""
  from risk_compose.tui.app import run_tui

  return run_tui


def _import_gui_runner() -> TuiRunner:
  """Import the optional GUI runner lazily so batch CLI stays lightweight."""
  import streamlit  # noqa: F401
  from risk_compose.gui.runner import run_gui

  return run_gui


def _is_missing_optional_surface(
  exc: ModuleNotFoundError,
  *,
  dependency_root: str,
  module_prefix: str,
) -> bool:
  """Return whether a missing import belongs to an optional split package."""
  missing_name = exc.name or ""
  return (
    missing_name == dependency_root
    or missing_name == module_prefix
    or missing_name.startswith(f"{module_prefix}.")
  )


def _options_from_args(args: argparse.Namespace) -> ScoringOptions:
  """Build scoring options from parsed CLI arguments."""
  return ScoringOptions(
    model_version=args.model_version,
    apply_mce_edits=not args.no_mce_edits,
    strict_validation=args.strict,
  )


def _validate_csv_only_io(args: argparse.Namespace) -> int:
  """Validate the currently supported CLI input and output formats."""
  if args.input_format != "csv" or args.output_format != "csv":
    print(
      "Only CSV input and output are implemented in the first skeleton.",
      file=sys.stderr,
    )
    return 2
  return 0


def _enforce_supported_source_model(validation_issues: tuple[ValidationIssue, ...]) -> None:
  """Raise when source workflows are asked to run unsupported model families."""
  enforce_strict_validation(
    tuple(
      issue
      for issue in validation_issues
      if issue.code in {"unsupported_source_model_version", "unsupported_source_model_family"}
    ),
  )


def _add_explicit_input_arguments(parser: argparse.ArgumentParser) -> None:
  """Add explicit subject and diagnosis input arguments."""
  parser.add_argument("--subjects", required=True, help="Path to the subject input file.")
  parser.add_argument("--diagnoses", required=True, help="Path to the diagnosis input file.")
  parser.add_argument("--output-dir", required=True, help="Directory for artifact outputs.")
  parser.add_argument(
    "--model-version",
    default="cms_hcc_v28_2026",
    help="Registered model version to run.",
  )
  parser.add_argument(
    "--input-format",
    choices=("csv", "parquet"),
    default="csv",
    help="Input file format. Only CSV is implemented in this milestone.",
  )
  parser.add_argument(
    "--output-format",
    choices=("csv", "parquet"),
    default="csv",
    help="Output file format. Only CSV is implemented in this milestone.",
  )
  parser.add_argument(
    "--strict",
    action="store_true",
    help="Treat validation errors as blocking failures.",
  )
  parser.add_argument(
    "--no-mce-edits",
    action="store_true",
    help="Disable MCE age-edit handling during diagnosis mapping.",
  )


def _add_source_workflow_arguments(parser: argparse.ArgumentParser) -> None:
  """Add source-driven preparation arguments."""
  parser.add_argument(
    "--source-manifest",
    required=True,
    help="Path to a JSON source manifest that declares logical source roles and mappings.",
  )
  parser.add_argument("--output-dir", required=True, help="Directory for artifact outputs.")
  parser.add_argument(
    "--model-version",
    default="cms_hcc_v28_2026",
    help="Registered model version to run.",
  )
  parser.add_argument(
    "--output-format",
    choices=("csv", "parquet"),
    default="csv",
    help="Output file format. Only CSV is implemented in the first skeleton.",
  )
  parser.add_argument(
    "--strict",
    action="store_true",
    help="Treat validation errors as blocking failures.",
  )
  parser.add_argument(
    "--no-mce-edits",
    action="store_true",
    help="Disable MCE age-edit handling during diagnosis mapping.",
  )


def _validate_output_format(args: argparse.Namespace) -> int:
  """Validate the currently supported CLI output format."""
  if args.output_format != "csv":
    print(
      "Only CSV output is implemented in the first skeleton.",
      file=sys.stderr,
    )
    return 2
  return 0


def _source_request_from_manifest(args: argparse.Namespace) -> SourcePreparationRequest:
  """Build a source-preparation request from a manifest file."""
  manifest_path = Path(args.source_manifest)
  manifest_data, manifest_issues = _read_manifest_data(manifest_path)
  _raise_for_issues(manifest_issues)
  assert manifest_data is not None

  source_spec, source_spec_issues = _source_spec_from_manifest(manifest_data, manifest_path)
  _raise_for_issues(source_spec_issues)
  assert source_spec is not None
  return SourcePreparationRequest(
    source_spec=source_spec,
    options=_options_from_args(args),
  )


def _read_manifest_data(manifest_path: Path) -> tuple[JsonObject | None, IssueTuple]:
  """Load manifest JSON and coerce it to the expected top-level object."""
  try:
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
  except FileNotFoundError:
    return None, _single_issue(
      code="missing_source_manifest",
      message=f"Source manifest does not exist: {manifest_path}",
    )
  except json.JSONDecodeError as exc:
    return None, _single_issue(
      code="invalid_source_manifest",
      message=f"Source manifest is not valid JSON: {exc}",
    )

  if not isinstance(manifest_data, dict):
    return None, _single_issue(
      code="invalid_source_manifest",
      message="Source manifest JSON must be an object at the top level.",
    )

  return manifest_data, ()


def _source_spec_from_manifest(
  manifest_data: JsonObject,
  manifest_path: Path,
) -> tuple[FlatFileSourceSpec | DatabaseSourceSpec | None, IssueTuple]:
  """Build a typed source spec from manifest data."""
  source_profile = manifest_data.get("source_profile")
  source_kind = manifest_data.get("source_kind", "flat-file")
  raw_sources = manifest_data.get("sources")
  if not isinstance(source_profile, str) or not source_profile:
    return None, _single_issue(
      code="missing_source_profile",
      message="Source manifests must declare a non-empty source_profile.",
    )
  if not isinstance(raw_sources, dict) or not raw_sources:
    return None, _single_issue(
      code="missing_manifest_sources",
      message="Source manifests must declare a non-empty 'sources' mapping.",
    )

  if source_kind == "flat-file":
    flat_file_sources: dict[str, FlatFileTableSpec] = {}
    for role, raw_spec in raw_sources.items():
      if not isinstance(raw_spec, dict):
        return None, _invalid_source_entry_issue(str(role))
      source_entry, entry_issues = _flat_file_entry_from_manifest(str(role), raw_spec)
      if entry_issues:
        return None, entry_issues
      assert source_entry is not None
      source_path = Path(source_entry.path)
      if not source_path.is_absolute():
        source_path = (manifest_path.parent / source_path).resolve()
      flat_file_sources[str(role)] = FlatFileTableSpec(
        path=source_path,
        columns=source_entry.columns,
        filter=source_entry.filter,
      )
    return (
      FlatFileSourceSpec(
        source_profile=source_profile,
        sources=flat_file_sources,
        file_format=parse_optional_text(manifest_data.get("file_format")) or "csv",
      ),
      (),
    )

  if source_kind == "database":
    database_sources: dict[str, DatabaseTableSpec] = {}
    for role, raw_spec in raw_sources.items():
      if not isinstance(raw_spec, dict):
        return None, _invalid_source_entry_issue(str(role))
      database_entry, entry_issues = _database_entry_from_manifest(str(role), raw_spec)
      if entry_issues:
        return None, entry_issues
      assert database_entry is not None
      database_sources[str(role)] = DatabaseTableSpec(
        locator=database_entry.locator,
        schema_name=database_entry.schema_name,
        columns=database_entry.columns,
        filter=database_entry.filter,
      )
    return (
      DatabaseSourceSpec(
        source_profile=source_profile,
        sources=database_sources,
      ),
      (),
    )

  return None, _single_issue(
    code="invalid_source_kind",
    message="Source manifests must declare source_kind as 'flat-file' or 'database'.",
  )


def _flat_file_entry_from_manifest(
  role: str,
  raw_spec: JsonObject,
) -> tuple[FlatFileSourceEntrySchema | None, IssueTuple]:
  """Validate and normalize one flat-file manifest entry."""
  try:
    return FlatFileSourceEntrySchema.model_validate(raw_spec), ()
  except PydanticValidationError as exc:
    error_fields = _error_fields(exc)
    if "path" in error_fields:
      return None, _single_issue(
        code="missing_source_path",
        message=f"Flat-file source role '{role}' must declare a non-empty path.",
      )
    if "columns" in error_fields:
      return None, _single_issue(
        code="invalid_mapping_object",
        message="Manifest mapping entries must be JSON objects.",
      )
    return None, _invalid_source_entry_issue(role)


def _database_entry_from_manifest(
  role: str,
  raw_spec: JsonObject,
) -> tuple[DatabaseSourceEntrySchema | None, IssueTuple]:
  """Validate and normalize one database manifest entry."""
  try:
    return DatabaseSourceEntrySchema.model_validate(raw_spec), ()
  except PydanticValidationError as exc:
    error_fields = _error_fields(exc)
    if "locator" in error_fields:
      return None, _single_issue(
        code="missing_source_locator",
        message=f"Database source role '{role}' must declare a non-empty locator.",
      )
    if "columns" in error_fields:
      return None, _single_issue(
        code="invalid_mapping_object",
        message="Manifest mapping entries must be JSON objects.",
      )
    return None, _invalid_source_entry_issue(role)


def _raise_for_issues(issues: IssueTuple) -> None:
  """Raise a validation error when any manifest issue is present."""
  if issues:
    raise ValidationError(issues)


def _single_issue(*, code: str, message: str) -> IssueTuple:
  """Build one blocking validation issue."""
  return (
    ValidationIssue(
      severity="error",
      code=code,
      message=message,
    ),
  )


def _invalid_source_entry_issue(role: str) -> IssueTuple:
  """Build the standard invalid source-entry issue for one role."""
  return _single_issue(
    code="invalid_source_entry",
    message=f"Source role '{role}' must map to an object in the manifest.",
  )


def _error_fields(exc: PydanticValidationError) -> set[str]:
  """Return top-level fields mentioned in a Pydantic validation error."""
  fields: set[str] = set()
  for error in exc.errors():
    location = error.get("loc", ())
    if location:
      fields.add(str(location[0]))
  return fields
