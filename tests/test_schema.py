"""Unit tests for Phase 1A: Domain schemas, contracts, state transitions, and safety invariants."""

import pytest
from pydantic import ValidationError

from ml.schemas.enums import (
    AdministrationRoute,
    DosageForm,
    LegibilityGrade,
    MatchTier,
    ReleaseType,
    RxSchedule,
    ScanWorkflowState,
)
from ml.schemas.quality import ImageQualityCheck, ImageQualityReport
from ml.schemas.extraction import (
    ExtractedPackSize,
    ExtractionFieldConfidence,
    PrintedCompositionItem,
    RawMedicineExtraction,
)
from ml.schemas.canonical import (
    ActiveSaltMoiety,
    CanonicalMedicine,
    PriceRecord,
    ProvenanceRecord,
)
from ml.schemas.matcher import (
    MANDATORY_DISCLAIMER,
    MatchAlternative,
    MatchResult,
    SavingsCalculation,
    validate_state_tier_combination,
)
from ml.schemas.api import ProblemDetails, ScanResponse


class TestWorkflowStatesAndTiers:
    """Tests ensuring perception workflow states and clinical match tiers are strictly decoupled."""

    def test_legal_state_tier_combinations(self):
        # READY_FOR_MATCHING can legally pair with any tier
        validate_state_tier_combination(ScanWorkflowState.READY_FOR_MATCHING, MatchTier.EXACT)
        validate_state_tier_combination(ScanWorkflowState.READY_FOR_MATCHING, MatchTier.CLOSE)
        validate_state_tier_combination(ScanWorkflowState.READY_FOR_MATCHING, MatchTier.NONE)

        # Non-ready states can ONLY pair with NONE
        validate_state_tier_combination(ScanWorkflowState.REJECT_IMAGE, MatchTier.NONE)
        validate_state_tier_combination(ScanWorkflowState.RETAKE_REQUIRED, MatchTier.NONE)
        validate_state_tier_combination(ScanWorkflowState.EXTRACTION_INCOMPLETE, MatchTier.NONE)
        validate_state_tier_combination(ScanWorkflowState.NEEDS_USER_CONFIRMATION, MatchTier.NONE)
        validate_state_tier_combination(ScanWorkflowState.RECOVERABLE_ERROR, MatchTier.NONE)

    def test_illegal_state_tier_combinations_raise_error(self):
        # Non-ready states paired with EXACT or CLOSE must be rejected
        with pytest.raises(ValueError, match="Invalid state-tier combination"):
            validate_state_tier_combination(ScanWorkflowState.NEEDS_USER_CONFIRMATION, MatchTier.EXACT)

        with pytest.raises(ValueError, match="Invalid state-tier combination"):
            validate_state_tier_combination(ScanWorkflowState.EXTRACTION_INCOMPLETE, MatchTier.EXACT)

        with pytest.raises(ValueError, match="Invalid state-tier combination"):
            validate_state_tier_combination(ScanWorkflowState.RETAKE_REQUIRED, MatchTier.EXACT)

        with pytest.raises(ValueError, match="Invalid state-tier combination"):
            validate_state_tier_combination(ScanWorkflowState.REJECT_IMAGE, MatchTier.CLOSE)


class TestRawExtractionSchema:
    """Tests for raw perception extraction validation and safety guards."""

    def test_valid_full_extraction(self):
        extraction = RawMedicineExtraction(
            is_medicine_pack=True,
            brand_name="Glycomet SR 500",
            manufacturer="USV Ltd",
            printed_composition=[
                PrintedCompositionItem(
                    salt_text="Metformin Hydrochloride",
                    strength_value=500.0,
                    strength_unit="mg",
                    per="tablet"
                )
            ],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.SR,
            route=AdministrationRoute.ORAL,
            pack_size=ExtractedPackSize(count=10.0, unit="tablets"),
            mrp_inr=42.50,
            expiry="2027-08",
            rx_schedule=RxSchedule.SCHEDULE_H,
            legibility=LegibilityGrade.GOOD,
            field_confidence=ExtractionFieldConfidence(
                brand_name=0.95,
                composition=0.90,
                strength=0.92,
                dosage_form=0.98,
                release_type=0.88,
                mrp_inr=0.85
            )
        )
        assert extraction.brand_name == "Glycomet SR 500"
        assert extraction.printed_composition[0].strength_value == 500.0
        assert extraction.expiry == "2027-08"

    def test_unreadable_critical_fields_remain_none(self):
        extraction = RawMedicineExtraction(
            is_medicine_pack=True,
            brand_name=None,
            printed_composition=[
                PrintedCompositionItem(
                    salt_text="Metformin Hydrochloride",
                    strength_value=None,  # Unreadable strength
                    strength_unit=None
                )
            ],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.UNKNOWN,
            mrp_inr=None,
            expiry=None
        )
        assert extraction.brand_name is None
        assert extraction.printed_composition[0].strength_value is None
        assert extraction.release_type == ReleaseType.UNKNOWN

    def test_non_medicine_pack_cannot_have_medicine_fields(self):
        with pytest.raises(ValidationError, match="brand_name and composition must be empty"):
            RawMedicineExtraction(
                is_medicine_pack=False,
                brand_name="Some Drug",
                printed_composition=[]
            )

    def test_invalid_expiry_format_rejected(self):
        with pytest.raises(ValidationError, match="Expiry must be formatted as YYYY-MM"):
            RawMedicineExtraction(
                is_medicine_pack=True,
                expiry="12-2027"  # Wrong format
            )

    def test_confidence_scores_bounded(self):
        with pytest.raises(ValidationError):
            ExtractionFieldConfidence(brand_name=1.5)  # Exceeds 1.0

        with pytest.raises(ValidationError):
            ExtractionFieldConfidence(strength=-0.1)  # Below 0.0


class TestCanonicalMedicineAndPrice:
    """Tests for canonical medicine representation, provenance, and pricing."""

    def test_canonical_salt_sanitization(self):
        salt = ActiveSaltMoiety(
            salt_name="  Metformin Hydrochloride  ",
            strength_value=500.0,
            strength_unit=" MG "
        )
        assert salt.salt_name == "metformin hydrochloride"
        assert salt.strength_unit == "mg"

    def test_price_record_unit_price_calculation(self):
        provenance = ProvenanceRecord(
            source_name="PMBI_JAN_AUSHADHI",
            source_row_id="123",
            raw_text="Metformin Tablets IP 500mg",
            retrieval_date="2026-10-13",
            price_date="2026-10-12"
        )
        price = PriceRecord(
            pack_mrp_inr=12.50,
            pack_count=10.0,
            unit_price_inr=1.25,
            price_date="2026-10-12",
            is_verified_current=True,
            provenance=provenance
        )
        assert price.unit_price_inr == 1.25

    def test_mismatched_unit_price_rejected(self):
        provenance = ProvenanceRecord(
            source_name="PMBI_JAN_AUSHADHI",
            raw_text="Metformin 500mg",
            retrieval_date="2026-10-13"
        )
        with pytest.raises(ValidationError, match="does not match pack_mrp_inr / pack_count"):
            PriceRecord(
                pack_mrp_inr=100.0,
                pack_count=10.0,
                unit_price_inr=5.0,  # Wrong: should be 10.0
                price_date="2026-10-12",
                provenance=provenance
            )

    def test_unquarantined_medicine_requires_salts(self):
        with pytest.raises(ValidationError, match="must have at least one active salt"):
            CanonicalMedicine(
                product_id="med_001",
                name="Empty Salts Tablet",
                salts=[],  # Illegal when is_quarantined=False
                dosage_form=DosageForm.TABLET,
                release_type=ReleaseType.IR,
                route=AdministrationRoute.ORAL,
                is_quarantined=False
            )


class TestSavingsCalculation:
    """Tests ensuring price comparison and savings math are mathematically and clinically valid."""

    def test_valid_savings_arithmetic(self):
        calc = SavingsCalculation(
            brand_unit_price_inr=4.25,
            generic_unit_price_inr=1.25,
            doses_per_day=2.0,
            units_per_month=60.0,
            monthly_savings_inr=180.0,  # (4.25 - 1.25) * 60 = 180.0
            yearly_savings_inr=2160.0,  # 180.0 * 12 = 2160.0
            price_as_of="2026-10-12"
        )
        assert calc.monthly_savings_inr == 180.0
        assert calc.yearly_savings_inr == 2160.0

    def test_negative_savings_rejected(self):
        with pytest.raises(ValidationError, match="Generic unit price .* exceeds brand unit price"):
            SavingsCalculation(
                brand_unit_price_inr=1.00,
                generic_unit_price_inr=2.50,  # Generic is more expensive
                units_per_month=60.0,
                monthly_savings_inr=0.0,
                yearly_savings_inr=0.0,
                price_as_of="2026-10-12"
            )

    def test_arithmetic_mismatch_rejected(self):
        with pytest.raises(ValidationError, match="does not match"):
            SavingsCalculation(
                brand_unit_price_inr=10.0,
                generic_unit_price_inr=2.0,
                units_per_month=30.0,
                monthly_savings_inr=500.0,  # Wrong: should be (10-2)*30 = 240.0
                yearly_savings_inr=6000.0,
                price_as_of="2026-10-12"
            )


class TestMatchResultSafetyInvariants:
    """Critical safety tests verifying deterministic matching boundaries."""

    def test_exact_match_with_valid_savings(self):
        savings = SavingsCalculation(
            brand_unit_price_inr=4.0,
            generic_unit_price_inr=1.0,
            units_per_month=60.0,
            monthly_savings_inr=180.0,
            yearly_savings_inr=2160.0,
            price_as_of="2026-10-12"
        )
        alt = MatchAlternative(
            generic_product_id="gen_001",
            generic_name="Metformin Tablets IP 500mg (Jan Aushadhi)",
            strip_mrp_inr=10.0,
            pack_count=10.0,
            unit_price_inr=1.0,
            price_date="2026-10-12",
            savings=savings
        )
        result = MatchResult(
            tier=MatchTier.EXACT,
            workflow_state=ScanWorkflowState.READY_FOR_MATCHING,
            matched_alternatives=[alt]
        )
        assert result.tier == MatchTier.EXACT
        assert result.disclaimer == MANDATORY_DISCLAIMER

    def test_close_tier_prohibited_from_containing_savings(self):
        savings = SavingsCalculation(
            brand_unit_price_inr=4.0,
            generic_unit_price_inr=1.0,
            units_per_month=60.0,
            monthly_savings_inr=180.0,
            yearly_savings_inr=2160.0,
            price_as_of="2026-10-12"
        )
        alt = MatchAlternative(
            generic_product_id="gen_002",
            generic_name="Metformin IR 500mg",
            strip_mrp_inr=10.0,
            pack_count=10.0,
            unit_price_inr=1.0,
            price_date="2026-10-12",
            savings=savings  # PROHIBITED ON CLOSE TIER!
        )
        with pytest.raises(ValidationError, match="Non-EXACT tier 'close' is prohibited from containing savings"):
            MatchResult(
                tier=MatchTier.CLOSE,
                workflow_state=ScanWorkflowState.READY_FOR_MATCHING,
                matched_alternatives=[alt]
            )

    def test_none_tier_prohibited_from_containing_savings(self):
        savings = SavingsCalculation(
            brand_unit_price_inr=4.0,
            generic_unit_price_inr=1.0,
            units_per_month=60.0,
            monthly_savings_inr=180.0,
            yearly_savings_inr=2160.0,
            price_as_of="2026-10-12"
        )
        alt = MatchAlternative(
            generic_product_id="gen_003",
            generic_name="Unrelated Medicine",
            strip_mrp_inr=10.0,
            pack_count=10.0,
            unit_price_inr=1.0,
            price_date="2026-10-12",
            savings=savings  # PROHIBITED ON NONE TIER!
        )
        with pytest.raises(ValidationError, match="Non-EXACT tier 'none' is prohibited from containing savings"):
            MatchResult(
                tier=MatchTier.NONE,
                workflow_state=ScanWorkflowState.READY_FOR_MATCHING,
                matched_alternatives=[alt]
            )

    def test_unconfirmed_workflow_state_cannot_have_exact_tier(self):
        with pytest.raises(ValueError, match="Invalid state-tier combination"):
            MatchResult(
                tier=MatchTier.EXACT,
                workflow_state=ScanWorkflowState.NEEDS_USER_CONFIRMATION,
                matched_alternatives=[]
            )

    def test_exact_tier_requires_alternatives(self):
        with pytest.raises(ValidationError, match="cannot claim EXACT tier with zero matched alternatives"):
            MatchResult(
                tier=MatchTier.EXACT,
                workflow_state=ScanWorkflowState.READY_FOR_MATCHING,
                matched_alternatives=[]
            )

    def test_mandatory_disclaimer_cannot_be_altered_or_removed(self):
        with pytest.raises(ValidationError, match="Mandatory disclaimer cannot be omitted or altered"):
            MatchResult(
                tier=MatchTier.NONE,
                workflow_state=ScanWorkflowState.READY_FOR_MATCHING,
                disclaimer="Generic medicine is always better."  # Prohibited replacement!
            )


class TestApiSchemas:
    """Tests for API responses and RFC 7807 problem details."""

    def test_scan_response_contract(self):
        resp = ScanResponse(
            scan_id="scan_123456",
            status=ScanWorkflowState.READY_FOR_MATCHING,
            next_action="ready_to_match",
            latency_ms=1240
        )
        assert resp.status == ScanWorkflowState.READY_FOR_MATCHING
        assert resp.disclaimer == MANDATORY_DISCLAIMER

    def test_rfc7807_problem_details(self):
        problem = ProblemDetails(
            type="https://sastidawai.org/errors/low-confidence",
            title="Extraction Confidence Low",
            status=422,
            detail="Strength value could not be confidently read from packaging foil.",
            code="LOW_CONFIDENCE"
        )
        assert problem.status == 422
        assert problem.code == "LOW_CONFIDENCE"
        assert problem.disclaimer == MANDATORY_DISCLAIMER
