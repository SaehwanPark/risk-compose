"""DataFrame engine adapters for the typed RAF scoring core."""

from __future__ import annotations

import importlib
from typing import cast

from risk_compose._artifact_io import validation_issues_to_artifact
from risk_compose._typing import (
  PandasFrame,
  PandasModule,
  PolarsFrame,
  PolarsModule,
  SparkDataFrame,
  SparkSessionLike,
)
from risk_compose.core import score_subjects
from risk_compose.types import EngineArtifacts, ScoringOptions, TableArtifact, ValidationIssue
from risk_compose.validation import build_request_from_rows


def score_pandas(
  subjects: PandasFrame,
  diagnoses: PandasFrame,
  *,
  options: ScoringOptions | None = None,
) -> EngineArtifacts[PandasFrame]:
  """Score pandas inputs and return pandas artifact tables with stable schemas."""
  pd = cast(PandasModule, _import_optional_dependency("pandas", "score_pandas"))
  request = build_request_from_rows(
    subjects.to_dict(orient="records"),
    diagnoses.to_dict(orient="records"),
    options=options,
  )
  result = score_subjects(request)
  return EngineArtifacts(
    subject_predictors=_artifact_to_pandas(pd, result.predictors.subject_predictors),
    subject_scores=_artifact_to_pandas(pd, result.scores.subject_scores),
    diagnosis_mappings=_artifact_to_pandas(pd, result.predictors.diagnosis_mappings),
    score_contributions=_artifact_to_pandas(pd, result.scores.score_contributions),
    validation_issues=_artifact_to_pandas(
      pd,
      _validation_issues_to_artifact(result.validation_issues),
    ),
  )


def score_polars(
  subjects: PolarsFrame,
  diagnoses: PolarsFrame,
  *,
  options: ScoringOptions | None = None,
) -> EngineArtifacts[PolarsFrame]:
  """Score polars inputs and return polars artifact tables with stable schemas."""
  pl = cast(PolarsModule, _import_optional_dependency("polars", "score_polars"))
  request = build_request_from_rows(
    subjects.to_dicts(),
    diagnoses.to_dicts(),
    options=options,
  )
  result = score_subjects(request)
  return EngineArtifacts(
    subject_predictors=_artifact_to_polars(pl, result.predictors.subject_predictors),
    subject_scores=_artifact_to_polars(pl, result.scores.subject_scores),
    diagnosis_mappings=_artifact_to_polars(pl, result.predictors.diagnosis_mappings),
    score_contributions=_artifact_to_polars(pl, result.scores.score_contributions),
    validation_issues=_artifact_to_polars(
      pl,
      _validation_issues_to_artifact(result.validation_issues),
    ),
  )


def score_pyspark(
  subjects: SparkDataFrame,
  diagnoses: SparkDataFrame,
  *,
  options: ScoringOptions | None = None,
) -> EngineArtifacts[SparkDataFrame]:
  """Score PySpark inputs and return Spark artifact tables with stable schemas."""
  _import_optional_dependency("pyspark", "score_pyspark")
  request = build_request_from_rows(
    [row.asDict(recursive=True) for row in subjects.toLocalIterator()],
    [row.asDict(recursive=True) for row in diagnoses.toLocalIterator()],
    options=options,
  )
  result = score_subjects(request)
  spark = subjects.sparkSession
  return EngineArtifacts(
    subject_predictors=_artifact_to_pyspark(spark, result.predictors.subject_predictors),
    subject_scores=_artifact_to_pyspark(spark, result.scores.subject_scores),
    diagnosis_mappings=_artifact_to_pyspark(spark, result.predictors.diagnosis_mappings),
    score_contributions=_artifact_to_pyspark(spark, result.scores.score_contributions),
    validation_issues=_artifact_to_pyspark(
      spark,
      _validation_issues_to_artifact(result.validation_issues),
    ),
  )


def _import_optional_dependency(module_name: str, adapter_name: str) -> object:
  """Import an optional dataframe dependency and raise a clear adapter error if missing."""
  try:
    return importlib.import_module(module_name)
  except ModuleNotFoundError as exc:
    raise RuntimeError(
      f"{adapter_name} requires the optional dependency '{module_name}'.",
    ) from exc


def _artifact_to_pandas(pd: PandasModule, artifact: TableArtifact) -> PandasFrame:
  """Convert a table artifact into a pandas dataframe."""
  return pd.DataFrame(list(artifact.rows), columns=list(artifact.columns))


def _artifact_to_polars(pl: PolarsModule, artifact: TableArtifact) -> PolarsFrame:
  """Convert a table artifact into a polars dataframe."""
  return pl.DataFrame(list(artifact.rows), schema=list(artifact.columns))


def _artifact_to_pyspark(spark: SparkSessionLike, artifact: TableArtifact) -> SparkDataFrame:
  """Convert a table artifact into a Spark dataframe."""
  if artifact.rows:
    return spark.createDataFrame(list(artifact.rows))
  spark_types = _import_optional_dependency("pyspark.sql.types", "_artifact_to_pyspark")
  StringType = getattr(spark_types, "StringType")
  StructField = getattr(spark_types, "StructField")
  StructType = getattr(spark_types, "StructType")

  schema = StructType(
    [StructField(column, StringType(), True) for column in artifact.columns],
  )
  return spark.createDataFrame([], schema)


def _validation_issues_to_artifact(validation_issues: tuple[ValidationIssue, ...]) -> TableArtifact:
  """Convert structured validation issues into a tabular artifact for adapters."""
  return validation_issues_to_artifact(validation_issues)
