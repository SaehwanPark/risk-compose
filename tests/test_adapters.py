from __future__ import annotations

import importlib
from typing import Any

import pytest

import risk_compose.adapters as adapters


@pytest.mark.parametrize(
  ("module_name", "adapter_name"),
  (
    ("pandas", "score_pandas"),
    ("polars", "score_polars"),
    ("pyspark", "score_pyspark"),
  ),
)
def test_optional_dependency_errors_are_clear(
  monkeypatch: pytest.MonkeyPatch,
  module_name: str,
  adapter_name: str,
) -> None:
  def fake_import(name: str) -> Any:
    raise ModuleNotFoundError(name)

  monkeypatch.setattr(importlib, "import_module", fake_import)
  with pytest.raises(RuntimeError, match=module_name):
    adapters._import_optional_dependency(module_name, adapter_name)
