"""Unit and safety regression tests for Phase 1E: Candidate Resolver & Retrieval Evaluation.

Covers:
1. Status classification: CANDIDATES_FOUND, NO_CANDIDATE, INSUFFICIENT_EVIDENCE.
2. Spelling variants and OCR noise resolution via RapidFuzz and chemical synonym mapping.
3. Multi-ingredient fixed-dose combinations and order-independent matching.
4. Strength value and concentration denominator distinctions.
5. Conservative salt modifier distinctions (besylate vs maleate never EXACT).
6. Release type distinctions (SR vs IR vs unknown release never EXACT).
7. Duplicate candidate handling and ID deduplication.
8. Quarantined, discontinued, and commercial brand candidate exclusion.
9. Golden safety rule: High fuzzy score or brand similarity alone can NEVER produce EXACT.
10. Integration test asserting zero False-EXACT on benchmark dataset.
"""

import pytest

from ml.data.database import DEFAULT_DB_URL, get_db_session
from ml.data.models import ProductRecord, ProductSaltRecord
from ml.evaluation.benchmark_resolver import evaluate_resolver_benchmark
from ml.resolver.candidates import (
    CandidateResolver,
    ResolverStatus,
    product_record_to_canonical,
)
from ml.safety.matcher import DeterministicMatcher, evaluate_single_pair
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
        source_name="TEST_FIXTURE",
        source_row_id="tf_1",
        raw_text=name,
        retrieval_date="2026-10-13",
        price_date="2026-10-08",
        checksum_sha256="1111111111111111111111111111111111111111111111111111111111111111",
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


@pytest.fixture
def resolver():
    """Provides CandidateResolver instance against the local catalogue SQLite DB."""
    return CandidateResolver(db_url=DEFAULT_DB_URL, min_fuzzy_score=55.0)


class TestResolverStatusClassification:
    """Tests distinguishing NO_CANDIDATE, INSUFFICIENT_EVIDENCE, and CANDIDATES_FOUND."""

    def test_insufficient_evidence_on_empty_canonical(self, resolver):
        empty_med = CanonicalMedicine(
            product_id="test_empty",
            name="Unknown Pack",
            brand_name=None,
            salts=[ActiveSaltMoiety(salt_name="placeholder", strength_value=1.0, strength_unit="mg", per_unit="unit")],
            is_quarantined=True,
            quarantine_reason="Test unreadable",
        )
        empty_med.salts = []  # Empty composition
        empty_med.brand_name = None

        res = resolver.resolve_from_canonical(empty_med)
        assert res.status == ResolverStatus.INSUFFICIENT_EVIDENCE
        assert len(res.candidates) == 0

    def test_insufficient_evidence_on_empty_query_string(self, resolver):
        res = resolver.resolve_from_query("")
        assert res.status == ResolverStatus.INSUFFICIENT_EVIDENCE
        assert len(res.candidates) == 0

        res_spaces = resolver.resolve_from_query("   ")
        assert res_spaces.status == ResolverStatus.INSUFFICIENT_EVIDENCE

    def test_no_candidate_on_nonexistent_medicine(self, resolver):
        res = resolver.resolve_from_query("NonExistentChemicalX99 1000mg")
        assert res.status == ResolverStatus.NO_CANDIDATE
        assert len(res.candidates) == 0

    def test_candidates_found_on_valid_query(self, resolver):
        res = resolver.resolve_from_query("Metformin")
        assert res.status == ResolverStatus.CANDIDATES_FOUND
        assert len(res.candidates) > 0


class TestSpellingVariantsAndFuzzyRetrieval:
    """Tests spelling variants and OCR noise handling."""

    def test_spelling_variation_brand_name(self, resolver):
        # Query with typo "Augmentn 625" should find Jan Aushadhi amox+clav generic
        res = resolver.resolve_from_query("Augmentn 625")
        assert res.status == ResolverStatus.CANDIDATES_FOUND
        c_ids = [c.product_id for c in res.candidates]
        assert "ja_39" in c_ids or any("amoxycillin" in c.canonical_name.lower() for c in res.candidates)

    def test_spelling_variation_generic_name(self, resolver):
        # "Diclophenac" with 'ph' instead of 'f'
        res = resolver.resolve_from_query("Diclophenac 100mg Prolonged")
        assert res.status == ResolverStatus.CANDIDATES_FOUND
        top_name = res.candidates[0].canonical_name.lower()
        assert "diclofenac" in top_name

    def test_fuzzy_brand_resolution(self, resolver):
        # "Azithrl 500" typo in brand Azithral 500
        res = resolver.resolve_from_query("Azithrl 500 Tablet")
        assert res.status == ResolverStatus.CANDIDATES_FOUND
        # Should retrieve azithromycin generic
        assert any("azithromycin" in c.canonical_name.lower() for c in res.candidates)


class TestCombinationIngredients:
    """Tests fixed-dose multi-ingredient combinations."""

    def test_order_independent_combination_retrieval(self, resolver):
        # Query with Pioglitazone + Metformin in reverse order
        med = CanonicalMedicine(
            product_id="test_combo",
            name="Met-Pio SR",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.SR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="metformin", strength_value=500.0, strength_unit="mg", per_unit="unit"),
                ActiveSaltMoiety(salt_name="pioglitazone", strength_value=15.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(50.0, 10.0, _make_dummy_provenance("Test Combo")),
            provenance=_make_dummy_provenance("Test Combo"),
        )
        res, match = resolver.resolve_and_match(med)
        assert res.status == ResolverStatus.CANDIDATES_FOUND
        assert len(res.candidates) > 0
        assert res.candidates[0].product_id == "ja_150"
        # Since ja_150 is Pioglitazone 15mg and Metformin 500mg SR, must match EXACT
        assert match.tier == MatchTier.EXACT

    def test_partial_vs_full_combination_overlap(self, resolver):
        # Query single-ingredient Metformin 500mg
        single_med = CanonicalMedicine(
            product_id="test_single",
            name="Metformin Single 500mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.MR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="metformin", salt_modifier="hydrochloride", strength_value=500.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(30.0, 10.0, _make_dummy_provenance("Single")),
            provenance=_make_dummy_provenance("Single"),
        )
        res = resolver.resolve_from_canonical(single_med)
        assert res.status == ResolverStatus.CANDIDATES_FOUND
        # ja_372 is pure Metformin 500 PR; it must be ranked above combinations
        top_cand = res.candidates[0]
        assert top_cand.product_id == "ja_372"
        assert "exact_active_moiety_set_match" in top_cand.evidence


class TestSaltAndReleaseSafetyGates:
    """Verifies that fuzzy retrieval cannot bypass deterministic safety rules."""

    def test_salt_modifier_besylate_vs_maleate_blocks_exact(self, resolver):
        # Scanned product is Amlodipine Maleate
        med = CanonicalMedicine(
            product_id="test_amlo_mal",
            name="Amlodipine Maleate 5mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="amlodipine", salt_modifier="maleate", strength_value=5.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(25.0, 10.0, _make_dummy_provenance("Amlo Maleate")),
            provenance=_make_dummy_provenance("Amlo Maleate"),
        )
        res, match = resolver.resolve_and_match(med)
        # Even if candidates are found, tier must NEVER be EXACT
        assert match.tier != MatchTier.EXACT
        assert match.tier in (MatchTier.CLOSE, MatchTier.NONE)

    def test_release_profile_sr_vs_ir_blocks_exact(self, resolver):
        # Scanned product is Immediate Release (IR) Metformin 500mg
        med = CanonicalMedicine(
            product_id="test_met_ir",
            name="Metformin IR 500mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="metformin", salt_modifier="hydrochloride", strength_value=500.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(20.0, 10.0, _make_dummy_provenance("Met IR")),
            provenance=_make_dummy_provenance("Met IR"),
        )
        res, match = resolver.resolve_and_match(med)
        # All eligible Jan Aushadhi 500mg generics are MR or SR (ja_372 is MR)
        # Therefore, EXACT match must be blocked
        assert match.tier != MatchTier.EXACT
        assert match.tier in (MatchTier.CLOSE, MatchTier.NONE)

    def test_unknown_release_in_scanned_medicine_blocks_exact(self, resolver):
        med = CanonicalMedicine(
            product_id="test_unk_rel",
            name="Metformin Unknown Release 500mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.UNKNOWN,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="metformin", salt_modifier="hydrochloride", strength_value=500.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(20.0, 10.0, _make_dummy_provenance("Met Unk")),
            provenance=_make_dummy_provenance("Met Unk"),
        )
        res, match = resolver.resolve_and_match(med)
        assert match.tier == MatchTier.NONE
        assert any("release type is unknown" in w.lower() for w in match.warnings)

    def test_strength_mismatch_blocks_exact(self, resolver):
        # 1000mg scanned medicine matching against 500mg generic
        med = CanonicalMedicine(
            product_id="test_met_1000",
            name="Metformin MR 1000mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.MR,
            route=AdministrationRoute.ORAL,
            salts=[
                ActiveSaltMoiety(salt_name="metformin", salt_modifier="hydrochloride", strength_value=1000.0, strength_unit="mg", per_unit="unit"),
            ],
            price=_make_dummy_price(40.0, 10.0, _make_dummy_provenance("Met 1000")),
            provenance=_make_dummy_provenance("Met 1000"),
        )
        res, match = resolver.resolve_and_match(med)
        # Candidates in catalogue are ja_144 (SR, not MR) and ja_372 (500mg, not 1000mg)
        # Neither qualifies for EXACT
        assert match.tier != MatchTier.EXACT


class TestCatalogueIntegrityAndExclusions:
    """Tests that quarantined, discontinued, and ineligible records fail closed."""

    def test_discontinued_candidate_fails_closed(self):
        # Create synthetic candidate with is_discontinued=True
        prov = _make_dummy_provenance("Discontinued Item")
        price = _make_dummy_price(10.0, 10.0, prov)
        scanned = CanonicalMedicine(
            product_id="s1",
            name="Metformin 500mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.MR,
            route=AdministrationRoute.ORAL,
            salts=[ActiveSaltMoiety(salt_name="metformin", strength_value=500.0, strength_unit="mg", per_unit="unit")],
            price=price,
            provenance=prov,
        )
        cand = CanonicalMedicine(
            product_id="c_disc",
            name="Metformin 500mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.MR,
            route=AdministrationRoute.ORAL,
            salts=[ActiveSaltMoiety(salt_name="metformin", strength_value=500.0, strength_unit="mg", per_unit="unit")],
            price=price,
            is_discontinued=True,
            provenance=prov,
        )
        tier, reason = evaluate_single_pair(scanned, cand)
        assert tier == MatchTier.NONE
        assert "discontinued" in reason.lower()

    def test_quarantined_candidate_fails_closed(self):
        prov = _make_dummy_provenance("Quarantined Item")
        price = _make_dummy_price(10.0, 10.0, prov)
        scanned = CanonicalMedicine(
            product_id="s1",
            name="Metformin 500mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.MR,
            route=AdministrationRoute.ORAL,
            salts=[ActiveSaltMoiety(salt_name="metformin", strength_value=500.0, strength_unit="mg", per_unit="unit")],
            price=price,
            provenance=prov,
        )
        cand = CanonicalMedicine(
            product_id="c_quar",
            name="Metformin 500mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.MR,
            route=AdministrationRoute.ORAL,
            salts=[ActiveSaltMoiety(salt_name="metformin", strength_value=500.0, strength_unit="mg", per_unit="unit")],
            price=price,
            is_quarantined=True,
            quarantine_reason="Zero price recorded",
            provenance=prov,
        )
        tier, reason = evaluate_single_pair(scanned, cand)
        assert tier == MatchTier.NONE
        assert "quarantined" in reason.lower()

    def test_ineligible_candidate_fails_closed(self):
        prov = _make_dummy_provenance("Ineligible Item")
        price = _make_dummy_price(10.0, 10.0, prov)
        scanned = CanonicalMedicine(
            product_id="s1",
            name="Metformin 500mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.MR,
            route=AdministrationRoute.ORAL,
            salts=[ActiveSaltMoiety(salt_name="metformin", strength_value=500.0, strength_unit="mg", per_unit="unit")],
            price=price,
            provenance=prov,
        )
        cand = CanonicalMedicine(
            product_id="c_inel",
            name="Metformin 500mg",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.MR,
            route=AdministrationRoute.ORAL,
            salts=[ActiveSaltMoiety(salt_name="metformin", strength_value=500.0, strength_unit="mg", per_unit="unit")],
            price=price,
            is_eligible_for_matching=False,
            provenance=prov,
        )
        tier, reason = evaluate_single_pair(scanned, cand)
        assert tier == MatchTier.NONE
        assert "ineligible" in reason.lower()

    def test_commercial_brand_never_returned_as_generic_substitute(self, resolver):
        session = get_db_session(DEFAULT_DB_URL)
        try:
            pool = resolver._get_generic_pool(session)
            # Generic pool must contain zero commercial brands
            for pid, name, prod in pool:
                assert prod.kind == "generic"
                assert prod.is_quarantined is False
        finally:
            session.close()

    def test_candidate_resolver_deduplicates_candidates(self, resolver):
        # Query known generic substring
        res = resolver.resolve_from_query("Metformin")
        c_ids = [c.product_id for c in res.candidates]
        assert len(c_ids) == len(set(c_ids)), "Candidate IDs must be strictly unique"


class TestHighFuzzyScoreNeverProducesExact:
    """Safety principle: Lexical or fuzzy similarity can never force an EXACT tier."""

    def test_perfect_lexical_similarity_mismatched_salt_fails_exact(self, resolver):
        # Suppose a drug has identical display name and 100% string similarity,
        # but one is Sodium and one is Potassium salt
        prov = _make_dummy_provenance("Test Salt Mismatch")
        price = _make_dummy_price(20.0, 10.0, prov)

        s_med = CanonicalMedicine(
            product_id="s_diclo_na",
            name="Diclofenac 50mg Tablet",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.DR_EC,
            route=AdministrationRoute.ORAL,
            salts=[ActiveSaltMoiety(salt_name="diclofenac", salt_modifier="sodium", strength_value=50.0, strength_unit="mg", per_unit="unit")],
            price=price,
            provenance=prov,
        )
        c_med = CanonicalMedicine(
            product_id="c_diclo_k",
            name="Diclofenac 50mg Tablet",
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.DR_EC,
            route=AdministrationRoute.ORAL,
            salts=[ActiveSaltMoiety(salt_name="diclofenac", salt_modifier="potassium", strength_value=50.0, strength_unit="mg", per_unit="unit")],
            price=price,
            provenance=prov,
        )

        tier, reason = evaluate_single_pair(s_med, c_med)
        assert tier == MatchTier.CLOSE
        assert "salt chemical modifier differs" in reason.lower()


class TestBenchmarkEvaluationIntegration:
    """Integration test validating benchmark metrics and zero false-EXACT."""

    def test_benchmark_train_split(self):
        summary = evaluate_resolver_benchmark(split_filter="train")
        assert summary.total_queries == 15
        assert summary.false_exact_count == 0, "Zero False-EXACT in Train split"
        assert summary.top_3_recall_pct >= 90.0, "Top-3 Recall must be >= 90%"
        assert summary.retrieval_accuracy_pct >= 90.0

    def test_benchmark_test_split(self):
        summary = evaluate_resolver_benchmark(split_filter="test")
        assert summary.total_queries == 15
        assert summary.false_exact_count == 0, "Zero False-EXACT in Held-out Test split"
        assert summary.top_3_recall_pct >= 90.0, "Top-3 Recall must be >= 90%"
        assert summary.retrieval_accuracy_pct >= 90.0

    def test_benchmark_overall(self):
        summary = evaluate_resolver_benchmark(split_filter=None)
        assert summary.total_queries == 30
        assert summary.false_exact_count == 0, "Zero False-EXACT overall"
        assert summary.top_3_recall_pct == 100.0, "All target candidates retrieved in Top-3"
        assert summary.mean_latency_ms < 100.0, "Mean latency must be sub-100ms"
