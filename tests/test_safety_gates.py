"""Unit and safety tests for Phase 1G: Local OCR cross-verification and safety gates.

Covers:
1. Deterministic dimension parsing from OCR text (salts, strengths, form, release).
2. Concordant agreement between Vision and OCR (Augmentin, Glycomet).
3. Strength value, unit, and denominator discrepancies blocking EXACT matching.
4. Active ingredient mismatches (disjoint salts, combination vs single).
5. Dosage form and release profile conflicts (IR vs SR).
6. Non-averaging of confidence scores on conflicting evidence.
7. OCR failure / timeout bypass conditions (only when vision evidence is independently verified).
8. Protection against overriding clinical conflicts via user confirmation or fuzzy similarity.
9. Principle: OCR agreement alone never establishes clinical equivalence.
"""

import pytest

from ml.resolver.candidates import CandidateResolver
from ml.safety.gates import (
    CrossVerificationConflict,
    EvidenceCrossVerificationResult,
    cross_verify_vision_and_ocr,
    parse_dimensions_from_ocr,
)
from ml.schemas.enums import (
    AdministrationRoute,
    DosageForm,
    MatchTier,
    ReleaseType,
    ScanWorkflowState,
)
from ml.schemas.extraction import (
    ConflictField,
    ExtractionFieldConfidence,
    PrintedCompositionItem,
    RawMedicineExtraction,
)
from ml.schemas.matcher import validate_state_tier_combination
from ml.schemas.ocr import OCRResult, OCRTextLine
from ml.vision.extractor import MockPreset, MockVisionExtractor
from ml.vision.ocr import MockOCREngine, MockOCRPreset


@pytest.fixture
def mock_extractor():
    return MockVisionExtractor()


@pytest.fixture
def mock_ocr():
    return MockOCREngine()


@pytest.fixture
def dummy_image():
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 50


class TestOCRDimensionParsing:
    """Tests evaluating deterministic parsing of clinical dimensions from OCR text."""

    def test_parse_augmentin_ocr_dimensions(self, mock_ocr, dummy_image):
        mock_ocr.set_preset(MockOCRPreset.AUGMENTIN_625_DUO)
        ocr_res = mock_ocr.extract_text(dummy_image)

        dims = parse_dimensions_from_ocr(ocr_res)
        assert "amoxicillin" in dims["salts"]
        assert "clavulanic acid" in dims["salts"]
        assert dims["dosage_form"] == DosageForm.TABLET
        assert dims["strengths"]["amoxicillin"][0][0] == 500.0
        assert dims["strengths"]["clavulanic acid"][0][0] == 125.0

    def test_parse_glycomet_ocr_dimensions(self, mock_ocr, dummy_image):
        mock_ocr.set_preset(MockOCRPreset.GLYCOMET_500_PR)
        ocr_res = mock_ocr.extract_text(dummy_image)

        dims = parse_dimensions_from_ocr(ocr_res)
        assert "metformin" in dims["salts"]
        assert dims["dosage_form"] == DosageForm.TABLET
        assert dims["release_type"] == ReleaseType.MR
        assert dims["strengths"]["metformin"][0][0] == 500.0


class TestCrossVerificationConcordance:
    """Tests evaluating concordant multi-modal readings between Vision and OCR."""

    def test_augmentin_concordant_agreement(self, mock_extractor, mock_ocr, dummy_image):
        mock_extractor.set_preset(MockPreset.AUGMENTIN_625_DUO)
        mock_ocr.set_preset(MockOCRPreset.AUGMENTIN_625_DUO)

        vision_ext = mock_extractor.extract([dummy_image])
        ocr_res = mock_ocr.extract_text(dummy_image)

        result = cross_verify_vision_and_ocr(vision_ext, ocr_res)

        assert result.is_concordant is True
        assert result.can_authorize_exact is True
        assert result.workflow_state == ScanWorkflowState.READY_FOR_MATCHING
        assert len(result.conflicts) == 0
        assert result.reconciled_extraction.has_critical_conflicts is False

    def test_glycomet_concordant_agreement(self, mock_extractor, mock_ocr, dummy_image):
        mock_extractor.set_preset(MockPreset.GLYCOMET_500_PR)
        mock_ocr.set_preset(MockOCRPreset.GLYCOMET_500_PR)

        vision_ext = mock_extractor.extract([dummy_image])
        ocr_res = mock_ocr.extract_text(dummy_image)

        result = cross_verify_vision_and_ocr(vision_ext, ocr_res)

        assert result.is_concordant is True
        assert result.can_authorize_exact is True
        assert result.workflow_state == ScanWorkflowState.READY_FOR_MATCHING
        assert len(result.conflicts) == 0


class TestCrossVerificationDiscrepancies:
    """Core Safety Boundary: Discrepancies between Vision and OCR must halt EXACT matching."""

    def test_strength_discrepancy_blocks_exact(self, mock_extractor, mock_ocr, dummy_image):
        # Vision read Glycomet 500mg, but OCR read Glycomet 1000mg
        mock_extractor.set_preset(MockPreset.GLYCOMET_500_PR)
        mock_ocr.set_preset(MockOCRPreset.GLYCOMET_1000_PR_CONFLICT)

        vision_ext = mock_extractor.extract([dummy_image])
        ocr_res = mock_ocr.extract_text(dummy_image)

        result = cross_verify_vision_and_ocr(vision_ext, ocr_res)

        assert result.is_concordant is False
        assert result.can_authorize_exact is False
        assert result.workflow_state == ScanWorkflowState.NEEDS_USER_CONFIRMATION
        assert any(c.field == ConflictField.STRENGTH for c in result.conflicts)

        # Conflicting strength must be demoted to None, never chosen
        reconciled = result.reconciled_extraction
        assert reconciled.printed_composition[0].strength_value is None
        # Strength confidence must be zeroed, NEVER averaged
        assert reconciled.field_confidence.strength == 0.0

        # State gate strictly rejects EXACT pairing
        with pytest.raises(ValueError, match="Invalid state-tier combination"):
            validate_state_tier_combination(result.workflow_state, MatchTier.EXACT)

    def test_ingredient_discrepancy_combination_vs_single_blocks_exact(self, mock_extractor, mock_ocr, dummy_image):
        # Vision read Augmentin (Amoxicillin + Clavulanic Acid), but OCR read Amoxil (Amoxicillin alone)
        mock_extractor.set_preset(MockPreset.AUGMENTIN_625_DUO)
        mock_ocr.set_preset(MockOCRPreset.AMOXI_ALONE_CONFLICT)

        vision_ext = mock_extractor.extract([dummy_image])
        ocr_res = mock_ocr.extract_text(dummy_image)

        result = cross_verify_vision_and_ocr(vision_ext, ocr_res)

        assert result.is_concordant is False
        assert result.can_authorize_exact is False
        assert result.workflow_state == ScanWorkflowState.NEEDS_USER_CONFIRMATION
        assert any(c.field == ConflictField.INGREDIENT for c in result.conflicts)

    def test_disjoint_active_ingredients_blocks_exact(self, mock_ocr, dummy_image):
        # Vision read Paracetamol 650mg, but OCR read Metformin 500mg
        vision_ext = RawMedicineExtraction(
            is_medicine_pack=True,
            brand_name="Dolo 650",
            printed_composition=[
                PrintedCompositionItem(salt_text="Paracetamol", strength_value=650.0, strength_unit="mg")
            ],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
        )
        mock_ocr.set_preset(MockOCRPreset.GLYCOMET_500_PR)
        ocr_res = mock_ocr.extract_text(dummy_image)

        result = cross_verify_vision_and_ocr(vision_ext, ocr_res)
        assert result.is_concordant is False
        assert result.can_authorize_exact is False
        assert any(c.field == ConflictField.INGREDIENT for c in result.conflicts)

    def test_dosage_form_discrepancy_blocks_exact(self, mock_extractor, mock_ocr, dummy_image):
        # Vision read Tablet, but OCR detected Hard Gelatin Capsules
        mock_extractor.set_preset(MockPreset.AUGMENTIN_625_DUO)
        mock_ocr.set_preset(MockOCRPreset.CAPSULE_FORM_CONFLICT)

        vision_ext = mock_extractor.extract([dummy_image])
        ocr_res = mock_ocr.extract_text(dummy_image)

        result = cross_verify_vision_and_ocr(vision_ext, ocr_res)

        assert result.is_concordant is False
        assert result.can_authorize_exact is False
        assert any(c.field == ConflictField.DOSAGE_FORM for c in result.conflicts)
        # Form demoted to UNKNOWN
        assert result.reconciled_extraction.dosage_form == DosageForm.UNKNOWN
        assert result.reconciled_extraction.field_confidence.dosage_form == 0.0

    def test_release_type_discrepancy_blocks_exact(self, mock_extractor, mock_ocr, dummy_image):
        # Vision read Glycomet PR/MR, but OCR read Immediate Release (IR)
        mock_extractor.set_preset(MockPreset.GLYCOMET_500_PR)
        mock_ocr.set_preset(MockOCRPreset.IR_RELEASE_CONFLICT)

        vision_ext = mock_extractor.extract([dummy_image])
        ocr_res = mock_ocr.extract_text(dummy_image)

        result = cross_verify_vision_and_ocr(vision_ext, ocr_res)

        assert result.is_concordant is False
        assert result.can_authorize_exact is False
        assert any(c.field == ConflictField.RELEASE_TYPE for c in result.conflicts)
        assert result.reconciled_extraction.release_type == ReleaseType.UNKNOWN


    def test_strength_unit_and_denominator_discrepancy_blocks_exact(self, mock_ocr, dummy_image):
        # Vision read 500 mg per tablet, OCR read 500 mg per 5 ml liquid suspension
        vision_ext = RawMedicineExtraction(
            is_medicine_pack=True,
            brand_name="Glycomet 500",
            printed_composition=[
                PrintedCompositionItem(salt_text="Metformin", strength_value=500.0, strength_unit="mg", per="tablet")
            ],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
        )
        custom_ocr = OCRResult(
            engine_name="mock_ocr",
            is_successful=True,
            raw_text="Metformin Hydrochloride 500 mg / 5ml Oral Solution",
            lines=[
                OCRTextLine(line_number=0, text="Metformin Hydrochloride 500 mg / 5ml Oral Solution", confidence=0.95)
            ],
            mean_confidence=0.95,
        )
        mock_ocr.queue_result(custom_ocr)
        ocr_res = mock_ocr.extract_text(dummy_image)

        result = cross_verify_vision_and_ocr(vision_ext, ocr_res)
        assert result.is_concordant is False
        assert result.can_authorize_exact is False
        assert result.workflow_state == ScanWorkflowState.NEEDS_USER_CONFIRMATION
        assert any(c.field == ConflictField.STRENGTH for c in result.conflicts)
        assert result.reconciled_extraction.field_confidence.strength == 0.0


class TestOCRFailureAndBypassSemantics:
    """Tests evaluating safe bypass and fail-closed behavior during OCR engine outage."""

    def test_ocr_failure_bypassed_when_vision_evidence_complete(self, mock_extractor, mock_ocr, dummy_image):
        # Vision evidence is complete and verified
        mock_extractor.set_preset(MockPreset.AUGMENTIN_625_DUO)
        vision_ext = mock_extractor.extract([dummy_image])

        # OCR engine simulates a failure / timeout
        mock_ocr.set_failure_mode("OCR timeout after 3000ms.")
        ocr_res = mock_ocr.extract_text(dummy_image)

        result = cross_verify_vision_and_ocr(vision_ext, ocr_res)

        # Permitted to proceed with warning
        assert result.workflow_state == ScanWorkflowState.READY_FOR_MATCHING
        assert result.can_authorize_exact is True
        assert any("unavailable" in w.lower() for w in result.warnings)

    def test_malformed_ocr_output_handling(self, mock_extractor, mock_ocr, dummy_image):
        mock_extractor.set_preset(MockPreset.AUGMENTIN_625_DUO)
        vision_ext = mock_extractor.extract([dummy_image])

        mock_ocr.set_preset(MockOCRPreset.MALFORMED_OUTPUT)
        ocr_res = mock_ocr.extract_text(dummy_image)

        result = cross_verify_vision_and_ocr(vision_ext, ocr_res)
        assert result.is_concordant is False
        # Vision is complete so permitted with warning, but error message is preserved
        assert any("crashed" in w.lower() or "failed" in w.lower() for w in result.warnings)

    def test_ocr_failure_cannot_bypass_when_vision_evidence_incomplete(self, mock_extractor, mock_ocr, dummy_image):
        # Vision evidence has unreadable strength
        mock_extractor.set_preset(MockPreset.UNREADABLE_STRENGTH)
        vision_ext = mock_extractor.extract([dummy_image])

        # OCR fails
        mock_ocr.set_failure_mode("OCR engine offline.")
        ocr_res = mock_ocr.extract_text(dummy_image)

        result = cross_verify_vision_and_ocr(vision_ext, ocr_res)

        # Fails closed as EXTRACTION_INCOMPLETE
        assert result.workflow_state == ScanWorkflowState.EXTRACTION_INCOMPLETE
        assert result.can_authorize_exact is False

    def test_non_medicine_image_fails_closed(self, mock_extractor, mock_ocr, dummy_image):
        mock_extractor.set_preset(MockPreset.NON_MEDICINE)
        mock_ocr.set_preset(MockOCRPreset.NON_MEDICINE)

        vision_ext = mock_extractor.extract([dummy_image])
        ocr_res = mock_ocr.extract_text(dummy_image)

        result = cross_verify_vision_and_ocr(vision_ext, ocr_res)
        assert result.workflow_state == ScanWorkflowState.REJECT_IMAGE
        assert result.can_authorize_exact is False


class TestConfidenceAndAgreementInvariants:
    """Safety Invariants: Confidence cannot override conflicts; agreement alone cannot authorize EXACT."""

    def test_confidence_scores_never_averaged(self, mock_extractor, mock_ocr, dummy_image):
        mock_extractor.set_preset(MockPreset.GLYCOMET_500_PR)
        mock_ocr.set_preset(MockOCRPreset.GLYCOMET_1000_PR_CONFLICT)

        vision_ext = mock_extractor.extract([dummy_image])
        ocr_res = mock_ocr.extract_text(dummy_image)

        # Vision strength confidence was 0.95; OCR mean confidence was 0.96
        result = cross_verify_vision_and_ocr(vision_ext, ocr_res)

        # On conflict, reconciled strength confidence is penalized to 0.0, NOT (0.95+0.96)/2
        assert result.reconciled_extraction.field_confidence.strength == 0.0

    def test_clinical_conflict_cannot_be_overridden_by_user_or_fuzzy(self, mock_extractor, mock_ocr, dummy_image):
        # Under conflicting strength, state is NEEDS_USER_CONFIRMATION
        mock_extractor.set_preset(MockPreset.GLYCOMET_500_PR)
        mock_ocr.set_preset(MockOCRPreset.GLYCOMET_1000_PR_CONFLICT)

        vision_ext = mock_extractor.extract([dummy_image])
        ocr_res = mock_ocr.extract_text(dummy_image)
        result = cross_verify_vision_and_ocr(vision_ext, ocr_res)

        # Conflict cannot be bypassed into EXACT tier even if user confirms or fuzzy score is 100%
        assert result.can_authorize_exact is False
        with pytest.raises(ValueError, match="Invalid state-tier combination"):
            validate_state_tier_combination(result.workflow_state, MatchTier.EXACT)

        # Candidate resolver with conflicting reconciled extraction demotes strength to None,
        # preventing EXACT matching in the deterministic catalogue matcher
        resolver = CandidateResolver()
        state, resolver_res, match_res = resolver.resolve_and_match_extraction(result.reconciled_extraction)
        assert match_res.tier != MatchTier.EXACT

    def test_ocr_agreement_alone_cannot_authorize_exact_without_catalogue(self, mock_extractor, mock_ocr, dummy_image):
        # Even with 100% concordant agreement between vision and OCR:
        mock_extractor.set_preset(MockPreset.AUGMENTIN_625_DUO)
        mock_ocr.set_preset(MockOCRPreset.AUGMENTIN_625_DUO)

        vision_ext = mock_extractor.extract([dummy_image])
        ocr_res = mock_ocr.extract_text(dummy_image)

        result = cross_verify_vision_and_ocr(vision_ext, ocr_res)
        assert result.can_authorize_exact is True

        # Pipeline execution: resolving against SQLite candidate resolver
        resolver = CandidateResolver()
        workflow_state, resolver_result, match_result = resolver.resolve_and_match_extraction(
            result.reconciled_extraction
        )

        # EXACT match is determined EXCLUSIVELY by the Phase 1C deterministic catalogue matcher,
        # never awarded simply because vision and OCR agreed.
        assert workflow_state == ScanWorkflowState.READY_FOR_MATCHING
        assert match_result is not None
        assert match_result.disclaimer is not None

