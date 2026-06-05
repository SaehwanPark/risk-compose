"""Streamlit GUI for score, explain, and exported-bundle review."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, cast

import streamlit as st

from risk_compose.review import (
  ExplainInputSession,
  MODEL_VERSIONS,
  ReviewSession,
  available_artifact_keys,
  build_artifact_view,
  build_review_options,
  format_row_detail,
  format_session_summary,
  load_bundle_session,
  load_explain_input_session,
  load_score_session,
  run_explain_session,
)

WORKFLOW_KEY = "gui_workflow"
CURRENT_SESSION_KEY = "gui_current_session"
EXPLAIN_INPUT_KEY = "gui_explain_input"
ARTIFACT_KEY = "gui_artifact_key"
BENEFICIARY_KEY = "gui_subject_filter"
SEARCH_KEY = "gui_search_query"
PAGE_KEY = "gui_page_number"
STATUS_KEY = "gui_status"
STARTUP_APPLIED_KEY = "gui_startup_bundle_applied"


def render_gui(*, startup_bundle_dir: Path | None = None) -> None:
  """Render the Streamlit GUI review surface."""
  st.set_page_config(page_title="risk-compose GUI", layout="wide")
  _initialize_state(startup_bundle_dir)

  st.title("risk-compose GUI")
  st.caption("Streamlit review surface for score, explain, and exported bundles.")
  _render_status_message()

  with st.sidebar:
    workflow = st.radio(
      "Workflow",
      ("Score", "Explain", "Open Bundle"),
      key=WORKFLOW_KEY,
    )
    if workflow == "Score":
      _render_score_controls()
    elif workflow == "Explain":
      _render_explain_controls()
    else:
      _render_bundle_controls()
    _render_export_controls()

  session = st.session_state.get(CURRENT_SESSION_KEY)
  if session is None:
    if st.session_state.get(EXPLAIN_INPUT_KEY) is not None:
      _render_explain_loaded_hint()
    else:
      st.info("Run a workflow or open a bundle to preview artifacts.")
    return

  _render_session(session)


def main(argv: list[str] | None = None) -> None:
  """Run the Streamlit app with optional startup bundle arguments."""
  parser = argparse.ArgumentParser(prog="risk-compose gui")
  parser.add_argument("--bundle-dir")
  args, _unknown = parser.parse_known_args(argv)
  startup_bundle_dir = Path(args.bundle_dir).expanduser().resolve() if args.bundle_dir else None
  render_gui(startup_bundle_dir=startup_bundle_dir)


def _initialize_state(startup_bundle_dir: Path | None) -> None:
  st.session_state.setdefault(CURRENT_SESSION_KEY, None)
  st.session_state.setdefault(EXPLAIN_INPUT_KEY, None)
  st.session_state.setdefault(ARTIFACT_KEY, None)
  st.session_state.setdefault(BENEFICIARY_KEY, "All")
  st.session_state.setdefault(SEARCH_KEY, "")
  st.session_state.setdefault(PAGE_KEY, 1)
  st.session_state.setdefault(STATUS_KEY, None)
  st.session_state.setdefault(STARTUP_APPLIED_KEY, False)

  if startup_bundle_dir is not None and not st.session_state[STARTUP_APPLIED_KEY]:
    try:
      session = load_bundle_session(startup_bundle_dir)
    except ValueError as exc:
      _set_status("error", str(exc))
    else:
      _apply_session(session)
      _set_status("success", f"Opened exported bundle from {startup_bundle_dir}.")
    st.session_state[STARTUP_APPLIED_KEY] = True


def _render_status_message() -> None:
  status = st.session_state.get(STATUS_KEY)
  if not status:
    return
  tone, message = status
  if tone == "success":
    st.success(message)
  elif tone == "warning":
    st.warning(message)
  elif tone == "error":
    st.error(message)
  else:
    st.info(message)


def _render_score_controls() -> None:
  st.subheader("Score")
  subjects_path = st.text_input("Subject CSV", key="score_subjects_path")
  diagnoses_path = st.text_input("Diagnosis CSV", key="score_diagnoses_path")
  model_version = st.selectbox(
    "Model Version",
    MODEL_VERSIONS,
    index=MODEL_VERSIONS.index("cms_hcc_v28_2026"),
    key="score_model_version",
  )
  strict_validation = st.checkbox("Strict validation", key="score_strict")
  disable_mce_edits = st.checkbox("Disable MCE edits", key="score_no_mce")
  if st.button("Run Score", key="score_run", type="primary"):
    try:
      session = load_score_session(
        _resolve_existing_path(subjects_path, "subject csv"),
        _resolve_existing_path(diagnoses_path, "diagnosis csv"),
        build_review_options(
          model_version=model_version,
          strict_validation=bool(strict_validation),
          disable_mce_edits=bool(disable_mce_edits),
        ),
      )
    except ValueError as exc:
      _set_status("error", str(exc))
    else:
      _apply_session(session)
      _set_status("success", "Score workflow completed.")


def _render_explain_controls() -> None:
  st.subheader("Explain")
  subjects_path = st.text_input("Subject CSV", key="explain_subjects_path")
  diagnoses_path = st.text_input("Diagnosis CSV", key="explain_diagnoses_path")
  model_version = st.selectbox(
    "Model Version",
    MODEL_VERSIONS,
    index=MODEL_VERSIONS.index("cms_hcc_v28_2026"),
    key="explain_model_version",
  )
  strict_validation = st.checkbox("Strict validation", key="explain_strict")
  disable_mce_edits = st.checkbox("Disable MCE edits", key="explain_no_mce")
  if st.button("Load Subjects", key="explain_load", type="primary"):
    try:
      explain_input = load_explain_input_session(
        _resolve_existing_path(subjects_path, "subject csv"),
        _resolve_existing_path(diagnoses_path, "diagnosis csv"),
        build_review_options(
          model_version=model_version,
          strict_validation=bool(strict_validation),
          disable_mce_edits=bool(disable_mce_edits),
        ),
      )
    except ValueError as exc:
      _set_status("error", str(exc))
    else:
      st.session_state[EXPLAIN_INPUT_KEY] = explain_input
      st.session_state[CURRENT_SESSION_KEY] = None
      st.session_state[BENEFICIARY_KEY] = explain_input.subject_ids[0] if explain_input.subject_ids else "All"
      _set_status("success", f"Loaded {len(explain_input.subject_ids)} subjects for explain review.")

  loaded_explain_input = cast(ExplainInputSession | None, st.session_state.get(EXPLAIN_INPUT_KEY))
  if loaded_explain_input is None:
    return
  subject_options = list(loaded_explain_input.subject_ids)
  if subject_options:
    current_subject = st.session_state[BENEFICIARY_KEY]
    explain_subject_key = "explain_selected_subject"
    if st.session_state.get(explain_subject_key) not in subject_options:
      st.session_state[explain_subject_key] = (
        current_subject if current_subject in subject_options else subject_options[0]
      )
    st.selectbox(
      "Subject",
      subject_options,
      index=subject_options.index(st.session_state[explain_subject_key]),
      key=explain_subject_key,
    )
  if st.button("Run Explain", key="explain_run"):
    try:
      session = run_explain_session(
        loaded_explain_input,
        str(st.session_state.get("explain_selected_subject", "")),
      )
    except ValueError as exc:
      _set_status("error", str(exc))
    else:
      _apply_session(session)
      _set_status(
        "success",
        f"Explain workflow completed for {st.session_state.get('explain_selected_subject', '')}.",
      )


def _render_bundle_controls() -> None:
  st.subheader("Open Bundle")
  bundle_dir = st.text_input("Bundle Directory", key="bundle_dir_path")
  if st.button("Open Bundle", key="bundle_open", type="primary"):
    try:
      session = load_bundle_session(_resolve_existing_path(bundle_dir, "bundle directory"))
    except ValueError as exc:
      _set_status("error", str(exc))
    else:
      _apply_session(session)
      _set_status("success", f"Opened exported bundle from {bundle_dir}.")


def _render_export_controls() -> None:
  st.divider()
  st.subheader("Export")
  export_dir = st.text_input("Export Directory", key="export_dir_path")
  session = st.session_state.get(CURRENT_SESSION_KEY)
  if st.button("Export Current Session", key="export_current", disabled=session is None):
    if session is None:
      _set_status("warning", "Run a workflow or open a bundle before exporting.")
      return
    if not export_dir.strip():
      _set_status("warning", "Provide an export directory before exporting.")
      return
    from risk_compose.review import export_review_session

    export_path = Path(export_dir).expanduser().resolve()
    export_review_session(session, export_path)
    _set_status("success", f"Exported {len(session.artifacts)} artifacts to {export_path}.")


def _render_explain_loaded_hint() -> None:
  explain_input = st.session_state[EXPLAIN_INPUT_KEY]
  st.info(
    "Explain input is loaded. Choose a subject in the sidebar and run the explain workflow."
  )
  st.text(
    "\n".join(
      (
        f"subjects loaded: {len(explain_input.subject_ids)}",
        f"current subject: {st.session_state.get(BENEFICIARY_KEY, 'none')}",
        f"subjects path: {explain_input.source_paths['subjects']}",
        f"diagnoses path: {explain_input.source_paths['diagnoses']}",
      )
    )
  )


def _render_session(session: ReviewSession) -> None:
  artifact_options = list(available_artifact_keys(session))
  if st.session_state[ARTIFACT_KEY] not in artifact_options:
    st.session_state[ARTIFACT_KEY] = artifact_options[0]
  if session.export_kind == "explain" and session.selected_subject_id:
    subject_default = session.selected_subject_id
  else:
    subject_default = "All"
  if st.session_state[BENEFICIARY_KEY] not in {"All", *session.subject_ids}:
    st.session_state[BENEFICIARY_KEY] = subject_default

  left_col, right_col = st.columns((1, 2))
  with left_col:
    st.subheader("Run Summary")
    st.code(format_session_summary(session), language="text")
    st.selectbox(
      "Artifact",
      artifact_options,
      index=artifact_options.index(st.session_state[ARTIFACT_KEY]),
      key=ARTIFACT_KEY,
      on_change=_reset_search_and_page,
    )
    st.selectbox(
      "Subject filter",
      ["All", *session.subject_ids],
      index=["All", *session.subject_ids].index(st.session_state[BENEFICIARY_KEY]),
      key=BENEFICIARY_KEY,
      on_change=_reset_page_only,
    )
    st.text_input("Search current artifact", key=SEARCH_KEY, on_change=_reset_page_only)

  view = build_artifact_view(
    session,
    st.session_state[ARTIFACT_KEY],
    subject_id=None if st.session_state[BENEFICIARY_KEY] == "All" else st.session_state[BENEFICIARY_KEY],
    search_query=st.session_state[SEARCH_KEY] or None,
    page=int(st.session_state[PAGE_KEY]),
  )
  st.session_state[PAGE_KEY] = view.page

  with left_col:
    page_options = list(range(1, view.page_count + 1))
    st.selectbox(
      "Page",
      page_options,
      index=page_options.index(view.page),
      key=PAGE_KEY,
    )
    view = build_artifact_view(
      session,
      st.session_state[ARTIFACT_KEY],
      subject_id=None if st.session_state[BENEFICIARY_KEY] == "All" else st.session_state[BENEFICIARY_KEY],
      search_query=st.session_state[SEARCH_KEY] or None,
      page=int(st.session_state[PAGE_KEY]),
    )

  with right_col:
    st.subheader(view.artifact_label)
    st.caption(
      f"Showing {len(view.page_rows)} row(s) on page {view.page} of {view.page_count}. "
      f"Filtered rows: {view.filtered_row_count} / {view.total_row_count}."
    )
    if view.page_rows:
      st.dataframe(list(view.page_rows), width="stretch", hide_index=True)
      row_options: list[Any] = ["None", *range(1, len(view.page_rows) + 1)]
      if st.session_state.get("row_detail_selectbox") not in row_options:
        st.session_state["row_detail_selectbox"] = "None"
      selected_row = st.selectbox("Row detail", row_options, key="row_detail_selectbox")
      if isinstance(selected_row, int):
        st.code(format_row_detail(view, selected_row), language="text")
    else:
      st.info("No rows matched the current filters.")


def _apply_session(session: ReviewSession) -> None:
  st.session_state[CURRENT_SESSION_KEY] = session
  st.session_state[EXPLAIN_INPUT_KEY] = None
  st.session_state[ARTIFACT_KEY] = available_artifact_keys(session)[0]
  st.session_state[PAGE_KEY] = 1
  st.session_state[SEARCH_KEY] = ""
  if session.export_kind == "explain" and session.selected_subject_id:
    st.session_state[BENEFICIARY_KEY] = session.selected_subject_id
  else:
    st.session_state[BENEFICIARY_KEY] = "All"


def _set_status(tone: str, message: str) -> None:
  st.session_state[STATUS_KEY] = (tone, message)


def _reset_search_and_page() -> None:
  st.session_state[SEARCH_KEY] = ""
  st.session_state[PAGE_KEY] = 1


def _reset_page_only() -> None:
  st.session_state[PAGE_KEY] = 1


def _resolve_existing_path(path_text: str, label: str) -> Path:
  path = Path(path_text).expanduser().resolve()
  if not path.exists():
    raise ValueError(f"Path does not exist for {label}: {path}")
  return path


if __name__ == "__main__":
  main(sys.argv[1:])
