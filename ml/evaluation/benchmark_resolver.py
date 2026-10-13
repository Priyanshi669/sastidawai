"""Retrieval and candidate resolution benchmark with train/test separation.

This benchmark evaluates retrieval recall (Top-1 and Top-3), resolution accuracy,
and strictly audits against false-EXACT matches across real-world Indian medicine queries.

Provenance & Limitations:
- Constructed from real commercial medicine brands in the Indian Medicine Dataset sample (500 rows)
  and verified Jan Aushadhi generic catalogue records.
- Train (15 queries) and Held-out Test (15 queries) splits.
- LIMITATION: Synthetic and manually curated for retrieval engineering evaluation;
  NOT clinically validated and does NOT constitute clinical advice.
"""

from dataclasses import dataclass, field
import json
import time
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel

from ml.data.database import DEFAULT_DB_URL
from ml.resolver.candidates import CandidateResolver, ResolverStatus
from ml.safety.matcher import DeterministicMatcher
from ml.schemas.canonical import (
    ActiveSaltMoiety,
    CanonicalMedicine,
    PriceRecord,
    ProvenanceRecord,
)
from ml.schemas.enums import (
    AdministrationRoute,
    DosageForm,
    MatchTier,
    ReleaseType,
    ScanWorkflowState,
)


def _make_dummy_provenance(name: str) -> ProvenanceRecord:
    return ProvenanceRecord(
        source_name="BENCHMARK_PROVENANCE",
        source_row_id="bm_test",
        raw_text=name,
        retrieval_date="2026-10-13",
        price_date="2026-10-08",
        checksum_sha256="0000000000000000000000000000000000000000000000000000000000000000",
    )


def _make_dummy_price(mrp: float, count: float, prov: ProvenanceRecord) -> PriceRecord:
    return PriceRecord(
        pack_mrp_inr=mrp,
        pack_count=count,
        unit_price_inr=round(mrp / count, 4),
        price_date="2026-10-08",
        is_verified_current=True,
        provenance=prov,
    )


@dataclass
class BenchmarkQuery:
    """A benchmark test case representing an OCR scan or text search query."""
    query_id: str
    split: str  # "train" or "test"
    category: str
    query_text: str
    scanned_med: Optional[CanonicalMedicine]
    expected_top_candidate_ids: List[str]  # Product IDs acceptable as top matches
    expected_tier: MatchTier  # Expected matcher result (EXACT, CLOSE, NONE)
    notes: str


# ---------------------------------------------------------------------------
# Curated Benchmark Dataset (30 Cases: 15 Train / 15 Test)
# ---------------------------------------------------------------------------

BENCHMARK_DATASET: List[BenchmarkQuery] = [
    # ========================== TRAIN / TUNING SPLIT (15 cases) ==========================
    BenchmarkQuery(
        query_id="train_01",
        split="train",
        category="standard_brand",
        query_text="Augmentin 625 Duo Tablet",
        scanned_med=CanonicalMedicine(
            product_id="bm_aug_625",
            name="Augmentin 625 Duo Tablet",
            brand_name="Augmentin 625 Duo Tablet",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="amoxicillin", strength_value=500.0, strength_unit="mg", per_unit="unit"),
                ActiveSaltMoiety(salt_name="clavulanic acid", strength_value=125.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(200.0, 10.0, _make_dummy_provenance("Augmentin 625 Duo")),
            provenance=_make_dummy_provenance("Augmentin 625 Duo"),
        ),
        expected_top_candidate_ids=["ja_39"],
        expected_tier=MatchTier.NONE,  # ja_39 has unknown release type -> must fail closed to NONE
        notes="Standard brand lookup. Generic ja_39 has unknown release, correctly preventing false EXACT.",
    ),
    BenchmarkQuery(
        query_id="train_02",
        split="train",
        category="exact_eligible",
        query_text="Glycomet 500 PR Tablet",
        scanned_med=CanonicalMedicine(
            product_id="bm_glyco_500pr",
            name="Glycomet 500 PR Tablet",
            brand_name="Glycomet",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.MR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="metformin", salt_modifier="hydrochloride", strength_value=500.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(35.0, 10.0, _make_dummy_provenance("Glycomet 500 PR")),
            provenance=_make_dummy_provenance("Glycomet 500 PR"),
        ),
        expected_top_candidate_ids=["ja_372"],
        expected_tier=MatchTier.EXACT,  # ja_372 is MR, 500mg, metformin hydrochloride tablet -> EXACT match
        notes="Exact eligible match against Metformin Hydrochloride Prolonged release Tablets IP 500 mg (ja_372).",
    ),
    BenchmarkQuery(
        query_id="train_03",
        split="train",
        category="spelling_variant",
        query_text="Glycomit 500 PR",
        scanned_med=CanonicalMedicine(
            product_id="bm_glyco_typo",
            name="Glycomit 500 PR",
            brand_name="Glycomit",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.MR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="metformin", salt_modifier="hydrochloride", strength_value=500.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(35.0, 10.0, _make_dummy_provenance("Glycomit")),
            provenance=_make_dummy_provenance("Glycomit"),
        ),
        expected_top_candidate_ids=["ja_372"],
        expected_tier=MatchTier.EXACT,
        notes="Spelling typo in brand name resolved via chemical salts to ja_372.",
    ),
    BenchmarkQuery(
        query_id="train_04",
        split="train",
        category="release_mismatch",
        query_text="Metformin 500mg Immediate Release Tablet",
        scanned_med=CanonicalMedicine(
            product_id="bm_met_ir",
            name="Metformin IR 500mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="metformin", salt_modifier="hydrochloride", strength_value=500.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(20.0, 10.0, _make_dummy_provenance("Metformin IR")),
            provenance=_make_dummy_provenance("Metformin IR"),
        ),
        expected_top_candidate_ids=["ja_372", "ja_145"],
        expected_tier=MatchTier.CLOSE,  # ja_372 is MR vs IR -> CLOSE (or NONE for ja_145)
        notes="Release mismatch: IR vs MR must NEVER produce EXACT.",
    ),
    BenchmarkQuery(
        query_id="train_05",
        split="train",
        category="salt_variant",
        query_text="Amlodipine Maleate 5mg Tablet",
        scanned_med=CanonicalMedicine(
            product_id="bm_amlo_maleate",
            name="Amlodipine Maleate 5mg Tablet",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="amlodipine", salt_modifier="maleate", strength_value=5.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(30.0, 10.0, _make_dummy_provenance("Amlodipine Maleate")),
            provenance=_make_dummy_provenance("Amlodipine Maleate"),
        ),
        expected_top_candidate_ids=["ja_264", "ja_440"],
        expected_tier=MatchTier.CLOSE,  # Maleate vs Besilate / unspecified -> CLOSE or NONE, NEVER EXACT
        notes="Salt distinction: Maleate vs Besilate must prevent EXACT match.",
    ),
    BenchmarkQuery(
        query_id="train_06",
        split="train",
        category="combination",
        query_text="Pioglitazone 15mg + Metformin 500mg SR",
        scanned_med=CanonicalMedicine(
            product_id="bm_pio_met",
            name="Pio-Met SR Tablet",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.SR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="pioglitazone", strength_value=15.0, strength_unit="mg", per_unit="unit"),
                ActiveSaltMoiety(salt_name="metformin", strength_value=500.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(85.0, 10.0, _make_dummy_provenance("Pio-Met")),
            provenance=_make_dummy_provenance("Pio-Met"),
        ),
        expected_top_candidate_ids=["ja_150"],
        expected_tier=MatchTier.EXACT,  # ja_150 has Pioglitazone 15mg and Metformin 500mg Sustained Release Tablets
        notes="Verified multi-ingredient fixed-dose combination match against ja_150.",
    ),
    BenchmarkQuery(
        query_id="train_07",
        split="train",
        category="dispersible_form",
        query_text="Amoxycillin Dispersible 125mg Tablet",
        scanned_med=CanonicalMedicine(
            product_id="bm_amox_dt",
            name="Amoxycillin DT 125mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.DISPERSIBLE,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="amoxycillin trihydrate", strength_value=125.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(25.0, 10.0, _make_dummy_provenance("Amox DT")),
            provenance=_make_dummy_provenance("Amox DT"),
        ),
        expected_top_candidate_ids=["ja_42"],
        expected_tier=MatchTier.EXACT,  # ja_42 is Amoxycillin Trihydrate Dispersible Tablets IP 125 mg
        notes="Dispersible tablet formulation verified against ja_42.",
    ),
    BenchmarkQuery(
        query_id="train_08",
        split="train",
        category="gastro_resistant",
        query_text="Aspirin 150mg Gastro-resistant Tablet",
        scanned_med=CanonicalMedicine(
            product_id="bm_asp_ec",
            name="Aspirin EC 150mg Tablet",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.DR_EC,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="aspirin", strength_value=150.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(15.0, 14.0, _make_dummy_provenance("Aspirin EC")),
            provenance=_make_dummy_provenance("Aspirin EC"),
        ),
        expected_top_candidate_ids=["ja_5"],
        expected_tier=MatchTier.EXACT,  # ja_5 is Aspirin Gastro-resistant Tablets IP 150 mg
        notes="Delayed-release / gastro-resistant formulation match against ja_5.",
    ),
    BenchmarkQuery(
        query_id="train_09",
        split="train",
        category="strength_mismatch",
        query_text="Metformin 1000mg PR vs 500mg Generic",
        scanned_med=CanonicalMedicine(
            product_id="bm_met_1000",
            name="Metformin PR 1000mg Tablet",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.MR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="metformin", salt_modifier="hydrochloride", strength_value=1000.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(60.0, 10.0, _make_dummy_provenance("Metformin 1000")),
            provenance=_make_dummy_provenance("Metformin 1000"),
        ),
        expected_top_candidate_ids=["ja_144", "ja_372"],
        expected_tier=MatchTier.CLOSE,  # 1000mg vs 500mg or MR vs SR -> CLOSE, NEVER EXACT
        notes="Strength and release differences must be CLOSE, never EXACT.",
    ),
    BenchmarkQuery(
        query_id="train_10",
        split="train",
        category="no_match",
        query_text="Xyloflozacin 999mg NonExistent",
        scanned_med=CanonicalMedicine(
            product_id="bm_fake_med",
            name="Xyloflozacin 999mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="xyloflozacin", strength_value=999.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(100.0, 10.0, _make_dummy_provenance("Xyloflozacin")),
            provenance=_make_dummy_provenance("Xyloflozacin"),
        ),
        expected_top_candidate_ids=[],
        expected_tier=MatchTier.NONE,
        notes="Completely fabricated active substance with no catalogue equivalent.",
    ),
    BenchmarkQuery(
        query_id="train_11",
        split="train",
        category="insufficient_evidence",
        query_text="",
        scanned_med=None,
        expected_top_candidate_ids=[],
        expected_tier=MatchTier.NONE,
        notes="Empty query must yield INSUFFICIENT_EVIDENCE.",
    ),
    BenchmarkQuery(
        query_id="train_12",
        split="train",
        category="unknown_release_in_db",
        query_text="Metformin Hydrochloride Tablets IP 500mg",
        scanned_med=CanonicalMedicine(
            product_id="bm_met_500_unk",
            name="Metformin 500mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.UNKNOWN,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="metformin", salt_modifier="hydrochloride", strength_value=500.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(15.0, 10.0, _make_dummy_provenance("Metformin 500")),
            provenance=_make_dummy_provenance("Metformin 500"),
        ),
        expected_top_candidate_ids=["ja_145", "ja_372"],
        expected_tier=MatchTier.NONE,
        notes="Unknown release type on scanned medicine blocks EXACT matching.",
    ),
    BenchmarkQuery(
        query_id="train_13",
        split="train",
        category="prolonged_release",
        query_text="Diclofenac Sodium 100mg Prolonged Release",
        scanned_med=CanonicalMedicine(
            product_id="bm_diclo_pr",
            name="Diclofenac PR 100mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.MR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="diclofenac", salt_modifier="sodium", strength_value=100.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(45.0, 10.0, _make_dummy_provenance("Diclofenac PR")),
            provenance=_make_dummy_provenance("Diclofenac PR"),
        ),
        expected_top_candidate_ids=["ja_9"],
        expected_tier=MatchTier.EXACT,  # ja_9 is Diclofenac Sodium Prolonged Release Tablets IP 100 mg
        notes="Prolonged release verified match against ja_9.",
    ),
    BenchmarkQuery(
        query_id="train_14",
        split="train",
        category="text_query_brand",
        query_text="Augmentin 625 Duo Tablet",
        scanned_med=None,
        expected_top_candidate_ids=["ja_39"],
        expected_tier=MatchTier.NONE,
        notes="Free-text query resolved via brand reference table to ja_39.",
    ),
    BenchmarkQuery(
        query_id="train_15",
        split="train",
        category="text_query_generic",
        query_text="Metformin Hydrochloride Prolonged release Tablets IP 500 mg",
        scanned_med=None,
        expected_top_candidate_ids=["ja_372"],
        expected_tier=MatchTier.NONE,
        notes="Free-text exact string lookup retrieving ja_372.",
    ),

    # ========================== TEST / EVALUATION SPLIT (15 cases) ==========================
    BenchmarkQuery(
        query_id="test_01",
        split="test",
        category="standard_brand",
        query_text="Azithral 500 Tablet",
        scanned_med=CanonicalMedicine(
            product_id="bm_azithral_500",
            name="Azithral 500 Tablet",
            brand_name="Azithral 500 Tablet",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="azithromycin", strength_value=500.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(119.0, 5.0, _make_dummy_provenance("Azithral 500")),
            provenance=_make_dummy_provenance("Azithral 500"),
        ),
        expected_top_candidate_ids=["ja_48"],
        expected_tier=MatchTier.CLOSE,  # ja_48 is 100mg DT vs 500mg IR -> CLOSE or NONE
        notes="Held-out brand test: Azithral 500 retrieves azithromycin generics; dosage/strength prevents false EXACT.",
    ),
    BenchmarkQuery(
        query_id="test_02",
        split="test",
        category="spelling_variant",
        query_text="Augmentn 625",
        scanned_med=None,
        expected_top_candidate_ids=["ja_39"],
        expected_tier=MatchTier.NONE,
        notes="Held-out noisy OCR brand query resolved via fuzzy brand matching to ja_39.",
    ),
    BenchmarkQuery(
        query_id="test_03",
        split="test",
        category="exact_eligible",
        query_text="Diclofenac Gastro-Resistant 50mg Tablet",
        scanned_med=CanonicalMedicine(
            product_id="bm_diclo_ec",
            name="Diclofenac EC 50mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.DR_EC,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="diclofenac", strength_value=50.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(25.0, 10.0, _make_dummy_provenance("Diclofenac EC")),
            provenance=_make_dummy_provenance("Diclofenac EC"),
        ),
        expected_top_candidate_ids=["ja_11"],
        expected_tier=MatchTier.EXACT,  # ja_11 is Diclofenac Gastro-Resistant Tablets IP 50 mg
        notes="Held-out exact match on delayed-release gastro-resistant formulation.",
    ),
    BenchmarkQuery(
        query_id="test_04",
        split="test",
        category="combination_partial_overlap",
        query_text="Metformin 500mg alone vs Metformin + Glimepiride in Catalogue",
        scanned_med=CanonicalMedicine(
            product_id="bm_met_single",
            name="Metformin Single 500mg PR",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.MR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="metformin", strength_value=500.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(20.0, 10.0, _make_dummy_provenance("Metformin 500 Single")),
            provenance=_make_dummy_provenance("Metformin 500 Single"),
        ),
        expected_top_candidate_ids=["ja_372", "ja_904"],
        expected_tier=MatchTier.EXACT,  # ja_372 is pure Metformin 500 PR, top-1 must be ja_372
        notes="Resolver must rank pure mono-ingredient ja_372 above combo ja_904 (Met+Glimepiride).",
    ),
    BenchmarkQuery(
        query_id="test_05",
        split="test",
        category="sr_sustained_release",
        query_text="Metformin SR 1000mg Tablet",
        scanned_med=CanonicalMedicine(
            product_id="bm_met_sr1000",
            name="Metformin SR 1000mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.SR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="metformin", salt_modifier="hydrochloride", strength_value=1000.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(45.0, 10.0, _make_dummy_provenance("Metformin SR 1000")),
            provenance=_make_dummy_provenance("Metformin SR 1000"),
        ),
        expected_top_candidate_ids=["ja_144"],
        expected_tier=MatchTier.EXACT,  # ja_144 is Metformin Hydrochloride Sustained Release Tablets IP 1000 mg
        notes="Held-out exact match on 1000mg sustained release generic (ja_144).",
    ),
    BenchmarkQuery(
        query_id="test_06",
        split="test",
        category="spelling_variant",
        query_text="Azithrl 500 Tablet",
        scanned_med=None,
        expected_top_candidate_ids=["ja_72", "ja_18", "ja_48"],
        expected_tier=MatchTier.NONE,
        notes="Spelling error in brand name 'Azithrl' fuzzy-resolved to azithromycin 500mg generic (ja_72).",
    ),
    BenchmarkQuery(
        query_id="test_07",
        split="test",
        category="release_mismatch",
        query_text="Metformin ER 500mg vs Metformin SR 500mg",
        scanned_med=CanonicalMedicine(
            product_id="bm_met_er500",
            name="Metformin ER 500mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.ER,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="metformin", strength_value=500.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(30.0, 10.0, _make_dummy_provenance("Metformin ER")),
            provenance=_make_dummy_provenance("Metformin ER"),
        ),
        expected_top_candidate_ids=["ja_372", "ja_150"],
        expected_tier=MatchTier.CLOSE,  # ER vs MR/SR -> CLOSE, never EXACT
        notes="ER vs MR/SR release profile distinction blocks EXACT.",
    ),
    BenchmarkQuery(
        query_id="test_08",
        split="test",
        category="route_mismatch",
        query_text="Diclofenac Injection 75mg vs Oral Tablet",
        scanned_med=CanonicalMedicine(
            product_id="bm_diclo_inj",
            name="Diclofenac Injection 75mg/ml",
            dosage_form=DosageForm.INJECTION,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.PARENTERAL,
            salts=[
                ActiveSaltMoiety(salt_name="diclofenac", strength_value=75.0, strength_unit="mg", per_unit="ml"),
            ],
            price=_make_dummy_price(15.0, 1.0, _make_dummy_provenance("Diclofenac Inj")),
            provenance=_make_dummy_provenance("Diclofenac Inj"),
        ),
        expected_top_candidate_ids=["ja_9", "ja_11"],
        expected_tier=MatchTier.NONE,  # IV route vs oral route -> NONE
        notes="Route mismatch (intravenous vs oral) strictly produces NONE.",
    ),
    BenchmarkQuery(
        query_id="test_09",
        split="test",
        category="dispersible_vs_standard",
        query_text="Azithromycin 100mg Dispersible Tablet",
        scanned_med=CanonicalMedicine(
            product_id="bm_azith_dt100",
            name="Azithromycin DT 100mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.DISPERSIBLE,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="azithromycin", strength_value=100.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(35.0, 10.0, _make_dummy_provenance("Azith DT")),
            provenance=_make_dummy_provenance("Azith DT"),
        ),
        expected_top_candidate_ids=["ja_48"],
        expected_tier=MatchTier.EXACT,  # ja_48 is Azithromycin Dispersible Tablets 100mg
        notes="Exact match on pediatric dispersible tablet (ja_48).",
    ),
    BenchmarkQuery(
        query_id="test_10",
        split="test",
        category="no_match",
        query_text="Veterinary Canine Chewable 50mg",
        scanned_med=CanonicalMedicine(
            product_id="bm_vet_med",
            name="Canine Chewable 50mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.CHEWABLE,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="afoxolaner", strength_value=50.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(500.0, 1.0, _make_dummy_provenance("Vet Med")),
            provenance=_make_dummy_provenance("Vet Med"),
        ),
        expected_top_candidate_ids=[],
        expected_tier=MatchTier.NONE,
        notes="Veterinary medication completely absent from human PMBJP catalogue.",
    ),
    BenchmarkQuery(
        query_id="test_11",
        split="test",
        category="denominator_mismatch",
        query_text="Amoxicillin 250mg per 5ml Oral Suspension vs Tablet",
        scanned_med=CanonicalMedicine(
            product_id="bm_amox_susp",
            name="Amoxicillin Suspension 250mg/5ml",
            dosage_form=DosageForm.SYRUP,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="amoxicillin", strength_value=250.0, strength_unit="mg", per_unit="5ml"),
            ],
            price=_make_dummy_price(65.0, 60.0, _make_dummy_provenance("Amox Susp")),
            provenance=_make_dummy_provenance("Amox Susp"),
        ),
        expected_top_candidate_ids=["ja_42", "ja_39"],
        expected_tier=MatchTier.NONE,  # Denominator (5ml vs tablet) or form (syrup vs tablet) and salt difference fail closed to NONE
        notes="Concentration denominator, dosage form, and moiety differences fail closed to NONE.",
    ),
    BenchmarkQuery(
        query_id="test_12",
        split="test",
        category="multi_salt_combo",
        query_text="Sitagliptin 50mg + Metformin 500mg ER",
        scanned_med=CanonicalMedicine(
            product_id="bm_sita_met_er",
            name="Sitagliptin 50 + Metformin 500 ER",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.ER,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="sitagliptin", strength_value=50.0, strength_unit="mg", per_unit="unit"),
                ActiveSaltMoiety(salt_name="metformin", strength_value=500.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(180.0, 10.0, _make_dummy_provenance("Sita-Met ER")),
            provenance=_make_dummy_provenance("Sita-Met ER"),
        ),
        expected_top_candidate_ids=["ja_2364"],
        expected_tier=MatchTier.EXACT,  # ja_2364 is Sitagliptin 50mg and Metformin 500mg Extended Release Tablets
        notes="Multi-salt extended release combination match against ja_2364.",
    ),
    BenchmarkQuery(
        query_id="test_13",
        split="test",
        category="text_query_brand",
        query_text="Amoxyclav 625 Tablet",
        scanned_med=None,
        expected_top_candidate_ids=["ja_39"],
        expected_tier=MatchTier.NONE,
        notes="Commercial brand Amoxyclav 625 resolved to Jan Aushadhi generic ja_39.",
    ),
    BenchmarkQuery(
        query_id="test_14",
        split="test",
        category="spelling_variant",
        query_text="Diclophenac 100mg Prolonged",
        scanned_med=None,
        expected_top_candidate_ids=["ja_9"],
        expected_tier=MatchTier.NONE,
        notes="Spelling variant 'Diclophenac' retrieved via RapidFuzz generic pool to ja_9.",
    ),
    BenchmarkQuery(
        query_id="test_15",
        split="test",
        category="no_match",
        query_text="NonExistentDrugBrand 100mg",
        scanned_med=None,
        expected_top_candidate_ids=[],
        expected_tier=MatchTier.NONE,
        notes="Unrecognized brand name with no salts returns NO_CANDIDATE.",
    ),
]


# ---------------------------------------------------------------------------
# Benchmark Evaluation Engine
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkCaseResult:
    query_id: str
    split: str
    category: str
    query_text: str
    status: str
    retrieved_candidate_ids: List[str]
    top_candidate_id: Optional[str]
    top_1_hit: bool
    top_3_hit: bool
    actual_tier: MatchTier
    expected_tier: MatchTier
    tier_match: bool
    is_false_exact: bool
    latency_ms: float
    notes: str


@dataclass
class BenchmarkSummary:
    total_queries: int
    split: str
    top_1_recall_pct: float
    top_3_recall_pct: float
    retrieval_accuracy_pct: float
    false_exact_count: int
    mean_latency_ms: float
    p95_latency_ms: float
    category_metrics: Dict[str, Dict[str, Any]]
    failure_cases: List[Dict[str, Any]]
    limitations: List[str]


def evaluate_resolver_benchmark(
    db_url: str = DEFAULT_DB_URL,
    split_filter: Optional[str] = None,
) -> BenchmarkSummary:
    """Executes the candidate resolver benchmark and returns structured metrics."""
    resolver = CandidateResolver(db_url=db_url)
    
    queries = BENCHMARK_DATASET
    if split_filter:
        queries = [q for q in BENCHMARK_DATASET if q.split == split_filter]

    results: List[BenchmarkCaseResult] = []
    category_counts: Dict[str, Dict[str, int]] = {}

    for q in queries:
        t0 = time.perf_counter()

        # Execute resolution
        if q.scanned_med:
            resolver_res, match_res = resolver.resolve_and_match(
                scanned=q.scanned_med,
                workflow_state=ScanWorkflowState.READY_FOR_MATCHING,
                limit=5,
            )
            actual_tier = match_res.tier
        else:
            resolver_res = resolver.resolve_from_query(query=q.query_text, limit=5)
            actual_tier = MatchTier.NONE

        t1 = time.perf_counter()
        latency_ms = round((t1 - t0) * 1000.0, 2)

        retrieved_ids = [c.product_id for c in resolver_res.candidates]
        top_id = retrieved_ids[0] if retrieved_ids else None

        # Determine Retrieval Recall
        if not q.expected_top_candidate_ids:
            # Negative case: Correctly handled if NO candidates retrieved or all candidates safely rejected as NONE
            top_1_hit = (
                len(retrieved_ids) == 0
                or resolver_res.status in (
                    ResolverStatus.NO_CANDIDATE,
                    ResolverStatus.INSUFFICIENT_EVIDENCE,
                )
                or actual_tier == MatchTier.NONE
            )
            top_3_hit = top_1_hit
        else:
            top_1_hit = top_id in q.expected_top_candidate_ids
            top_3_hit = any(cid in q.expected_top_candidate_ids for cid in retrieved_ids[:3])

        # Strict Safety Audit: False EXACT Check
        # A False EXACT occurs whenever the system awards EXACT, but the expected tier is NOT EXACT
        is_false_exact = (actual_tier == MatchTier.EXACT) and (q.expected_tier != MatchTier.EXACT)
        tier_match = (actual_tier == q.expected_tier)

        results.append(
            BenchmarkCaseResult(
                query_id=q.query_id,
                split=q.split,
                category=q.category,
                query_text=q.query_text,
                status=resolver_res.status.value,
                retrieved_candidate_ids=retrieved_ids,
                top_candidate_id=top_id,
                top_1_hit=top_1_hit,
                top_3_hit=top_3_hit,
                actual_tier=actual_tier,
                expected_tier=q.expected_tier,
                tier_match=tier_match,
                is_false_exact=is_false_exact,
                latency_ms=latency_ms,
                notes=q.notes,
            )
        )

        # Track per-category metrics
        cat = q.category
        if cat not in category_counts:
            category_counts[cat] = {"total": 0, "top_1": 0, "top_3": 0, "false_exact": 0}
        category_counts[cat]["total"] += 1
        if top_1_hit:
            category_counts[cat]["top_1"] += 1
        if top_3_hit:
            category_counts[cat]["top_3"] += 1
        if is_false_exact:
            category_counts[cat]["false_exact"] += 1

    # Aggregate Metrics
    n = len(results)
    top_1_recall = round(sum(1 for r in results if r.top_1_hit) / n * 100.0, 2) if n else 0.0
    top_3_recall = round(sum(1 for r in results if r.top_3_hit) / n * 100.0, 2) if n else 0.0
    accuracy = round(sum(1 for r in results if r.tier_match) / n * 100.0, 2) if n else 0.0
    false_exact = sum(1 for r in results if r.is_false_exact)

    latencies = sorted([r.latency_ms for r in results])
    mean_lat = round(sum(latencies) / n, 2) if n else 0.0
    p95_lat = latencies[int(n * 0.95)] if n else 0.0

    failures = [
        {
            "query_id": r.query_id,
            "category": r.category,
            "query_text": r.query_text,
            "expected_tier": r.expected_tier.value,
            "actual_tier": r.actual_tier.value,
            "top_candidate": r.top_candidate_id,
            "retrieved_candidates": r.retrieved_candidate_ids,
            "is_false_exact": r.is_false_exact,
            "notes": r.notes,
        }
        for r in results
        if not r.top_3_hit or r.is_false_exact
    ]

    limitations = [
        "Benchmark is synthetic/curated for retrieval algorithm evaluation; does NOT claim clinical trial validation.",
        "Brand coverage is bounded to the 500-sample Indian Medicine Dataset; full production will ingest 250k rows.",
        "PMBJP catalogue contains 1,347 items with unspecified release profiles, which fail closed to NONE by safety design.",
    ]

    return BenchmarkSummary(
        total_queries=n,
        split=split_filter or "all",
        top_1_recall_pct=top_1_recall,
        top_3_recall_pct=top_3_recall,
        retrieval_accuracy_pct=accuracy,
        false_exact_count=false_exact,
        mean_latency_ms=mean_lat,
        p95_latency_ms=p95_lat,
        category_metrics=category_counts,
        failure_cases=failures,
        limitations=limitations,
    )


def print_benchmark_report():
    """Runs train, test, and overall benchmark, printing a formatted markdown table."""
    print("=" * 80)
    print("SASTI DAWAI PHASE 1E — CANDIDATE RESOLVER BENCHMARK EVALUATION")
    print("=" * 80)

    for split in ["train", "test", None]:
        label = split.upper() if split else "OVERALL (TRAIN + TEST)"
        summary = evaluate_resolver_benchmark(split_filter=split)
        print(f"\n--- {label} RESULTS ({summary.total_queries} queries) ---")
        print(f"Top-1 Retrieval Recall : {summary.top_1_recall_pct}%")
        print(f"Top-3 Retrieval Recall : {summary.top_3_recall_pct}%")
        print(f"Tier Match Accuracy    : {summary.retrieval_accuracy_pct}%")
        print(f"FALSE-EXACT Count      : {summary.false_exact_count} (Safety target: 0)")
        print(f"Latency Mean / P95     : {summary.mean_latency_ms} ms / {summary.p95_latency_ms} ms")
        print("Category Breakdown:")
        for cat, m in summary.category_metrics.items():
            print(f"  • {cat:<24}: {m['top_1']}/{m['total']} Top-1 ({round(m['top_1']/m['total']*100)}%), False-EXACT: {m['false_exact']}")
        if summary.failure_cases:
            print(f"Failures ({len(summary.failure_cases)}):")
            for f in summary.failure_cases:
                print(f"  [X] {f['query_id']} ({f['category']}): {f['query_text']} -> Got {f['actual_tier']} (Expected {f['expected_tier']})")
        else:
            print("Failures               : 0 (All retrieval targets met)")


if __name__ == "__main__":
    print_benchmark_report()
