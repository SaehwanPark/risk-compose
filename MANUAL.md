# risk-compose User Manual

## Overview

`risk-compose` scores canonical subject and diagnosis data against packaged risk-adjustment model artifacts. The core library is deterministic: it receives typed inputs, applies validation, generates predictors, applies hierarchy and interaction logic, and emits tabular artifacts.

## Package Surfaces

- `risk-compose`: bundled Python package, packaged runtime data, and CLI.
- `risk-compose-tui`: bundled terminal review app.
- `risk-compose-gui`: bundled Streamlit review app.

Install `risk-compose` once for all user-facing surfaces. Dataframe engines remain optional.

## Model Versions

Supported `model_version` values in `1.0.2`:

- `cms_hcc_v22_2026`
- `cms_hcc_v28_2026`
- `esrd_v21_2026`
- `esrd_v24_2026`
- `rxhcc_v8_t_2026`
- `rxhcc_v8_x_2026`
- `elixhauser_v2026_1`

The default is `cms_hcc_v28_2026`.

## Input Concepts

`SubjectRecord` represents the scored person or entity. It includes a stable `subject_id` and model-specific fields when needed.

`DiagnosisRecord` represents one accepted diagnosis observation for a subject. It includes `subject_id`, `icd10_code`, and optional details such as service date, diagnosis sequence, and present-on-admission indicator.

`ScoringRequest` bundles subjects, diagnoses, and scoring options.

## CLI Workflows

### Score Explicit Inputs

```bash
risk-compose score \
  --subjects subjects.csv \
  --diagnoses diagnoses.csv \
  --output-dir out/score
```

Add `--model-version` to choose a model. Add `--strict` to convert blocking validation issues into a nonzero exit.

### Prepare Source Inputs

`prepare-source` converts a declared CMS source manifest into canonical scoring inputs. This workflow remains CMS-HCC-oriented in this release.

```bash
risk-compose prepare-source \
  --source-manifest source-manifest.json \
  --output-dir out/prepare
```

### Prepare And Score

```bash
risk-compose score-source \
  --source-manifest source-manifest.json \
  --output-dir out/score-source
```

### Explain One Subject

```bash
risk-compose explain-subject \
  --subjects subjects.csv \
  --diagnoses diagnoses.csv \
  --subject-id B1 \
  --output-dir out/explain
```

## Output Artifacts

- `subject_predictors.csv`: generated demographic, diagnosis, hierarchy, interaction, and model-specific predictors.
- `subject_scores.csv`: score totals by subject and score family.
- `diagnosis_mappings.csv`: diagnosis-to-category mapping results.
- `score_contributions.csv`: factor-level contributions to final scores.
- `validation_issues.csv`: non-strict validation findings.

Explanation bundles add subject-level hierarchy, interaction, and RAF total artifacts.

## Python API

```python
from risk_compose import ScoringOptions, ScoringRequest, score_subjects

result = score_subjects(
  ScoringRequest(
    subjects=subjects,
    diagnoses=diagnoses,
    options=ScoringOptions(model_version="cms_hcc_v28_2026"),
  )
)
```

Use `generate_predictors` for intermediate predictors and `generate_scores` when predictors are already available.

## Dataframe Adapters

The core package exposes lazy dataframe adapters:

- `score_pandas`
- `score_polars`
- `score_pyspark`

Install the matching engine dependency or package extra before using an adapter.

## Review Frontends

Launch the terminal interface:

```bash
risk-compose-tui
```

Launch the browser interface:

```bash
risk-compose-gui
```

The CLI aliases `risk-compose tui` and `risk-compose gui` can also launch the review apps.

## Validation

Non-strict workflows emit validation artifacts. Strict workflows fail when blocking issues are found. Prefer strict mode for production pipelines and non-strict mode while onboarding data feeds.

## Versioning

- `1.0.0`: stable checkpoint for CMS-family HCC, ESRD, and RxHCC scoring.
- `1.0.2`: Elixhauser extension release.

Patch releases should preserve public input and artifact shapes unless the changelog explicitly says otherwise.

## Provenance And Limitations

Runtime tables are curated from official CMS and AHRQ materials. The package is not a substitute for official regulatory guidance, contract-specific policy review, or independent validation in production environments.
