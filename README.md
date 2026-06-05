# risk-compose

`risk-compose` is a typed, deterministic Python library designed for risk-adjustment scoring using subject and diagnosis data. It packages official risk-adjustment models—such as CMS-HCC, ESRD, RxHCC, and AHRQ Elixhauser—into a modern, lightweight developer interface with built-in validation and explainability.

---

## What is risk-compose?

`risk-compose` is a developer-first risk-adjustment library built to translate complex clinical coding and demographic inputs into accurate Risk Adjustment Factors (RAF) and comorbidity indices. It operates entirely deterministically, separating raw input parsing, validation, core scoring logic, and explainability workflows into modular, testable surfaces inside one installable package.

The project ships one installable package with all user-facing surfaces:

| Surface | Purpose |
| --- | --- |
| Python API | Core scoring, data validation, packaged model coefficients, and dataframe adapters. |
| `risk-compose` | Command-line scoring, source data preparation, and subject explanation workflows. |
| `risk-compose-tui` | Terminal review interface for interactive visual exploration of subject scores. |
| `risk-compose-gui` | Streamlit-based web interface for browser-based interactive scoring and tracing. |

---

## Key User Clusters & Use Cases

`risk-compose` serves three main types of users, each with distinct workflow requirements:

### 1. Data Engineers & Data Scientists (Scale & Automation)
* **Scenario**: Building high-throughput risk-scoring pipelines to process Medicare/Medicaid diagnostic claims for millions of beneficiaries.
* **Use Case**: Integrating scoring directly into data pipelines using **Pandas**, **Polars**, or **PySpark** via lazy, engine-native dataframe adapters that avoid slow row-by-row serialization loops.

### 2. Clinical Informaticians & Quality Auditors (Traceability & Quality)
* **Scenario**: Reviewing and auditing coded diagnoses to verify risk score calculations before submitting them for compliance or reimbursement.
* **Use Case**: Using the **TUI** or **GUI** review applications to trace how individual diagnostic codes (ICD-10-CM) map to Hierarchical Condition Categories (HCCs), and identifying exactly which conditions drove the final Risk Adjustment Factor (RAF).

### 3. Application & Product Developers (Integration)
* **Scenario**: Embedding deterministic risk scoring, Elixhauser comorbidity indices, or eligibility validation directly into software applications, EHR tools, or digital health platforms.
* **Use Case**: Calling a lightweight, type-safe Python API that runs entirely locally, requires zero network calls, and executes with minimal resource overhead.

---

## Usual Pain Points in Risk Adjustment

Organizations running risk-adjustment workflows typically struggle with:
* **The "Black Box" Problem**: Monolithic scoring engines or legacy scripts provide a final score but hide the step-by-step logic. Diagnosing *why* a score is incorrect or *which* diagnosis triggered an HCC is extremely manual and time-consuming.
* **Legacy Runtime Overhead**: Official risk-adjustment software frequently relies on expensive proprietary tools (like SAS) or heavy database structures, making local testing and agile development difficult.
* **Silent Data Validation Failures**: Subtle data problems—such as mismatched demographic codes, invalid/unsupported ICD-10 codes, or missing Present on Admission (POA) indicators—silently corrupt the final score without warning.
* **Scalability Bottlenecks**: Scaling traditional risk models to run across massive modern databases or distributed computing frameworks requires rewriting scoring rules from scratch, risking mathematical deviations from official models.

---

## How risk-compose Addresses Them

`risk-compose` was built from the ground up to solve these exact challenges:

* **Unmatched Explainability & Tracing**: Rather than returning a single score, every execution produces comprehensive, structured artifacts showing demographic predictors, hierarchy results, interaction terms, diagnosis-to-category mappings, and individual factor contributions.
* **Lightweight & Dependency-Free Core**: No SAS license or external databases are required. A complete `pip install` sets up a deterministic local engine powered by pre-compiled, bundled runtime CSV data.
* **Built-in Validation & Lineage Engine**: Operates in both **strict** mode (to fail early on data anomalies) and **non-strict** mode (to report validation issues as structured CSV tables). It detects invalid diagnostic codes, incorrect demographic boundaries, and input anomalies automatically.
* **Native Dataframe Adapters**: Shipped with lazy adapters for Pandas, Polars, and PySpark. Scoring logic scales cleanly to massive datasets while preserving strict mathematical parity with official reference models.

---

## Other Helpful Information

### Supported Models (Version 1.0.2)
The package includes packaged runtime artifacts for:
* **CMS-HCC 2026**: `cms_hcc_v22_2026`, `cms_hcc_v28_2026`
* **ESRD 2026**: `esrd_v21_2026`, `esrd_v24_2026`
* **RxHCC 2026**: `rxhcc_v8_t_2026`, `rxhcc_v8_x_2026`
* **AHRQ Elixhauser CMR v2026.1**: `elixhauser_v2026_1`

### Installation

Python 3.11 or newer is required.

#### Using Standard `pip`

```bash
pip install risk-compose
```

#### Using `uv`

For faster installations, virtual environment management, or running tools directly from a local workspace clone:

```bash
# Fast pip-equivalent install
uv pip install risk-compose

# Run the bundled package directly without a global/system install
uv run --package risk-compose risk-compose --help
```

#### Repo-Local Development (Cloned Workspace)

If you have cloned the source repository for development:

```bash
# Synchronize all workspace packages and dev groups
uv sync --group dev

# Execute package entry points directly
uv run --package risk-compose risk-compose --help
uv run --package risk-compose risk-compose-tui --help
uv run --package risk-compose risk-compose-gui --help
```

### Quick Commands

**Command Line Batch Scoring**:
```bash
risk-compose score \
  --subjects subjects.csv \
  --diagnoses diagnoses.csv \
  --output-dir out/score \
  --model-version cms_hcc_v28_2026
```

**Python API Usage**:
```python
from datetime import date
from risk_compose import DiagnosisRecord, ScoringRequest, SubjectRecord, score_subjects

request = ScoringRequest(
  subjects=(
    SubjectRecord(
      subject_id="B1",
      date_of_birth=date(1953, 5, 1),
      sex=2,
      original_reason_entitlement_code=0,
    ),
  ),
  diagnoses=(DiagnosisRecord("B1", "E119"),),
)

result = score_subjects(request)
print(result.scores.subject_scores.rows[0])
```

### Documentation Guide
* [`QUICKSTART.md`](QUICKSTART.md): Quick installation and your first scoring run.
* [`MANUAL.md`](MANUAL.md): Complete guide to Python APIs, CLI, dataframe adapters, and review frontends.
* [`CHANGELOG.md`](CHANGELOG.md): History of package updates, features, and version checkpoints.

### Data Attribution & Disclaimer
This package includes curated runtime tables derived from CMS and AHRQ public release artifacts. Users must review upstream CMS and AHRQ license terms before redistributing derived data or using outputs in regulated workflows.

`risk-compose` is an independent open-source library and is not affiliated with, endorsed by, or associated with CMS or AHRQ.
