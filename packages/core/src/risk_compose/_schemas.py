"""Private Pydantic schemas for boundary validation and coercion."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def parse_identifier(value: object | None) -> str:
  """Normalize identifier-like values to stripped strings."""
  if value is None:
    return ""
  text = str(value).strip()
  return "" if text.lower() == "nan" else text


def parse_int(value: object | None) -> int | None:
  """Parse nullable integer-like values."""
  if value in (None, "", "nan", "None"):
    return None
  try:
    return int(str(value))
  except ValueError:
    try:
      return int(float(str(value)))
    except ValueError:
      return None


def parse_date(value: object | None) -> date | None:
  """Parse supported date inputs into ``date`` values."""
  if value in (None, "", "nan", "None"):
    return None
  if isinstance(value, date) and not isinstance(value, datetime):
    return value
  if isinstance(value, datetime):
    return value.date()
  text = str(value).strip()
  for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
    try:
      return datetime.strptime(text, fmt).date()
    except ValueError:
      continue
  try:
    return date.fromisoformat(text)
  except ValueError:
    return None


def parse_optional_text(value: object | None) -> str | None:
  """Normalize a nullable text value."""
  if value in (None, ""):
    return None
  return str(value)


def parse_string_mapping(value: object | None) -> dict[str, str]:
  """Normalize a nullable mapping into string keys and values."""
  if value is None:
    return {}
  if not isinstance(value, dict):
    raise TypeError("mapping values must be objects")
  return {str(key): str(item) for key, item in value.items()}


class SubjectRowSchema(BaseModel):
  """Canonical subject row shape accepted at the input boundary."""

  model_config = ConfigDict(extra="ignore", frozen=True)

  subject_id: str = ""
  date_of_birth: date | None = None
  sex: int | None = None
  original_reason_entitlement_code: int | None = None
  limited_income_medicaid_flag: int | None = None
  new_enrollee_medicaid_flag: int | None = None
  concurrent_esrd_flag: int | None = None
  medicaid_flag: int | None = None
  full_benefit_dual_flag: int | None = None
  partial_benefit_dual_flag: int | None = None
  long_term_institutional_flag: int | None = None

  @field_validator("subject_id", mode="before")
  @classmethod
  def _validate_subject_id(cls, value: object | None) -> str:
    return parse_identifier(value)

  @field_validator("date_of_birth", mode="before")
  @classmethod
  def _validate_date_of_birth(cls, value: object | None) -> date | None:
    return parse_date(value)

  @field_validator(
    "sex",
    "original_reason_entitlement_code",
    "limited_income_medicaid_flag",
    "new_enrollee_medicaid_flag",
    "concurrent_esrd_flag",
    "medicaid_flag",
    "full_benefit_dual_flag",
    "partial_benefit_dual_flag",
    "long_term_institutional_flag",
    mode="before",
  )
  @classmethod
  def _validate_nullable_int(cls, value: object | None) -> int | None:
    return parse_int(value)


class DiagnosisRowSchema(BaseModel):
  """Canonical diagnosis row shape accepted at the input boundary."""

  model_config = ConfigDict(extra="ignore", frozen=True)

  subject_id: str = ""
  icd10_code: str = ""
  service_date: date | None = None
  claim_id: str | None = None
  source: str | None = None
  diagnosis_sequence: int | None = None
  present_on_admission: str | None = None

  @field_validator("subject_id", mode="before")
  @classmethod
  def _validate_subject_id(cls, value: object | None) -> str:
    return parse_identifier(value)

  @field_validator("icd10_code", mode="before")
  @classmethod
  def _validate_icd10_code(cls, value: object | None) -> str:
    return parse_identifier(value).upper()

  @field_validator("service_date", mode="before")
  @classmethod
  def _validate_service_date(cls, value: object | None) -> date | None:
    return parse_date(value)

  @field_validator("claim_id", "source", mode="before")
  @classmethod
  def _validate_optional_text(cls, value: object | None) -> str | None:
    return parse_optional_text(value)

  @field_validator("diagnosis_sequence", mode="before")
  @classmethod
  def _validate_diagnosis_sequence(cls, value: object | None) -> int | None:
    return parse_int(value)

  @field_validator("present_on_admission", mode="before")
  @classmethod
  def _validate_present_on_admission(cls, value: object | None) -> str | None:
    text = parse_optional_text(value)
    return text.upper() if text is not None else None


class FlatFileSourceEntrySchema(BaseModel):
  """One flat-file source entry declared in the CLI manifest."""

  model_config = ConfigDict(extra="ignore", frozen=True)

  path: str
  columns: dict[str, str] = Field(default_factory=dict)
  filter: str | None = None

  @field_validator("path", mode="before")
  @classmethod
  def _validate_path(cls, value: object | None) -> str:
    text = parse_optional_text(value)
    if text is None:
      raise ValueError("path must be a non-empty string")
    return text

  @field_validator("columns", mode="before")
  @classmethod
  def _validate_columns(cls, value: object | None) -> dict[str, str]:
    return parse_string_mapping(value)

  @field_validator("filter", mode="before")
  @classmethod
  def _validate_filter(cls, value: object | None) -> str | None:
    return parse_optional_text(value)


class DatabaseSourceEntrySchema(BaseModel):
  """One database source entry declared in the CLI manifest."""

  model_config = ConfigDict(extra="ignore", frozen=True)

  locator: str
  schema_name: str | None = None
  columns: dict[str, str] = Field(default_factory=dict)
  filter: str | None = None

  @field_validator("locator", mode="before")
  @classmethod
  def _validate_locator(cls, value: object | None) -> str:
    text = parse_optional_text(value)
    if text is None:
      raise ValueError("locator must be a non-empty string")
    return text

  @field_validator("schema_name", "filter", mode="before")
  @classmethod
  def _validate_optional_text(cls, value: object | None) -> str | None:
    return parse_optional_text(value)

  @field_validator("columns", mode="before")
  @classmethod
  def _validate_columns(cls, value: object | None) -> dict[str, str]:
    return parse_string_mapping(value)
