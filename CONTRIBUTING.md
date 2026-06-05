# Contributing

`risk-compose` accepts focused changes that preserve deterministic scoring behavior,
typed public dataclasses, and clear validation boundaries.

Before opening a pull request:

- Run `uv run --all-packages pytest`.
- Run `uv run --all-packages mypy packages tests`.
- Run `uv run --all-packages basedpyright`.
- Update user-facing docs when public behavior changes.

Do not commit credentials, PyPI tokens, generated build artifacts, or private
development harness files.
