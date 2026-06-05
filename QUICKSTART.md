# Quickstart

This guide gets you from installation to a first score run.

## Install

```bash
pip install risk-compose
```

## Prepare Input Files

`subjects.csv` can use canonical `subject` names or supported legacy CMS-style aliases:

```csv
subject_id,date_of_birth,sex,original_reason_entitlement_code
B1,1953-05-01,2,0
```

`diagnoses.csv` needs one accepted diagnosis observation per row:

```csv
subject_id,icd10_code
B1,E119
B1,I509
```

## Run Scoring

```bash
risk-compose score \
  --subjects subjects.csv \
  --diagnoses diagnoses.csv \
  --output-dir out/score
```

The default model is `cms_hcc_v28_2026`.

To select another model:

```bash
risk-compose score \
  --subjects subjects.csv \
  --diagnoses diagnoses.csv \
  --output-dir out/elixhauser \
  --model-version elixhauser_v2026_1
```

## Inspect Outputs

Scoring writes:

- `subject_predictors.csv`
- `subject_scores.csv`
- `diagnosis_mappings.csv`
- `score_contributions.csv`
- `validation_issues.csv`

Run with `--strict` when validation issues should fail the command instead of being reported as artifacts.

## Explain One Subject

```bash
risk-compose explain-subject \
  --subjects subjects.csv \
  --diagnoses diagnoses.csv \
  --subject-id B1 \
  --output-dir out/explain-B1
```

## Use Python

```python
from risk_compose import DEFAULT_MODEL_VERSION, get_model_spec

print(DEFAULT_MODEL_VERSION)
print(get_model_spec("cms_hcc_v28_2026").model_version)
```

See `MANUAL.md` for the full API, CLI, source-preparation, and review-frontend guide.
