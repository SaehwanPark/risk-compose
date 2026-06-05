"""Shared typing helpers for internal package use."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Protocol, TypeAlias

ArtifactValue: TypeAlias = str | int | float | bool | date | None
ArtifactRow: TypeAlias = dict[str, ArtifactValue]
ArtifactRowMapping: TypeAlias = Mapping[str, ArtifactValue]
InputRow: TypeAlias = dict[str, object]
InputRowMapping: TypeAlias = Mapping[str, object]
JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class TuiRunner(Protocol):
  """Callable contract for the lazily imported TUI runner."""

  def __call__(self, *, bundle_dir: Path | None = None) -> int:
    """Launch the TUI for an optional preloaded bundle."""
    ...


class PandasFrame(Protocol):
  """Minimal pandas-like dataframe contract used by the adapter layer."""

  def to_dict(self, *, orient: str) -> list[InputRow]:
    """Return row-oriented dictionaries."""
    ...


class PandasModule(Protocol):
  """Minimal pandas module surface required by the adapter layer."""

  def DataFrame(
    self,
    data: Sequence[Mapping[str, object]],
    columns: list[str],
  ) -> PandasFrame:
    """Construct a dataframe from row dictionaries."""
    ...


class PolarsFrame(Protocol):
  """Minimal polars-like dataframe contract used by the adapter layer."""

  def to_dicts(self) -> list[InputRow]:
    """Return row-oriented dictionaries."""
    ...


class PolarsModule(Protocol):
  """Minimal polars module surface required by the adapter layer."""

  def DataFrame(
    self,
    data: Sequence[Mapping[str, object]],
    schema: list[str],
  ) -> PolarsFrame:
    """Construct a dataframe from row dictionaries."""
    ...


class SparkRow(Protocol):
  """Minimal Spark row surface required by the adapter layer."""

  def asDict(self, recursive: bool = False) -> InputRow:
    """Return a row as a dictionary."""
    ...


class SparkSessionLike(Protocol):
  """Minimal Spark session surface required by the adapter layer."""

  def createDataFrame(
    self,
    data: Sequence[Mapping[str, object]],
    schema: object | None = None,
  ) -> SparkDataFrame:
    """Construct a Spark dataframe."""
    ...


class SparkDataFrame(Protocol):
  """Minimal Spark dataframe surface required by the adapter layer."""

  @property
  def sparkSession(self) -> SparkSessionLike:
    """Return the owning Spark session."""
    ...

  def toLocalIterator(self) -> Iterator[SparkRow]:
    """Iterate over Spark rows."""
    ...
