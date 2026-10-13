# Sasti Dawai ML Subsystem — Revised Implementation Plan

**Version:** 1.1 (Phase 0.1 Plan Correction)  
**Date:** 13 October 2026  
**Status:** Architecture Review Approved / Pending User Sign-off  
**Parent PRD:** `Sasti-Dawai-PRD.pdf` v1.0  
**ML PRD:** `Sasti_Dawai_ML_PRD.pdf` v1.0  
**Core Directive:** *AI reads the medicine pack. Verified data checks what it read. Deterministic code decides whether a match is safe.*

---

## 1. Revised Phase Breakdown and Ordering

The implementation is partitioned into small, independently verifiable phases. Each phase builds strictly on deterministic guarantees established in preceding phases.

```
[Phase 1A: Scaffolding, Schemas & Contracts]
                    │
                    ▼
[Phase 1B: Pure Normalization & Canonical Representations]
                    │
                    ▼
[Phase 1C: Deterministic Matcher & Safety Tests]
                    │
                    ▼
[Phase 1D: Catalogue ETL, Eligibility & Provenance]
                    │
                    ▼
[Phase 1E: Candidate Resolver & Retrieval Evaluation]
                    │
                    ▼
[Phase 1F: Image Quality Gate & Extractor Interface]
                    │
                    ▼
[Phase 1G: OCR, Evidence Reconciliation & Safety Gates]
                    │
                    ▼
[Phase 1H: API Orchestration & Integration]
                    │
                    ▼
[Phase 1I: Golden-Set Evaluation & Release Readiness]
```

### Phase Rationale and Sequencing
1. **Phase 1A (Scaffolding, Schemas, Contracts)**: Defines the formal boundary contracts (Pydantic V2) for all data entering and leaving the system before any logic exists.
2. **Phase 1B (Pure Normalization)**: Standardizes units (e.g., `g` to `mg`, `mcg` to `mg`), dosage forms, and release mechanisms into pure immutable types. Neither matching nor ETL can function safely without deterministic normalization.
3. **Phase 1C (Deterministic Matcher & Safety Tests)**: Implements the 5-dimension equivalence engine on synthetic, hand-crafted test fixtures *before* touching noisy real-world catalogue data. Proves the safety boundary is airtight.
4. **Phase 1D (Catalogue ETL, Eligibility & Provenance)**: Parses real datasets (Jan Aushadhi 2,439 rows; Indian Medicine records), enforces provenance metadata, applies quarantine filters, and populates the clean local catalogue.
5. **Phase 1E (Candidate Resolver & Retrieval Evaluation)**: Implements exact + RapidFuzz lexical candidate retrieval against the curated catalogue and measures top-1/top-3 candidate accuracy.
6. **Phase 1F (Image Quality Checks & Extractor Interface)**: Implements OpenCV image heuristics (blur, darkness, glare) and a provider-independent VLM extraction adapter (with deterministic mock for offline testing).
7. **Phase 1G (OCR, Evidence Reconciliation & Safety Gate)**: Fuses VLM readings, OCR fallback, and catalogue evidence into explicit workflow states. Enforces the rule that evidence conflicts block matching.
8. **Phase 1H (API Orchestration & Integration)**: Integrates the components into the FastAPI application endpoints (`/v1/scan`, `/v1/match`, `/v1/medicines/search`, `/health`).
9. **Phase 1I (Golden-Set Evaluation & Release Readiness)**: Evaluates end-to-end performance on the golden evaluation set, enforces zero-false-positive release criteria, and outputs `MODEL_CARD.md` and `EVALUATION_REPORT.md`.

---

## 2. Separation of Scan Workflow State vs Match Tier

Workflow state and clinical equivalence are two fundamentally distinct concepts that must **never** be conflated:
- **Scan Workflow State**: Describes the health, completeness, and human verification status of the *perception and input pipeline*.
- **Match Tier**: Represents the *deterministic medical equivalence relationship* between a verified scanned product and a verified catalogue product.

### 2.1 Scan Workflow States
1. `REJECT_IMAGE`: The submitted input is invalid, corrupt, or not a medicine pack. Processing halts immediately.
2. `RETAKE_REQUIRED`: Image quality heuristics detected severe blur, darkness, or glare that obscures readable details. Actionable guidance returned to user.
3. `EXTRACTION_INCOMPLETE`: Critical fields (e.g., composition, strength) could not be extracted from visible text.
4. `NEEDS_USER_CONFIRMATION`: Extraction succeeded, but model confidence is below threshold, OCR disagrees with VLM, or brand/composition conflicts require patient/caregiver confirmation.
5. `READY_FOR_MATCHING`: All critical fields are extracted, cross-checked, verified (or user-confirmed), and cleanly normalized. Eligible to be evaluated by the deterministic matcher.
6. `RECOVERABLE_ERROR`: Upstream network timeout, malformed provider payload, or system error. Returns a safe error response with manual search fallback.

### 2.2 Match Tiers
1. `EXACT`: Full 5-dimension equivalence confirmed against a verified catalogue record. Verified price comparison and savings calculation permitted.
2. `CLOSE`: Related active ingredient, but release type differs (e.g., SR vs IR) or different strength/dosage form. **Never considered an equivalent substitute; never used to compute savings.** Displays a prominent clinical caution banner.
3. `NONE`: No verified generic candidate exists, brand could not be verified, or essential attributes are missing.

### 2.3 Valid State & Tier Combinations
| Scan Workflow State | Permitted Match Tier | Behavior / Description |
|---|---|---|
| `REJECT_IMAGE` | `None` (no match run) | Early abort; user asked for a valid medicine pack photo. |
| `RETAKE_REQUIRED` | `None` (no match run) | Early abort; user receives framing/lighting guidance. |
| `EXTRACTION_INCOMPLETE` | `None` (no match run) | Cannot proceed to matching without critical fields. |
| `NEEDS_USER_CONFIRMATION` | `None` (pending confirmation) | Candidate preview may be shown, but **no** `EXACT` tier or savings can be awarded until the user confirms highlighted fields. |
| `READY_FOR_MATCHING` | `EXACT` | Evaluated by rules engine: all 5 canonical dimensions match identical records. Savings displayed. |
| `READY_FOR_MATCHING` | `CLOSE` | Evaluated by rules engine: composition matches but release type or strength differs. Savings suppressed. |
| `READY_FOR_MATCHING` | `NONE` | Evaluated by rules engine: no matching Jan Aushadhi generic exists. Honest empty state displayed. |
| `RECOVERABLE_ERROR` | `None` (no match run) | Graceful failure; fallback to manual search offered. |

> **Critical Safety Invariant**: A workflow state of `READY_FOR_MATCHING` does not imply `EXACT`. Only the deterministic rule engine can award `EXACT`.

---

## 3. Catalogue Eligibility, Quarantine, and Provenance

Raw CSV datasets are noisy external inputs, not verified truths. The ETL system treats them with zero implicit trust.

### 3.1 Provenance Tracking
Every loaded catalogue record must retain immutable provenance:
- `source_name`: Exact source (e.g., `PMBI_JAN_AUSHADHI`, `INDIAN_MEDICINE_DATASET`).
- `source_row_id`: Primary key or row index in the raw file.
- `raw_text`: Unmodified generic/brand name and composition string as published in source.
- `retrieval_date`: Timestamp when the dataset was downloaded.
- `price_date`: Date when the price was verified/published. (Never claim a price is current without verified publication date).
- `raw_checksum`: SHA-256 of the source file to guarantee reproducibility.

### 3.2 Quarantine Criteria (Ineligible for Matching)
Any catalogue row meeting any of the following criteria is automatically quarantined into a `quarantined_records` table and excluded from `EXACT` matching:
1. **Ambiguous Salt Parsing**: Multi-salt strings containing unrecognized separators or ambiguous punctuation where ingredient boundaries cannot be deterministically resolved.
2. **Missing Strength or Unit**: Missing numerical strength or missing unit for any active ingredient.
3. **Unsupported Unit Representation**: Non-standard or unconvertible units (e.g., ambiguous drops, unspecified parts).
4. **Unknown Dosage Form**: Product form cannot be mapped to the controlled dosage form vocabulary.
5. **Missing or Ambiguous Release Type**: Oral solid forms where release profile cannot be definitively established as immediate or modified release.
6. **Discontinued Records**: Rows where `Is_discontinued = TRUE` (preserved as reference but ineligible for active savings comparison).
7. **Synthetic Fixtures**: Test fixtures are isolated in `tests/fixtures/` and prohibited by build checks from ever entering production databases.

---

## 4. Clinical Safety & NTI (Narrow Therapeutic Index) Policy

### 4.1 NTI Drug Handling: BLOCKED Status
- The parental PRD mentions NTI drugs (e.g., Levothyroxine, Warfarin, Lithium, Digoxin, Phenytoin, Carbamazepine).
- **Rule**: Antigravity ML Engineer must **not** invent or compile an ad-hoc NTI list without clinical consensus.
- **Current State**: The automated NTI classification feature is marked **`BLOCKED`** pending an authoritative, clinician-signed reference dataset.
- **Interim Safety Fallback**: The deterministic matcher will support an explicit, empty-by-default NTI registry schema. In the absence of a verified clinical source, the system defaults to strict fail-safe behavior: all results display the mandatory doctor disclaimer, and no substitution or therapeutic equivalence is ever claimed.

### 4.2 Prohibited Clinical Claims
- The system is purely an identification and price-comparison tool.
- Prohibited outputs:
  - No dosage recommendations or dosage adjustment suggestions (e.g., never suggest "take two 250mg tablets for 500mg").
  - No claims of bioequivalence, clinical interchangeability, or therapeutic superiority.
  - Mandatory disclaimer appended by code to every output: **"Always confirm with your doctor or pharmacist."**

---

## 5. Tightened Deterministic EXACT Match Specification

A candidate generic product qualifies as an `EXACT` match if and only if **all five** canonical dimensions are verified identical:

1. **Active Salt Set**:
   - The set of active moieties must be identical.
   - For combination drugs ($N \ge 2$), every single active ingredient in the brand must match an active ingredient in the generic, with zero surplus or omitted ingredients.
2. **Normalized Strength and Unit**:
   - For every ingredient in the active salt set, normalized numerical strength and unit must match identically (e.g., $1\text{ g} \equiv 1000\text{ mg}$).
   - Denominators must match (e.g., $\text{mg/tablet}$ cannot be matched against $\text{mg/5 ml}$ without an explicit validated conversion).
3. **Dosage Form**:
   - Both products must share the identical controlled dosage form (`tablet`, `capsule`, `syrup`, `suspension`, `injection`, `gel`, `drops`, `inhaler`).
4. **Release Type**:
   - Release profile must be identical (`IR`, `SR`, `ER`, `XR`, `DR/EC`, `MR`, `ODT`, `chewable`, `dispersible`).
   - Mismatch between Immediate Release (IR) and Sustained/Extended Release (SR/ER) **immediately downgrades the result to CLOSE or NONE**.
5. **Route of Administration**:
   - Routes must be identical (`oral`, `topical`, `ophthalmic`, `parenteral`).

### Safety Boundaries on Non-EXACT Tiers
- **`CLOSE`**: Used strictly for transparency when a related formulation exists (e.g., same salt but different release mechanism or strength).
  - Must display: *"Similar, not identical. Ask your doctor before switching."*
  - **Must never display savings calculations or monthly rupees saved.**
- **`NONE`**: Used when no identical or close match exists.
  - Must display: *"No cheaper exact match found."*
  - **Never invent or guess a substitute.**

---

## 6. Lean Architecture and Infrastructure Decisions

To ensure maximum reliability and maintainability for the hackathon MVP:
1. **Local Storage**: Use SQLite for local development and unit/integration testing. SQLite eliminates Docker/cloud setup hurdles and guarantees reproducible CI execution while supporting the exact same SQLAlchemy schema.
2. **PostgreSQL/pgvector**: Deferred. The relational schema is PostgreSQL-compatible, but pgvector will only be provisioned if evaluation demonstrates that lexical retrieval fails to achieve target candidate recall.
3. **Lexical Retrieval Baseline**: Pure RapidFuzz (token sort ratio + partial ratio) combined with exact normalized indexing. This avoids heavy external dependencies while delivering sub-millisecond retrieval on the 2,439 Jan Aushadhi records.
4. **No Premature Model Training**: No model fine-tuning or vector embeddings in Phase 1. Standard pretrained vision-language model APIs with structured JSON output and temperature 0.0 meet the perceptual requirements.

---

## 7. Detailed Phase Breakdown and Definition of Done (DoD)

### Phase 1A: Project Scaffolding, Schemas, and API Contract
- **Objective**: Establish the directory layout and implement typed Pydantic V2 schemas for extraction, canonical representation, and API contracts.
- **Files to Create**:
  - `ml/schemas/extraction.py` (VLM extraction models, bounding/confidence schemas)
  - `ml/schemas/canonical.py` (CanonicalProduct, SaltMoiety, StrengthValue)
  - `ml/schemas/matcher.py` (MatchRequest, MatchResult, TierEnum, WorkflowStateEnum)
  - `ml/schemas/quality.py` (ImageQualityReport, QualityGateStatus)
  - `.env.example` (Placeholder environment configuration)
  - `tests/test_schema.py` (Pydantic validation tests)
- **Definition of Done**:
  - Schemas validate correct and malformed payloads without errors.
  - Missing critical fields cleanly validate to `None` / fail validation as configured.
  - `pytest tests/test_schema.py` passes 100%.

### Phase 1B: Pure Normalization and Canonical Field Representations
- **Objective**: Implement unit conversions, dosage form normalization, release type parsing, and canonical string sanitation.
- **Files to Create**:
  - `ml/resolver/normalize.py` (Unit conversions: mg/g/mcg, release marker extraction, form mapping)
  - `tests/test_normalization.py` (Table-driven normalization tests)
- **Definition of Done**:
  - `1000 mg` standardizes to `1 g` equivalent; `0.5 mg` standardizes to `500 mcg`.
  - Combinations are order-independent (e.g., `{A: 500, B: 2}` equals `{B: 2, A: 500}`).
  - `pytest tests/test_normalization.py` passes 100%.

### Phase 1C: Deterministic EXACT/CLOSE/NONE Matcher & Safety Tests
- **Objective**: Implement the 5-dimension deterministic rule engine on synthetic fixtures.
- **Files to Create**:
  - `ml/safety/matcher.py` (Core matching logic, unit price calculation, savings calculator)
  - `ml/safety/boundaries.py` (Invariants enforcement, clinical disclaimer injector)
  - `tests/fixtures/synthetic_medicines.py` (Isolated, clearly marked mock products)
  - `tests/test_exact_match_boundary.py` (Edge cases: SR vs IR, combination differences, strength mismatch)
- **Definition of Done**:
  - Mismatched release type never returns `EXACT`.
  - Mismatched strength never returns `EXACT`.
  - Combination with missing salt never returns `EXACT`.
  - `CLOSE` tier never generates monthly savings numbers.
  - `pytest tests/test_exact_match_boundary.py` passes 100%.

### Phase 1D: Catalogue ETL, Eligibility Rules, and Provenance
- **Objective**: Process the 2,439 Jan Aushadhi records into a verified SQLite/SQLAlchemy catalogue.
- **Files to Create**:
  - `ml/data/etl.py` (Defensive CSV parser, provenance stamper, quarantine engine)
  - `ml/data/models.py` (SQLAlchemy models: Product, ProductSalt, QuarantinedRecord)
  - `ml/data/database.py` (Database connection and session factory)
  - `tests/test_catalogue_etl.py` (ETL integrity tests, checksum validation, quarantine checks)
- **Definition of Done**:
  - All 2,439 Jan Aushadhi rows parsed idempotently; ambiguous rows successfully quarantined.
  - Provenance (source, raw row, price date, SHA-256) attached to every record.
  - `pytest tests/test_catalogue_etl.py` passes 100%.

### Phase 1E: Candidate Resolver and Retrieval Evaluation
- **Objective**: Implement exact lookup and RapidFuzz candidate retrieval to resolve extracted brand names to catalogue entities.
- **Files to Create**:
  - `ml/resolver/candidates.py` (Candidate retrieval and ranking engine)
  - `tests/test_resolver.py` (Fuzzy spelling variance, whitespace/casing tolerance)
- **Definition of Done**:
  - Brand name resolution achieves top-1 match on exact names and tolerant match on common OCR noise.
  - Disputed or ambiguous candidates flagged for confirmation.
  - `pytest tests/test_resolver.py` passes 100%.

### Phase 1F: Image Quality Checks and Extraction-Provider Interface
- **Objective**: Implement OpenCV quality heuristics (blur, darkness, glare) and a provider-independent VLM extractor abstraction.
- **Files to Create**:
  - `ml/vision/quality.py` (Laplacian variance blur check, intensity histogram, glare estimation)
  - `ml/vision/extractor.py` (Abstract extractor interface, Gemini/Claude adapter, offline MockExtractor)
  - `ml/prompts/extract_medicine.txt` (Versioned system prompt for structured extraction)
  - `tests/test_quality_gate.py` (Quality check evaluations)
  - `tests/test_extractor_mock.py` (Mock extractor behavior tests)
- **Definition of Done**:
  - Low-quality images trigger `RETAKE_REQUIRED` with plain-language advice.
  - Offline MockExtractor returns valid structured JSON adhering to the schema.
  - `pytest tests/test_quality_gate.py tests/test_extractor_mock.py` passes 100%.

### Phase 1G: OCR, Evidence Reconciliation, and Safety Gate Integration
- **Objective**: Implement OCR fallback adapter and fuse multiple evidence streams into explicit workflow states.
- **Files to Create**:
  - `ml/vision/ocr.py` (OCR fallback interface)
  - `ml/safety/gates.py` (Evidence reconciliation: VLM vs OCR vs Catalogue cross-check)
  - `tests/test_safety_gates.py` (Discrepancy detection: VLM says 500mg, OCR says 250mg -> triggers `NEEDS_USER_CONFIRMATION`)
- **Definition of Done**:
  - Disagreements between VLM and OCR halt automatic progression.
  - Workflow state machine enforces zero unconfirmed transitions.
  - `pytest tests/test_safety_gates.py` passes 100%.

### Phase 1H: API Orchestration and Integration
- **Objective**: Wire all components into the FastAPI application with structured error handling and security controls.
- **Files to Create**:
  - `ml/app/main.py` (FastAPI app factory, CORS, exception handlers)
  - `ml/app/api/routes_scan.py` (`POST /v1/scan` orchestration)
  - `ml/app/api/routes_match.py` (`POST /v1/match` orchestration)
  - `ml/app/api/routes_medicines.py` (`GET /v1/medicines/search`, `GET /v1/medicines/{id}`)
  - `tests/test_api_integration.py` (End-to-end API tests with TestClient)
- **Definition of Done**:
  - API endpoints conform to RFC 7807 error formatting and PRD specifications.
  - All responses include the mandatory safety disclaimer.
  - `pytest tests/test_api_integration.py` passes 100%.

### Phase 1I: Golden-Set Evaluation, Reliability, and Release Checks
- **Objective**: Build evaluation harness, measure field extraction accuracy and exact-match precision, and compile model card and limitations.
- **Files to Create**:
  - `ml/evaluation/run_eval.py` (CLI evaluation runner)
  - `ml/evaluation/metrics.py` (Accuracy, precision, recall, latency calculations)
  - `ml/reports/MODEL_CARD.md` (Documenting model capabilities, intended use, prohibited use, and data provenance)
  - `ml/reports/README.md` (Subsystem documentation and run guide)
- **Definition of Done**:
  - Evaluation harness runs reproducibly.
  - Release gate: **Zero false-positive EXACT matches** on the evaluation set. Any false positive blocks release.
  - Complete `MODEL_CARD.md` generated with explicit limitations.

---

## 8. Summary of Blockers and Clear Mitigation Paths

| Blocker / Dependency | Impact | Status | Mitigation Path |
|---|---|---|---|
| **Vision Provider API Key** | Cannot run live VLM queries | Soft blocker | Use `MockExtractor` with golden fixture responses for all unit/integration tests until key is provided. |
| **Authoritative NTI Drug List** | Cannot run automated clinical NTI filtering | **HARD BLOCKED** | Mark NTI feature as blocked; default all outputs to mandatory doctor consultation notice; do not invent drug lists. |
| **Jan Aushadhi Kendra Directory** | Store locator endpoint cannot return real locations | Soft blocker | Defer Kendra locator to Phase 2; focus strictly on medicine extraction and matching. |
| **PostgreSQL / pgvector Setup** | DB setup complexity | Resolved | Use SQLite + RapidFuzz locally. Schema is 100% SQLAlchemy-compatible with Postgres for zero-risk future migration. |
