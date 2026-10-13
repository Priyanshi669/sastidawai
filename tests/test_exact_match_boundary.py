"""Comprehensive safety boundary unit tests for Phase 1C: Deterministic Matcher."""

import pytest
from ml.safety.matcher import DeterministicMatcher, evaluate_deterministic_match, evaluate_single_pair
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
from ml.schemas.matcher import MANDATORY_DISCLAIMER
from tests.fixtures.synthetic_medicines import (
    SYNTHETIC_BRAND_AUGMENTIN_625,
    SYNTHETIC_BRAND_METFORMIN_SR,
    SYNTHETIC_GENERIC_AUGMENTIN_625,
    SYNTHETIC_GENERIC_METFORMIN_IR,
    SYNTHETIC_GENERIC_METFORMIN_SR,
    make_synthetic_medicine,
)


class TestExactMatchPositives:
    """Tests verifying that identical, verified formulations achieve EXACT tier and savings."""

    def test_single_salt_exact_match(self):
        result = DeterministicMatcher.match(
            scanned=SYNTHETIC_BRAND_METFORMIN_SR,
            candidates=[SYNTHETIC_GENERIC_METFORMIN_SR],
            workflow_state=ScanWorkflowState.READY_FOR_MATCHING,
            units_per_month=60.0,
        )

        assert result.tier == MatchTier.EXACT
        assert len(result.matched_alternatives) == 1
        alt = result.matched_alternatives[0]
        assert alt.generic_product_id == "synth_gen_metformin_sr_500"
        assert alt.savings is not None

        # Verify exact math: brand unit = ₹4.0, generic unit = ₹1.25
        # (4.0 - 1.25) * 60 = 2.75 * 60 = ₹165.00 / month; ₹1980.00 / year
        assert alt.savings.monthly_savings_inr == 165.0
        assert alt.savings.yearly_savings_inr == 1980.0
        assert result.disclaimer == MANDATORY_DISCLAIMER

    def test_combination_salt_exact_match_with_reversed_order(self):
        result = DeterministicMatcher.match(
            scanned=SYNTHETIC_BRAND_AUGMENTIN_625,
            candidates=[SYNTHETIC_GENERIC_AUGMENTIN_625],
            workflow_state=ScanWorkflowState.READY_FOR_MATCHING,
            units_per_month=30.0,
        )

        assert result.tier == MatchTier.EXACT
        assert len(result.matched_alternatives) == 1
        alt = result.matched_alternatives[0]
        assert alt.savings is not None
        # brand unit = 22.0, generic unit = 6.5
        # (22.0 - 6.5) * 30 = 15.5 * 30 = ₹465.00 / month
        assert alt.savings.monthly_savings_inr == 465.0
        assert alt.savings.yearly_savings_inr == 5580.0


class TestIndependentDimensionMismatches:
    """Tests verifying that mismatch on ANY of the 5 canonical dimensions blocks EXACT."""

    def test_dimension_1_route_mismatch_blocks_exact(self):
        oral_med = SYNTHETIC_BRAND_METFORMIN_SR
        topical_cand = make_synthetic_medicine(
            product_id="topical_cand",
            name="Metformin Topical Cream",
            salts=oral_med.salts,
            dosage_form=DosageForm.CREAM,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.TOPICAL,  # Route differs!
            is_brand=False,
        )

        tier, reason = evaluate_single_pair(oral_med, topical_cand)
        assert tier == MatchTier.NONE
        assert "route differs" in reason.lower()

        result = DeterministicMatcher.match(oral_med, [topical_cand])
        assert result.tier == MatchTier.NONE

    def test_dimension_2_salt_moiety_mismatch_blocks_exact(self):
        med_metformin = SYNTHETIC_BRAND_METFORMIN_SR
        cand_glimepiride = make_synthetic_medicine(
            product_id="cand_glimepiride",
            name="Glimepiride Tablets 2mg",
            salts=[
                ActiveSaltMoiety(
                    salt_name="glimepiride",
                    strength_value=2.0,
                    strength_unit="mg",
                    per_unit="unit",
                )
            ],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
            is_brand=False,
        )

        tier, reason = evaluate_single_pair(med_metformin, cand_glimepiride)
        assert tier == MatchTier.NONE
        assert "active ingredients do not match" in reason.lower()

    def test_dimension_3_salt_modifier_difference_downgrades_to_close(self):
        """Clinical safety: Besylate vs Maleate is NOT automatically EXACT."""
        med_besylate = make_synthetic_medicine(
            product_id="amlod_besylate",
            name="Amlodipine Besylate 5mg",
            salts=[
                ActiveSaltMoiety(
                    salt_name="amlodipine",
                    salt_modifier="besylate",
                    strength_value=5.0,
                    strength_unit="mg",
                    per_unit="unit",
                )
            ],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
        )
        cand_maleate = make_synthetic_medicine(
            product_id="amlod_maleate",
            name="Amlodipine Maleate 5mg",
            salts=[
                ActiveSaltMoiety(
                    salt_name="amlodipine",
                    salt_modifier="maleate",  # Different modifier!
                    strength_value=5.0,
                    strength_unit="mg",
                    per_unit="unit",
                )
            ],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
            is_brand=False,
        )

        tier, reason = evaluate_single_pair(med_besylate, cand_maleate)
        assert tier == MatchTier.CLOSE
        assert "chemical modifier differs" in reason
        assert "Pharmacist to confirm" in reason

        result = DeterministicMatcher.match(med_besylate, [cand_maleate])
        assert result.tier == MatchTier.CLOSE
        # Savings MUST be suppressed on CLOSE tier
        assert result.matched_alternatives[0].savings is None

    def test_dimension_4a_strength_mismatch_blocks_exact(self):
        med_500 = SYNTHETIC_BRAND_METFORMIN_SR
        cand_250 = make_synthetic_medicine(
            product_id="cand_metformin_250",
            name="Metformin SR 250mg",
            salts=[
                ActiveSaltMoiety(
                    salt_name="metformin",
                    salt_modifier="hydrochloride",
                    strength_value=250.0,  # Half strength!
                    strength_unit="mg",
                    per_unit="unit",
                )
            ],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.SR,
            route=AdministrationRoute.ORAL,
            is_brand=False,
        )

        tier, reason = evaluate_single_pair(med_500, cand_250)
        assert tier == MatchTier.CLOSE
        assert "strength differs" in reason.lower()

    def test_dimension_4b_denominator_mismatch_blocks_exact(self):
        med_tab = make_synthetic_medicine(
            product_id="pcm_tab",
            name="Paracetamol Tablets 250mg",
            salts=[
                ActiveSaltMoiety(
                    salt_name="paracetamol",
                    strength_value=250.0,
                    strength_unit="mg",
                    per_unit="unit",  # Per tablet
                )
            ],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
        )
        cand_syr = make_synthetic_medicine(
            product_id="pcm_syr",
            name="Paracetamol Syrup 250mg/5ml",
            salts=[
                ActiveSaltMoiety(
                    salt_name="paracetamol",
                    strength_value=250.0,
                    strength_unit="mg",
                    per_unit="5ml",  # Per 5ml liquid!
                )
            ],
            dosage_form=DosageForm.SYRUP,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
            is_brand=False,
        )

        tier, reason = evaluate_single_pair(med_tab, cand_syr)
        assert tier == MatchTier.CLOSE
        assert "denominator differs" in reason.lower()

    def test_dimension_5_dosage_form_mismatch_blocks_exact(self):
        med_tab = SYNTHETIC_BRAND_METFORMIN_SR
        cand_cap = make_synthetic_medicine(
            product_id="cand_cap",
            name="Metformin SR Capsules 500mg",
            salts=med_tab.salts,
            dosage_form=DosageForm.CAPSULE,  # Capsule vs Tablet!
            release_type=ReleaseType.SR,
            route=AdministrationRoute.ORAL,
            is_brand=False,
        )

        tier, reason = evaluate_single_pair(med_tab, cand_cap)
        assert tier == MatchTier.CLOSE
        assert "dosage form differs" in reason.lower()

    def test_dimension_6_release_type_sr_vs_ir_mismatch_blocks_exact(self):
        """CRITICAL SAFETY TEST: SR vs IR must NEVER be EXACT."""
        tier, reason = evaluate_single_pair(
            SYNTHETIC_BRAND_METFORMIN_SR,
            SYNTHETIC_GENERIC_METFORMIN_IR,
        )

        assert tier == MatchTier.CLOSE
        assert "release type differs" in reason.lower()

        result = DeterministicMatcher.match(
            SYNTHETIC_BRAND_METFORMIN_SR,
            [SYNTHETIC_GENERIC_METFORMIN_IR],
        )
        assert result.tier == MatchTier.CLOSE
        assert result.matched_alternatives[0].savings is None


class TestCombinationEdgeCases:
    """Tests for combination medicines with missing, extra, or mismatched salts."""

    def test_combination_missing_salt_is_close_not_exact(self):
        # Scanned has Amox + Clav; candidate only has Amox
        cand_amox_only = make_synthetic_medicine(
            product_id="amox_plain",
            name="Amoxicillin Tablets 500mg",
            salts=[
                ActiveSaltMoiety(
                    salt_name="amoxicillin",
                    strength_value=500.0,
                    strength_unit="mg",
                    per_unit="unit",
                )
            ],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
            is_brand=False,
        )

        tier, reason = evaluate_single_pair(SYNTHETIC_BRAND_AUGMENTIN_625, cand_amox_only)
        assert tier == MatchTier.CLOSE
        assert "partial active ingredient overlap" in reason.lower()

        result = DeterministicMatcher.match(SYNTHETIC_BRAND_AUGMENTIN_625, [cand_amox_only])
        assert result.tier == MatchTier.CLOSE
        assert result.matched_alternatives[0].savings is None


class TestUnknownAttributesAndQuarantine:
    """Tests ensuring incomplete, ambiguous, or quarantined records fail closed."""

    def test_scanned_unknown_dosage_form_blocks_exact(self):
        med = make_synthetic_medicine(
            product_id="med_unknown_form",
            name="Unknown Form Drug",
            salts=[ActiveSaltMoiety(salt_name="metformin", strength_value=500.0, strength_unit="mg")],
            dosage_form=DosageForm.UNKNOWN,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
        )
        result = DeterministicMatcher.match(med, [SYNTHETIC_GENERIC_METFORMIN_SR])
        assert result.tier == MatchTier.NONE
        assert any("dosage form is unknown" in w.lower() for w in result.warnings)

    def test_scanned_unknown_release_type_blocks_exact(self):
        med = make_synthetic_medicine(
            product_id="med_unknown_rel",
            name="Unknown Release Drug",
            salts=[ActiveSaltMoiety(salt_name="metformin", strength_value=500.0, strength_unit="mg")],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.UNKNOWN,
            route=AdministrationRoute.ORAL,
        )
        result = DeterministicMatcher.match(med, [SYNTHETIC_GENERIC_METFORMIN_SR])
        assert result.tier == MatchTier.NONE
        assert any("release type is unknown" in w.lower() for w in result.warnings)

    def test_quarantined_scanned_medicine_returns_none(self):
        med = make_synthetic_medicine(
            product_id="med_quarantined",
            name="Quarantined Drug",
            salts=[ActiveSaltMoiety(salt_name="metformin", strength_value=500.0, strength_unit="mg")],
            is_quarantined=True,
            quarantine_reason="Ambiguous salt split in raw ETL",
        )
        result = DeterministicMatcher.match(med, [SYNTHETIC_GENERIC_METFORMIN_SR])
        assert result.tier == MatchTier.NONE
        assert any("quarantined" in w.lower() for w in result.warnings)


class TestWorkflowStateGates:
    """Tests verifying workflow states gate matcher execution."""

    @pytest.mark.parametrize(
        "state",
        [
            ScanWorkflowState.REJECT_IMAGE,
            ScanWorkflowState.RETAKE_REQUIRED,
            ScanWorkflowState.EXTRACTION_INCOMPLETE,
            ScanWorkflowState.NEEDS_USER_CONFIRMATION,
            ScanWorkflowState.RECOVERABLE_ERROR,
        ],
    )
    def test_non_ready_workflow_state_immediately_returns_none(self, state):
        result = DeterministicMatcher.match(
            scanned=SYNTHETIC_BRAND_METFORMIN_SR,
            candidates=[SYNTHETIC_GENERIC_METFORMIN_SR],
            workflow_state=state,
        )
        assert result.tier == MatchTier.NONE
        assert result.workflow_state == state
        assert len(result.matched_alternatives) == 0


class TestPricingAndSavingsSuppression:
    """Tests ensuring invalid, missing, or negative savings are strictly suppressed."""

    def test_missing_brand_price_suppresses_savings(self):
        med_no_price = make_synthetic_medicine(
            product_id="med_no_price",
            name="Unpriced Brand SR",
            salts=SYNTHETIC_BRAND_METFORMIN_SR.salts,
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.SR,
            route=AdministrationRoute.ORAL,
        )
        med_no_price.price = None  # Price not readable from packaging

        result = DeterministicMatcher.match(
            scanned=med_no_price,
            candidates=[SYNTHETIC_GENERIC_METFORMIN_SR],
        )
        assert result.tier == MatchTier.EXACT
        # Candidate matched, but savings MUST be suppressed
        assert result.matched_alternatives[0].savings is None
        assert any("missing price record" in w.lower() for w in result.warnings)

    def test_generic_more_expensive_than_brand_suppresses_savings(self):
        # Brand unit = ₹1.0, Generic unit = ₹2.0
        cheap_brand = make_synthetic_medicine(
            product_id="cheap_brand",
            name="Cheap Brand",
            salts=SYNTHETIC_BRAND_METFORMIN_SR.salts,
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.SR,
            route=AdministrationRoute.ORAL,
            mrp=10.0,
            pack_count=10.0,  # unit ₹1.0
        )
        expensive_gen = make_synthetic_medicine(
            product_id="exp_gen",
            name="Expensive Generic",
            salts=SYNTHETIC_BRAND_METFORMIN_SR.salts,
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.SR,
            route=AdministrationRoute.ORAL,
            mrp=20.0,
            pack_count=10.0,  # unit ₹2.0
            is_brand=False,
        )

        result = DeterministicMatcher.match(
            scanned=cheap_brand,
            candidates=[expensive_gen],
        )
        assert result.tier == MatchTier.EXACT
        assert result.matched_alternatives[0].savings is None
        assert any("exceeds brand price" in w.lower() for w in result.warnings)


class TestNtiPrecautionWarning:
    """Tests verifying Narrow Therapeutic Index triggers precaution warning."""

    def test_nti_flag_triggers_prominent_doctor_warning(self):
        nti_med = make_synthetic_medicine(
            product_id="synth_levothyroxine",
            name="Levothyroxine 100mcg",
            salts=[
                ActiveSaltMoiety(
                    salt_name="levothyroxine",
                    strength_value=100.0,
                    strength_unit="mcg",
                    per_unit="unit",
                )
            ],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
            is_nti=True,  # NTI flag!
        )
        cand = make_synthetic_medicine(
            product_id="synth_gen_levo",
            name="Levothyroxine Tablets 100mcg",
            salts=nti_med.salts,
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
            route=AdministrationRoute.ORAL,
            is_brand=False,
        )

        result = DeterministicMatcher.match(nti_med, [cand])
        assert result.tier == MatchTier.EXACT
        assert any("narrow therapeutic index" in w.lower() for w in result.warnings)
