"""Command-first Textual TUI for score, explain, and bundle review."""

from __future__ import annotations

import argparse
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import Never

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Static

from risk_compose.review import (
  ArtifactView,
  DEFAULT_PAGE_SIZE,
  ExplainInputSession,
  ReviewSession,
  available_artifact_keys,
  build_artifact_view,
  build_review_options,
  format_artifact_preview,
  format_row_detail,
  format_session_summary,
  load_bundle_session,
  load_explain_input_session,
  load_score_session,
  run_explain_session,
)
from risk_compose.validation import DIAGNOSIS_COLUMN_ALIASES, SUBJECT_COLUMN_ALIASES

TITLE = "risk-compose tui"


class CommandUsageError(ValueError):
  """Raised when a typed command is syntactically invalid."""


class _CommandParser(argparse.ArgumentParser):
  """Argparse wrapper that raises regular exceptions instead of exiting."""

  def error(self, message: str) -> Never:
    raise CommandUsageError(message)

  def exit(self, status: int = 0, message: str | None = None) -> Never:
    raise CommandUsageError(message or f"Command exited with status {status}.")


class RiskComposeApp(App[None]):
  """Minimal command-first terminal interface for review workflows."""

  CSS_PATH = "theme.tcss"
  BINDINGS = [
    Binding("ctrl+q", "quit", "Quit", priority=True),
    Binding("ctrl+l", "clear_screen", "Clear", priority=True),
  ]

  def __init__(self, *, startup_bundle_dir: Path | None = None) -> None:
    super().__init__()
    self._startup_bundle_dir = startup_bundle_dir
    self._current_session: ReviewSession | None = None
    self._loaded_explain_input: ExplainInputSession | None = None
    self._selected_subject_id: str | None = None
    self._current_artifact_key: str | None = None
    self._current_search_query: str | None = None
    self._current_page = 1
    self._row_detail_text: str | None = None
    self._last_command: str | None = None

  def compose(self) -> ComposeResult:
    with Vertical(id="app-shell"):
      yield Static(TITLE, id="title-bar")
      yield Static("", id="context-bar")
      yield Static("", id="status-line")
      with VerticalScroll(id="screen-scroll"):
        yield Static("", id="screen-output")
      with Horizontal(id="prompt-row"):
        yield Static(">", id="prompt-glyph")
        yield Input(placeholder="Type `help` for commands.", id="command-input")

  def on_mount(self) -> None:
    """Render the initial screen and optionally open a startup bundle."""
    self.title = TITLE
    self.sub_title = "command-first review"
    self._set_status("Ready. Type `help` for the command set.", tone="info")
    self._render_screen()
    self.query_one("#command-input", Input).focus()
    if self._startup_bundle_dir is not None:
      self._last_command = f"open --bundle-dir {self._startup_bundle_dir}"
      try:
        self._open_bundle_path(self._startup_bundle_dir)
      except ValueError as exc:
        self._set_status(str(exc), tone="error")
        self._render_screen()

  def action_clear_screen(self) -> None:
    """Redraw the current state without changing it."""
    self._row_detail_text = None
    self._render_screen()
    self.query_one("#command-input", Input).focus()

  def on_input_submitted(self, event: Input.Submitted) -> None:
    """Handle typed command submission from the prompt."""
    if event.input.id != "command-input":
      return
    command_text = event.value.strip()
    event.input.value = ""
    if not command_text:
      self.query_one("#command-input", Input).focus()
      return
    self._dispatch_command(command_text)
    self.query_one("#command-input", Input).focus()

  def _dispatch_command(self, command_text: str) -> None:
    self._last_command = command_text
    try:
      tokens = shlex.split(command_text)
    except ValueError as exc:
      self._set_status(f"Could not parse command: {exc}", tone="error")
      return
    if not tokens:
      return
    root = tokens[0]
    try:
      if root == "help":
        self._set_status("Showing command reference.", tone="info")
        self._render_screen(show_help=True)
        return
      if root == "score":
        self._run_score_command(tokens[1:])
        return
      if root == "explain":
        self._run_explain_command(tokens[1:])
        return
      if root == "open":
        self._run_open_command(tokens[1:])
        return
      if root == "artifact":
        self._set_current_artifact(tokens[1:])
        return
      if root == "subject":
        self._set_subject_filter(tokens[1:])
        return
      if root == "search":
        self._set_search_query(tokens[1:])
        return
      if root == "page":
        self._set_page(tokens[1:])
        return
      if root == "next":
        self._advance_page(1)
        return
      if root == "prev":
        self._advance_page(-1)
        return
      if root == "row":
        self._show_row_detail(tokens[1:])
        return
      if root == "export":
        self._export_current_session(tokens[1:])
        return
      if root == "clear":
        self.action_clear_screen()
        self._set_status("Cleared row detail and redrew the current screen.", tone="info")
        return
      if root == "quit":
        self.exit()
        return
      raise CommandUsageError(f"Unknown command `{root}`.")
    except CommandUsageError as exc:
      self._set_status(str(exc), tone="error")
    except ValueError as exc:
      self._set_status(str(exc), tone="error")

  def _run_score_command(self, argv: list[str]) -> None:
    parser = _CommandParser(prog="score", add_help=False)
    parser.add_argument("--subjects", required=True)
    parser.add_argument("--diagnoses", required=True)
    parser.add_argument("--model-version", default="cms_hcc_v28_2026")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--no-mce-edits", action="store_true")
    args = parser.parse_args(argv)
    subjects_path = self._resolve_existing_path(args.subjects, "subjects")
    diagnoses_path = self._resolve_existing_path(args.diagnoses, "diagnoses")
    session = load_score_session(
      subjects_path,
      diagnoses_path,
      build_review_options(
        model_version=args.model_version,
        strict_validation=bool(args.strict),
        disable_mce_edits=bool(args.no_mce_edits),
      ),
    )
    self._apply_session(session, success_message="Score workflow completed.")

  def _run_explain_command(self, argv: list[str]) -> None:
    if not argv:
      raise CommandUsageError("Explain requires a subcommand: `load` or `run`.")
    subcommand = argv[0]
    if subcommand == "load":
      parser = _CommandParser(prog="explain load", add_help=False)
      parser.add_argument("--subjects", required=True)
      parser.add_argument("--diagnoses", required=True)
      parser.add_argument("--model-version", default="cms_hcc_v28_2026")
      parser.add_argument("--strict", action="store_true")
      parser.add_argument("--no-mce-edits", action="store_true")
      args = parser.parse_args(argv[1:])
      subjects_path = self._resolve_existing_path(args.subjects, "subjects")
      diagnoses_path = self._resolve_existing_path(args.diagnoses, "diagnoses")
      explain_input = load_explain_input_session(
        subjects_path,
        diagnoses_path,
        build_review_options(
          model_version=args.model_version,
          strict_validation=bool(args.strict),
          disable_mce_edits=bool(args.no_mce_edits),
        ),
      )
      self._loaded_explain_input = explain_input
      self._current_session = None
      self._current_artifact_key = None
      self._current_search_query = None
      self._current_page = 1
      self._row_detail_text = None
      self._selected_subject_id = explain_input.subject_ids[0] if explain_input.subject_ids else None
      self._set_status(
        f"Loaded {len(explain_input.subject_ids)} subjects for explain review.",
        tone="success",
      )
      self._render_screen()
      return
    if subcommand == "run":
      parser = _CommandParser(prog="explain run", add_help=False)
      parser.add_argument("--subject-id", required=True)
      args = parser.parse_args(argv[1:])
      if self._loaded_explain_input is None:
        raise ValueError("Load explain input before running `explain run`.")
      subject_id = str(args.subject_id)
      if subject_id not in self._loaded_explain_input.subject_ids:
        raise ValueError(f"Subject `{subject_id}` was not loaded for explain review.")
      session = run_explain_session(self._loaded_explain_input, subject_id)
      self._apply_session(session, success_message="Explain workflow completed.")
      return
    raise CommandUsageError(f"Unknown explain subcommand `{subcommand}`.")

  def _run_open_command(self, argv: list[str]) -> None:
    parser = _CommandParser(prog="open", add_help=False)
    parser.add_argument("--bundle-dir", required=True)
    args = parser.parse_args(argv)
    bundle_dir = self._resolve_existing_path(args.bundle_dir, "bundle-dir")
    self._open_bundle_path(bundle_dir)

  def _set_current_artifact(self, argv: list[str]) -> None:
    if len(argv) != 1:
      raise CommandUsageError("Usage: artifact <artifact_key>")
    session = self._require_session()
    artifact_key = argv[0]
    if artifact_key not in available_artifact_keys(session):
      raise ValueError(
        f"Artifact `{artifact_key}` is not available. "
        f"Available: {', '.join(available_artifact_keys(session))}."
      )
    self._current_artifact_key = artifact_key
    self._current_page = 1
    self._current_search_query = None
    self._row_detail_text = None
    self._set_status(f"Switched to artifact `{artifact_key}`.", tone="success")
    self._render_screen()

  def _set_subject_filter(self, argv: list[str]) -> None:
    if len(argv) != 1:
      raise CommandUsageError("Usage: subject <subject_id|all>")
    subject_id = argv[0]
    available_ids = self._available_subject_ids()
    if subject_id == "all":
      self._selected_subject_id = None
    else:
      if subject_id not in available_ids:
        raise ValueError(
          f"Subject `{subject_id}` is not available. "
          f"Available count: {len(available_ids)}."
        )
      self._selected_subject_id = subject_id
    self._current_page = 1
    self._row_detail_text = None
    self._set_status(
      f"Subject filter set to {self._selected_subject_id or 'all'}.",
      tone="success",
    )
    self._render_screen()

  def _set_search_query(self, argv: list[str]) -> None:
    self._require_session()
    self._current_search_query = " ".join(argv).strip() or None
    self._current_page = 1
    self._row_detail_text = None
    self._set_status(
      f"Search query set to `{self._current_search_query or 'none'}`.",
      tone="success",
    )
    self._render_screen()

  def _set_page(self, argv: list[str]) -> None:
    if len(argv) != 1:
      raise CommandUsageError("Usage: page <n>")
    try:
      requested_page = int(argv[0])
    except ValueError as exc:
      raise ValueError("Page expects an integer.") from exc
    if requested_page < 1:
      raise ValueError("Page numbers start at 1.")
    view = self._build_current_view()
    self._current_page = min(requested_page, view.page_count)
    self._row_detail_text = None
    self._set_status(f"Moved to page {self._current_page}.", tone="success")
    self._render_screen()

  def _advance_page(self, delta: int) -> None:
    view = self._build_current_view()
    next_page = min(max(view.page + delta, 1), view.page_count)
    self._current_page = next_page
    self._row_detail_text = None
    self._set_status(f"Moved to page {self._current_page}.", tone="success")
    self._render_screen()

  def _show_row_detail(self, argv: list[str]) -> None:
    if len(argv) != 1:
      raise CommandUsageError("Usage: row <n>")
    try:
      row_number = int(argv[0])
    except ValueError as exc:
      raise ValueError("Row expects an integer.") from exc
    if row_number < 1:
      raise ValueError("Row numbers start at 1.")
    view = self._build_current_view()
    self._row_detail_text = format_row_detail(view, row_number)
    self._set_status(f"Showing row {row_number} from the current page.", tone="success")
    self._render_screen()

  def _export_current_session(self, argv: list[str]) -> None:
    if len(argv) != 1:
      raise CommandUsageError("Usage: export <directory>")
    session = self._require_session()
    export_dir = Path(argv[0]).expanduser().resolve()
    from risk_compose.review import export_review_session

    export_review_session(session, export_dir)
    self._set_status(
      f"Exported {len(session.artifacts)} artifacts to {export_dir}.",
      tone="success",
    )
    self._render_screen()

  def _apply_session(self, session: ReviewSession, *, success_message: str) -> None:
    self._current_session = session
    self._loaded_explain_input = None
    self._current_artifact_key = available_artifact_keys(session)[0]
    self._current_search_query = None
    self._current_page = 1
    self._row_detail_text = None
    if session.export_kind == "explain":
      self._selected_subject_id = session.selected_subject_id
    else:
      self._selected_subject_id = None
    self._set_status(success_message, tone="success")
    self._render_screen()

  def _open_bundle_path(self, bundle_dir: Path) -> None:
    session = load_bundle_session(bundle_dir)
    self._apply_session(session, success_message="Opened exported bundle.")

  def _render_screen(self, *, show_help: bool = False) -> None:
    self.query_one("#context-bar", Static).update(self._build_context_bar())
    self.query_one("#screen-output", Static).update(self._build_screen_output(show_help=show_help))

  def _build_context_bar(self) -> str:
    if self._current_session is None and self._loaded_explain_input is None:
      return "session: none | artifact: none | subject: all | page: - | search: none"
    if self._current_session is None and self._loaded_explain_input is not None:
      return (
        "session: explain-input "
        f"| subjects: {len(self._loaded_explain_input.subject_ids)} "
        f"| subject: {self._selected_subject_id or 'none'}"
      )
    session = self._require_session()
    view = self._build_current_view()
    return (
      f"session: {session.title} "
      f"| artifact: {view.artifact_key} "
      f"| subject: {view.selected_subject_id or 'all'} "
      f"| page: {view.page}/{view.page_count} "
      f"| search: {view.search_query or 'none'}"
    )

  def _build_screen_output(self, *, show_help: bool = False) -> str:
    sections = []
    if self._last_command:
      sections.append(f"$ {self._last_command}")
    if show_help or (self._current_session is None and self._loaded_explain_input is None):
      sections.append(_help_text())
    if self._loaded_explain_input is not None and self._current_session is None:
      sections.append(self._build_explain_input_output())
    if self._current_session is not None:
      view = self._build_current_view()
      sections.append(format_session_summary(self._current_session))
      sections.append(format_artifact_preview(view))
      if self._row_detail_text:
        sections.append(self._row_detail_text)
    return "\n\n".join(section for section in sections if section).strip()

  def _build_explain_input_output(self) -> str:
    explain_input = self._loaded_explain_input
    assert explain_input is not None
    subject_preview = ", ".join(explain_input.subject_ids[:10]) or "none"
    if len(explain_input.subject_ids) > 10:
      subject_preview = f"{subject_preview}, ..."
    return "\n".join(
      (
        "Explain input loaded",
        "",
        f"subjects: {len(explain_input.subject_ids)}",
        f"current subject: {self._selected_subject_id or 'none'}",
        f"source subjects: {explain_input.source_paths['subjects']}",
        f"source diagnoses: {explain_input.source_paths['diagnoses']}",
        f"subject ids: {subject_preview}",
        "",
        "Next step:",
        "explain run --subject-id <id>",
      )
    )

  def _build_current_view(self) -> ArtifactView:
    session = self._require_session()
    artifact_key = self._current_artifact_key or available_artifact_keys(session)[0]
    return build_artifact_view(
      session,
      artifact_key,
      subject_id=self._selected_subject_id,
      search_query=self._current_search_query,
      page=self._current_page,
      page_size=DEFAULT_PAGE_SIZE,
    )

  def _available_subject_ids(self) -> tuple[str, ...]:
    if self._current_session is not None:
      return self._current_session.subject_ids
    if self._loaded_explain_input is not None:
      return self._loaded_explain_input.subject_ids
    return ()

  def _require_session(self) -> ReviewSession:
    if self._current_session is None:
      raise ValueError("Run `score`, `explain run`, or `open` before reviewing artifacts.")
    return self._current_session

  def _resolve_existing_path(self, path_text: str, label: str) -> Path:
    path = Path(path_text).expanduser().resolve()
    if not path.exists():
      raise ValueError(f"Path does not exist for `{label}`: {path}")
    return path

  def _set_status(self, message: str, *, tone: str) -> None:
    status_widget = self.query_one("#status-line", Static)
    status_widget.update(message)
    for class_name in ("status-info", "status-success", "status-warning", "status-error"):
      status_widget.remove_class(class_name)
    if message:
      status_widget.add_class(f"status-{tone}")


def _help_text() -> str:
  sections = [
    "Commands",
    "",
    "score --subjects <path> --diagnoses <path> [--model-version <id>] [--strict] [--no-mce-edits]",
    "explain load --subjects <path> --diagnoses <path> [--model-version <id>] [--strict] [--no-mce-edits]",
    "explain run --subject-id <id>",
    "open --bundle-dir <path>",
    "artifact <artifact_key>",
    "subject <subject_id|all>",
    "search [text]",
    "page <n>",
    "next",
    "prev",
    "row <n>",
    "export <directory>",
    "clear",
    "quit",
    "",
    "Expected explicit-file columns",
    "",
    "Subject aliases:",
    *_format_alias_lines(SUBJECT_COLUMN_ALIASES),
    "",
    "Diagnosis aliases:",
    *_format_alias_lines(DIAGNOSIS_COLUMN_ALIASES),
  ]
  return "\n".join(sections)


def _format_alias_lines(alias_map: dict[str, tuple[str, ...]]) -> list[str]:
  return [f"{canonical}: {', '.join(aliases)}" for canonical, aliases in alias_map.items()]


def run_tui(*, bundle_dir: Path | None = None) -> int:
  """Launch the interactive TUI application."""
  app = RiskComposeApp(startup_bundle_dir=bundle_dir)
  app.run()
  return 0


def main(argv: Sequence[str] | None = None) -> int:
  """Run the standalone TUI console script."""
  parser = argparse.ArgumentParser(prog="risk-compose-tui")
  parser.add_argument(
    "--bundle-dir",
    help="Optional previously exported score or explain bundle to open at startup.",
  )
  args = parser.parse_args(list(argv) if argv is not None else None)
  bundle_dir = Path(args.bundle_dir).resolve() if args.bundle_dir else None
  return run_tui(bundle_dir=bundle_dir)
