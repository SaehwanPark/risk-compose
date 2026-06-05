# Install From GitHub

These examples use placeholders:

- `OWNER/REPO`: the public GitHub repository
- `REF`: a branch, tag, or commit SHA

Replace both placeholders before running the commands.

## Install The Bundle

Use this for Python API scoring, source preparation, validation, review helpers, packaged runtime data, dataframe adapters, CLI workflows, and the bundled TUI/GUI frontends.

```bash
pip install \
  "risk-compose @ git+https://github.com/OWNER/REPO.git@REF"
```

Smoke test:

```bash
risk-compose --help
risk-compose-tui --help
risk-compose-gui --help
python -c "import risk_compose; print(risk_compose.DEFAULT_MODEL_VERSION)"
```

## Notes

- The public repository root is the Python project root.
- `risk-compose` provides the batch/source-manifest CLI.
- `risk-compose-tui` and `risk-compose-gui` are standalone launchers and also work through `risk-compose tui` and `risk-compose gui`.
- Once published to an index, the GitHub URL can be replaced with `pip install risk-compose`.
