"""Pure score-stage logic for the typed scoring core."""

from __future__ import annotations

from risk_compose._typing import ArtifactRow, ArtifactValue
from risk_compose.registry import ScoreFactor, get_elixhauser_tables, get_model_tables, read_reference_rows
from risk_compose.types import ModelSpec, ScoreArtifacts, ScoringOptions, TableArtifact

SCORE_CONTRIBUTION_COLUMNS = (
  "subject_id",
  "score_family",
  "variable_name",
  "coefficient",
  "value",
  "contribution",
  "contribution_status",
)

RAF_TOTAL_COLUMNS = (
  "subject_id",
  "score_family",
  "raf_total",
)


def calculate_scores(
  subject_predictors: TableArtifact,
  model_spec: ModelSpec,
  *,
  options: ScoringOptions | None = None,
) -> ScoreArtifacts:
  """Generate stable score-family columns and score contribution artifacts."""
  resolved_options = options or ScoringOptions(model_version=model_spec.version_id)
  if model_spec.family in {"cms_hcc", "rxhcc"}:
    return _calculate_factor_table_scores(
      subject_predictors,
      model_spec,
      options=resolved_options,
    )
  if model_spec.family == "esrd":
    return _calculate_esrd_scores(
      subject_predictors,
      model_spec,
      options=resolved_options,
    )
  if model_spec.family == "ahrq_elixhauser":
    return _calculate_elixhauser_scores(
      subject_predictors,
      model_spec,
      options=resolved_options,
    )
  raise NotImplementedError(f"Unsupported score family: {model_spec.family}")


def _calculate_factor_table_scores(
  subject_predictors: TableArtifact,
  model_spec: ModelSpec,
  *,
  options: ScoringOptions,
) -> ScoreArtifacts:
  """Apply direct coefficient-table multiplication for score families."""
  model_tables = get_model_tables(model_spec.version_id)
  score_columns = _score_columns(model_spec)
  score_rows: list[ArtifactRow] = []
  contribution_rows: list[ArtifactRow] = []
  for predictor_row in subject_predictors.rows:
    score_row: ArtifactRow = {
      "subject_id": predictor_row["subject_id"],
      "model_version": model_spec.version_id,
    }
    for score_family in model_spec.score_families:
      total_score, applied_rows = _factor_rows_for_score_family(
        predictor_row,
        score_family,
        model_tables.score_factors.get(score_family, ()),
        round_digits=options.score_round_digits,
      )
      _append_score_family(
        score_row,
        contribution_rows,
        subject_id=str(predictor_row["subject_id"]),
        score_family=score_family,
        total_score=total_score,
        applied_rows=applied_rows,
        round_digits=options.score_round_digits,
      )
    score_rows.append(score_row)
  return ScoreArtifacts(
    model_spec=model_spec,
    subject_scores=TableArtifact(
      name="subject_scores",
      columns=("subject_id", "model_version", *score_columns),
      rows=tuple(score_rows),
    ),
    score_contributions=TableArtifact(
      name="score_contributions",
      columns=SCORE_CONTRIBUTION_COLUMNS,
      rows=tuple(contribution_rows),
    ),
    validation_issues=(),
  )


def _calculate_esrd_scores(
  subject_predictors: TableArtifact,
  model_spec: ModelSpec,
  *,
  options: ScoringOptions,
) -> ScoreArtifacts:
  """Apply ESRD base, duration-adjusted, and transplant score logic."""
  model_tables = get_model_tables(model_spec.version_id)
  graft_duration_rows = read_reference_rows(model_spec.reference_paths["graft_duration_scores"])
  transplant_rows = read_reference_rows(model_spec.reference_paths["transplant_scores"])
  inst_graft_rows = (
    read_reference_rows(model_spec.reference_paths["inst_graft_scores"])
    if "inst_graft_scores" in model_spec.reference_paths
    else ()
  )

  score_rows: list[ArtifactRow] = []
  contribution_rows: list[ArtifactRow] = []
  for predictor_row in subject_predictors.rows:
    subject_id = str(predictor_row["subject_id"])
    score_row: ArtifactRow = {
      "subject_id": subject_id,
      "model_version": model_spec.version_id,
    }
    base_scores = {
      family: _factor_rows_for_score_family(
        predictor_row,
        family,
        model_tables.score_factors.get(family, ()),
        round_digits=options.score_round_digits,
      )
      for family in model_tables.score_factors
    }

    _append_score_family(
      score_row,
      contribution_rows,
      subject_id=subject_id,
      score_family="dial",
      total_score=base_scores.get("dial", (0.0, []))[0],
      applied_rows=list(base_scores.get("dial", (0.0, []))[1]),
      round_digits=options.score_round_digits,
    )

    if model_spec.version_id == "esrd_v21_2026":
      _append_esrd_v21_scores(
        predictor_row,
        score_row,
        contribution_rows,
        base_scores=base_scores,
        graft_duration_rows=graft_duration_rows,
        transplant_rows=transplant_rows,
        round_digits=options.score_round_digits,
      )
    else:
      _append_esrd_v24_scores(
        predictor_row,
        score_row,
        contribution_rows,
        base_scores=base_scores,
        graft_duration_rows=graft_duration_rows,
        transplant_rows=transplant_rows,
        inst_graft_rows=inst_graft_rows,
        round_digits=options.score_round_digits,
      )
    score_rows.append(score_row)

  return ScoreArtifacts(
    model_spec=model_spec,
    subject_scores=TableArtifact(
      name="subject_scores",
      columns=("subject_id", "model_version", *_score_columns(model_spec)),
      rows=tuple(score_rows),
    ),
    score_contributions=TableArtifact(
      name="score_contributions",
      columns=SCORE_CONTRIBUTION_COLUMNS,
      rows=tuple(contribution_rows),
    ),
    validation_issues=(),
  )


def _calculate_elixhauser_scores(
  subject_predictors: TableArtifact,
  model_spec: ModelSpec,
  *,
  options: ScoringOptions,
) -> ScoreArtifacts:
  """Calculate AHRQ Elixhauser readmission and mortality indices."""
  model_tables = get_elixhauser_tables(model_spec.version_id)
  score_rows: list[ArtifactRow] = []
  contribution_rows: list[ArtifactRow] = []
  for predictor_row in subject_predictors.rows:
    subject_id = str(predictor_row["subject_id"])
    score_row: ArtifactRow = {
      "subject_id": subject_id,
      "model_version": model_spec.version_id,
    }
    has_missing_measure = any(
      predictor_row.get(measure.measure) is None for measure in model_tables.measures
    )
    totals = {"readmission_index": 0.0, "mortality_index": 0.0}
    for measure in model_tables.measures:
      value = _numeric_value(predictor_row.get(measure.measure))
      weight = model_tables.weights_by_measure[measure.measure]
      for score_family, coefficient in (
        ("readmission_index", weight.readmission_weight),
        ("mortality_index", weight.mortality_weight),
      ):
        contribution = value * coefficient
        totals[score_family] += contribution
        if contribution:
          contribution_rows.append(
            _contribution_row(
              subject_id=subject_id,
              score_family=score_family,
              variable_name=measure.measure,
              coefficient=float(coefficient),
              value=value,
              contribution=contribution,
              round_digits=options.score_round_digits,
            ),
          )
    for score_family in model_spec.score_families:
      score_row[f"score_{score_family}"] = (
        None if has_missing_measure else round(totals[score_family], options.score_round_digits)
      )
      if has_missing_measure:
        contribution_rows.append(
          {
            "subject_id": subject_id,
            "score_family": score_family,
            "variable_name": "poa_required_measure",
            "coefficient": 0.0,
            "value": 0.0,
            "contribution": None,
            "contribution_status": "missing_poa",
          },
        )
    score_rows.append(score_row)
  return ScoreArtifacts(
    model_spec=model_spec,
    subject_scores=TableArtifact(
      name="subject_scores",
      columns=("subject_id", "model_version", *_score_columns(model_spec)),
      rows=tuple(score_rows),
    ),
    score_contributions=TableArtifact(
      name="score_contributions",
      columns=SCORE_CONTRIBUTION_COLUMNS,
      rows=tuple(contribution_rows),
    ),
    validation_issues=(),
  )


def _append_esrd_v21_scores(
  predictor_row: ArtifactRow,
  score_row: ArtifactRow,
  contribution_rows: list[ArtifactRow],
  *,
  base_scores: dict[str, tuple[float, list[ArtifactRow]]],
  graft_duration_rows: tuple[dict[str, str], ...],
  transplant_rows: tuple[dict[str, str], ...],
  round_digits: int,
) -> None:
  """Append ESRD v21 public score families for one subject."""
  graft_duration_scores = {
    row["Graft Duration"]: float(row["Score"])
    for row in graft_duration_rows
    if row.get("Graft Duration") and row.get("Score")
  }

  for base_family in ("graft_comm", "graft_inst"):
    base_total, base_rows = base_scores.get(base_family, (0.0, []))
    for duration_label, duration_score in graft_duration_scores.items():
      public_family = f"{base_family}_{duration_label.lower()}"
      age_flag = _numeric_value(
        predictor_row["Aged"] if "GE65" in duration_label else predictor_row["NonAged"]
      )
      extra_rows: list[ArtifactRow] = []
      total_score = base_total
      if base_total:
        duration_contribution = duration_score * age_flag
        total_score += duration_contribution
        if duration_contribution:
          extra_rows.append(
            _contribution_row(
              subject_id=str(predictor_row["subject_id"]),
              score_family=public_family,
              variable_name=duration_label.lower(),
              coefficient=duration_score,
              value=age_flag,
              contribution=duration_contribution,
              round_digits=round_digits,
            ),
          )
      _append_score_family(
        score_row,
        contribution_rows,
        subject_id=str(predictor_row["subject_id"]),
        score_family=public_family,
        total_score=total_score,
        applied_rows=[
          *_retag_contribution_rows(base_rows, score_family=public_family),
          *extra_rows,
        ]
        if base_total
        else [],
        round_digits=round_digits,
      )

  dial_ne_total, dial_ne_rows = base_scores.get("dial_ne", (0.0, []))
  _append_score_family(
    score_row,
    contribution_rows,
    subject_id=str(predictor_row["subject_id"]),
    score_family="dial_ne",
    total_score=dial_ne_total,
    applied_rows=list(dial_ne_rows),
    round_digits=round_digits,
  )

  graft_ne_total, graft_ne_rows = base_scores.get("graft_ne", (0.0, []))
  ne_aged = _numeric_value(
    int(
      _numeric_value(predictor_row["age"]) >= 65
      or (
        _numeric_value(predictor_row["age"]) == 64
        and _numeric_value(predictor_row["original_reason_entitlement_code"]) == 0
      ),
    ),
  )
  ne_nonaged = 1.0 - ne_aged
  for duration_label, duration_score in graft_duration_scores.items():
    public_family = f"graft_ne_{duration_label.lower()}"
    age_flag = ne_aged if "GE65" in duration_label else ne_nonaged
    extra_rows = []
    total_score = graft_ne_total
    if graft_ne_total:
      duration_contribution = duration_score * age_flag
      total_score += duration_contribution
      if duration_contribution:
        extra_rows.append(
          _contribution_row(
            subject_id=str(predictor_row["subject_id"]),
            score_family=public_family,
            variable_name=duration_label.lower(),
            coefficient=duration_score,
            value=age_flag,
            contribution=duration_contribution,
            round_digits=round_digits,
          ),
        )
    _append_score_family(
      score_row,
      contribution_rows,
      subject_id=str(predictor_row["subject_id"]),
      score_family=public_family,
      total_score=total_score,
      applied_rows=[
        *_retag_contribution_rows(graft_ne_rows, score_family=public_family),
        *extra_rows,
      ]
      if graft_ne_total
      else [],
      round_digits=round_digits,
    )

  _append_transplant_scores(
    score_row,
    contribution_rows,
    subject_id=str(predictor_row["subject_id"]),
    transplant_rows=transplant_rows,
    round_digits=round_digits,
  )


def _append_esrd_v24_scores(
  predictor_row: ArtifactRow,
  score_row: ArtifactRow,
  contribution_rows: list[ArtifactRow],
  *,
  base_scores: dict[str, tuple[float, list[ArtifactRow]]],
  graft_duration_rows: tuple[dict[str, str], ...],
  transplant_rows: tuple[dict[str, str], ...],
  inst_graft_rows: tuple[dict[str, str], ...],
  round_digits: int,
) -> None:
  """Append ESRD v24 public score families for one subject."""
  graft_duration_scores = {
    row["Graft Duration"]: float(row["Score"])
    for row in graft_duration_rows
    if row.get("Graft Duration") and row.get("Score")
  }
  inst_graft_scores = {
    row["Graft Duration"]: float(row["Score"])
    for row in inst_graft_rows
    if row.get("Graft Duration") and row.get("Score")
  }
  aged = _numeric_value(predictor_row["Aged"])
  nonaged = _numeric_value(predictor_row["NonAged"])
  partial_dual = _numeric_value(predictor_row["partial_benefit_dual_flag"])
  full_dual = _numeric_value(predictor_row["full_benefit_dual_flag"])
  lti = _numeric_value(predictor_row["long_term_institutional_flag"])

  for duration_label, duration_score in graft_duration_scores.items():
    if "flag" in duration_label:
      continue
    normalized_label = duration_label.lower()
    age_group = "ge65" if "ge65" in normalized_label else "lt65"
    duration_suffix = "dur4_9" if "dur4_9" in normalized_label else "dur10pl"
    segment = "nd_pbd" if "nd_pbd" in normalized_label else "fbd"
    base_family = f"g_comm_{segment}_{age_group}"
    public_family = f"{base_family}_{duration_suffix}"
    base_total, base_rows = base_scores.get(base_family, (0.0, []))
    age_flag = aged if age_group == "ge65" else nonaged
    total_score = base_total
    inst_extra_rows: list[ArtifactRow] = []
    if base_total:
      duration_contribution = duration_score * age_flag
      total_score += duration_contribution
      if duration_contribution:
        inst_extra_rows.append(
          _contribution_row(
            subject_id=str(predictor_row["subject_id"]),
            score_family=public_family,
            variable_name=duration_label.lower(),
            coefficient=duration_score,
            value=age_flag,
            contribution=duration_contribution,
            round_digits=round_digits,
          ),
        )
      if segment == "nd_pbd":
        pbd_label = "PBD_GE65_flag" if age_group == "ge65" else "PBD_LT65_flag"
        pbd_score = graft_duration_scores[pbd_label]
        pbd_contribution = pbd_score * partial_dual * age_flag
        total_score += pbd_contribution
        if pbd_contribution:
          inst_extra_rows.append(
            _contribution_row(
              subject_id=str(predictor_row["subject_id"]),
              score_family=public_family,
              variable_name=pbd_label.lower(),
              coefficient=pbd_score,
              value=partial_dual * age_flag,
              contribution=pbd_contribution,
              round_digits=round_digits,
            ),
          )
    _append_score_family(
      score_row,
      contribution_rows,
      subject_id=str(predictor_row["subject_id"]),
      score_family=public_family,
      total_score=total_score,
      applied_rows=[
        *_retag_contribution_rows(base_rows, score_family=public_family),
        *inst_extra_rows,
      ]
      if base_total
      else [],
      round_digits=round_digits,
    )

  graft_inst_total, graft_inst_rows = base_scores.get("graft_inst", (0.0, []))
  for duration_label, duration_score in inst_graft_scores.items():
    if duration_label in {"FGI_PBD_LT65_flag", "FGI_PBD_GE65_flag", "LTI_LT65", "LTI_GE65"}:
      continue
    tokens = duration_label.lower().replace("fgi_", "").split("_")
    age_group = "ge65" if "ge65" in tokens else "lt65"
    segment = "fbd" if "fbd" in tokens else "nd_pbd"
    duration_suffix = "dur4_9" if "dur4" in duration_label.lower() else "dur10pl"
    public_family = f"graft_inst_{segment}_{age_group}_{duration_suffix}"
    age_flag = aged if age_group == "ge65" else nonaged
    total_score = graft_inst_total
    graft_inst_extra_rows: list[ArtifactRow] = []
    if graft_inst_total:
      main_contribution = duration_score * age_flag
      total_score += main_contribution
      if main_contribution:
        graft_inst_extra_rows.append(
          _contribution_row(
            subject_id=str(predictor_row["subject_id"]),
            score_family=public_family,
            variable_name=duration_label.lower(),
            coefficient=duration_score,
            value=age_flag,
            contribution=main_contribution,
            round_digits=round_digits,
          ),
        )
      lti_label = "LTI_GE65" if age_group == "ge65" else "LTI_LT65"
      lti_score = inst_graft_scores[lti_label]
      lti_contribution = lti_score * lti * age_flag
      total_score += lti_contribution
      if lti_contribution:
        graft_inst_extra_rows.append(
          _contribution_row(
            subject_id=str(predictor_row["subject_id"]),
            score_family=public_family,
            variable_name=lti_label.lower(),
            coefficient=lti_score,
            value=lti * age_flag,
            contribution=lti_contribution,
            round_digits=round_digits,
          ),
        )
      if segment == "nd_pbd":
        pbd_label = "FGI_PBD_GE65_flag" if age_group == "ge65" else "FGI_PBD_LT65_flag"
        pbd_score = inst_graft_scores[pbd_label]
        pbd_contribution = pbd_score * partial_dual * age_flag
        total_score += pbd_contribution
        if pbd_contribution:
          graft_inst_extra_rows.append(
            _contribution_row(
              subject_id=str(predictor_row["subject_id"]),
              score_family=public_family,
              variable_name=pbd_label.lower(),
              coefficient=pbd_score,
              value=partial_dual * age_flag,
              contribution=pbd_contribution,
              round_digits=round_digits,
            ),
          )
    _append_score_family(
      score_row,
      contribution_rows,
      subject_id=str(predictor_row["subject_id"]),
      score_family=public_family,
      total_score=total_score,
      applied_rows=[
        *_retag_contribution_rows(graft_inst_rows, score_family=public_family),
        *graft_inst_extra_rows,
      ]
      if graft_inst_total
      else [],
      round_digits=round_digits,
    )

  dial_ne_total, dial_ne_rows = base_scores.get("dial_ne", (0.0, []))
  _append_score_family(
    score_row,
    contribution_rows,
    subject_id=str(predictor_row["subject_id"]),
    score_family="dial_ne",
    total_score=dial_ne_total,
    applied_rows=list(dial_ne_rows),
    round_digits=round_digits,
  )

  graft_ne_total, graft_ne_rows = base_scores.get("graft_ne", (0.0, []))
  ne_aged = _numeric_value(
    int(
      _numeric_value(predictor_row["age"]) >= 65
      or (
        _numeric_value(predictor_row["age"]) == 64
        and _numeric_value(predictor_row["original_reason_entitlement_code"]) == 0
      ),
    ),
  )
  ne_nonaged = 1.0 - ne_aged
  not_full_dual = 1.0 - full_dual
  for duration_label, duration_score in graft_duration_scores.items():
    if duration_label in {"PBD_LT65_flag", "PBD_GE65_flag"}:
      continue
    normalized_label = duration_label.lower()
    age_group = "ge65" if "ge65" in normalized_label else "lt65"
    duration_suffix = "dur4_9" if "dur4_9" in normalized_label else "dur10pl"
    segment = "nd_pbd" if "nd_pbd" in normalized_label else "fbd"
    public_family = f"graft_ne_{age_group}_{duration_suffix}_{segment}"
    act_adj = 0.905 if duration_suffix == "dur4_9" else 0.698
    age_flag = ne_aged if age_group == "ge65" else ne_nonaged
    segment_flag = full_dual if segment == "fbd" else not_full_dual
    total_score = 0.0
    graft_ne_extra_rows: list[ArtifactRow] = []
    scaled_base_rows: list[ArtifactRow] = []
    if graft_ne_total:
      total_score, scaled_base_rows = _factor_rows_for_score_family(
        predictor_row,
        public_family,
        get_model_tables("esrd_v24_2026").score_factors.get("graft_ne", ()),
        round_digits=round_digits,
        coefficient_scale=1 / act_adj,
      )
      duration_contribution = (duration_score * age_flag * segment_flag) / act_adj
      total_score += duration_contribution
      if duration_contribution:
        graft_ne_extra_rows.append(
          _contribution_row(
            subject_id=str(predictor_row["subject_id"]),
            score_family=public_family,
            variable_name=duration_label.lower(),
            coefficient=duration_score / act_adj,
            value=age_flag * segment_flag,
            contribution=duration_contribution,
            round_digits=round_digits,
          ),
        )
    _append_score_family(
      score_row,
      contribution_rows,
      subject_id=str(predictor_row["subject_id"]),
      score_family=public_family,
      total_score=total_score,
      applied_rows=[*scaled_base_rows, *graft_ne_extra_rows] if graft_ne_total else [],
      round_digits=round_digits,
    )

  _append_transplant_scores(
    score_row,
    contribution_rows,
    subject_id=str(predictor_row["subject_id"]),
    transplant_rows=transplant_rows,
    round_digits=round_digits,
  )


def _append_transplant_scores(
  score_row: ArtifactRow,
  contribution_rows: list[ArtifactRow],
  *,
  subject_id: str,
  transplant_rows: tuple[dict[str, str], ...],
  round_digits: int,
) -> None:
  """Append constant transplant public score families."""
  for row in transplant_rows:
    family = row["Variable"].lower()
    score = float(row["Score"])
    applied_rows = [
      _contribution_row(
        subject_id=subject_id,
        score_family=family,
        variable_name=family,
        coefficient=score,
        value=1.0,
        contribution=score,
        round_digits=round_digits,
      ),
    ]
    _append_score_family(
      score_row,
      contribution_rows,
      subject_id=subject_id,
      score_family=family,
      total_score=score,
      applied_rows=applied_rows,
      round_digits=round_digits,
    )


def _append_score_family(
  score_row: ArtifactRow,
  contribution_rows: list[ArtifactRow],
  *,
  subject_id: str,
  score_family: str,
  total_score: float,
  applied_rows: list[ArtifactRow],
  round_digits: int,
) -> None:
  """Append one score family and its contribution rows."""
  rounded_total = round(total_score, round_digits)
  score_row[f"score_{score_family}"] = rounded_total
  if applied_rows:
    contribution_rows.extend(applied_rows)
    return
  contribution_rows.append(
    {
      "subject_id": subject_id,
      "score_family": score_family,
      "variable_name": "score_total",
      "coefficient": 0.0,
      "value": 0.0,
      "contribution": rounded_total,
      "contribution_status": "zero_score",
    },
  )


def _factor_rows_for_score_family(
  predictor_row: ArtifactRow,
  score_family: str,
  factors: tuple[ScoreFactor, ...],
  *,
  round_digits: int,
  coefficient_scale: float = 1.0,
) -> tuple[float, list[ArtifactRow]]:
  """Return the score total and contribution rows for one factor table family."""
  total_score = 0.0
  applied_rows: list[ArtifactRow] = []
  for factor in factors:
    coefficient = factor.coefficient * coefficient_scale
    value = _numeric_value(predictor_row.get(factor.variable))
    contribution = value * coefficient
    total_score += contribution
    if contribution:
      applied_rows.append(
        _contribution_row(
          subject_id=str(predictor_row["subject_id"]),
          score_family=score_family,
          variable_name=factor.variable,
          coefficient=coefficient,
          value=value,
          contribution=contribution,
          round_digits=round_digits,
        ),
      )
  return total_score, applied_rows


def _retag_contribution_rows(
  rows: list[ArtifactRow],
  *,
  score_family: str,
) -> list[ArtifactRow]:
  """Copy contribution rows under one public score-family name."""
  return [{**row, "score_family": score_family} for row in rows]


def _contribution_row(
  *,
  subject_id: str,
  score_family: str,
  variable_name: str,
  coefficient: float,
  value: float,
  contribution: float,
  round_digits: int,
) -> ArtifactRow:
  """Build one applied contribution row."""
  return {
    "subject_id": subject_id,
    "score_family": score_family,
    "variable_name": variable_name,
    "coefficient": coefficient,
    "value": value,
    "contribution": round(contribution, round_digits),
    "contribution_status": "applied",
  }


def build_raf_totals(subject_scores: TableArtifact, model_spec: ModelSpec) -> TableArtifact:
  """Build a long-form RAF totals artifact from subject score rows."""
  rows: list[ArtifactRow] = []
  for score_row in subject_scores.rows:
    subject_id = score_row["subject_id"]
    for score_family in model_spec.score_families:
      score_column = f"score_{score_family}"
      rows.append(
        {
          "subject_id": subject_id,
          "score_family": score_family,
          "raf_total": score_row.get(score_column, 0.0),
        },
      )
  return TableArtifact(
    name="raf_totals",
    columns=RAF_TOTAL_COLUMNS,
    rows=tuple(rows),
  )


def _score_columns(model_spec: ModelSpec) -> tuple[str, ...]:
  """Return stable public score column names for a model spec."""
  return tuple(f"score_{score_family}" for score_family in model_spec.score_families)


def _numeric_value(value: ArtifactValue) -> float:
  """Convert predictor artifact values to numeric coefficient inputs."""
  if value in (None, "", False):
    return 0.0
  if value is True:
    return 1.0
  if isinstance(value, (int, float)):
    return float(value)
  if isinstance(value, str):
    return float(value)
  return 0.0
