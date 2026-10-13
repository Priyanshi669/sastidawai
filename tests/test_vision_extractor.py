"""Unit and safety tests for Phase 1F: Vision Extraction Interface and Mock Provider.

Covers:
1. BaseVisionExtractor interface contract.
2. MockVisionExtractor standard presets (Augmentin, Glycomet, Dispersible).
3. Non-medicine image handling and schema invariant (brand/composition must be empty).
4. Safe abstention on unreadable or missing strength/composition (never inferred from brand).
5. Field-level confidence score preservation.
6. Error handling and simulated upstream provider failure.
7. Asynchronous extraction interface.
8. Decoupling workflow state from match tier: image quality success alone never produces EXACT.
"""

import pytest
from pydantic import ValidationError

from ml.schemas.enums import (
    AdministrationRoute,
    DosageForm,
    MatchTier,
    ReleaseType,
    ScanWorkflowState,
)
from ml.schemas.extraction import (
    ConflictField,
    ExtractionConflict,
    ExtractionFieldConfidence,
    PrintedCompositionItem,
    RawMedicineExtraction,
)
from ml.schemas.matcher import validate_state_tier_combination
from ml.vision.extractor import (
    BaseVisionExtractor,
    MockPreset,
    MockVisionExtractor,
)
from ml.vision.quality import ImageQualityValidator
from ml.vision.reconciliation import (
    can_authorize_exact_matching,
    determine_workflow_state,
    reconcile_extractions,
)


@pytest.fixture
def mock_extractor():
    return MockVisionExtractor()


@pytest.fixture
def sample_image_bytes():
    # Minimal 1x1 valid PNG bytes for provider call
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (100, 100), color="white").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def sharp_valid_image_bytes():
    from io import BytesIO
    import cv2
    import numpy as np
    from PIL import Image
    img = np.full((300, 300, 3), 128, dtype=np.uint8)
    for y in range(20, 280, 20):
        cv2.line(img, (20, y), (280, y), (0, 0, 0), 2)
        cv2.putText(img, "AMOXICILLIN 500mg", (30, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    buf = BytesIO()
    Image.fromarray(img).save(buf, format="PNG")
    return buf.getvalue()


class TestMockVisionExtractorPresets:
    """Tests evaluating standard synthetic extraction presets."""

    def test_augmentin_preset_extraction(self, mock_extractor, sample_image_bytes):
        mock_extractor.set_preset(MockPreset.AUGMENTIN_625_DUO)
        res = mock_extractor.extract([sample_image_bytes], request_id="req_001")

        assert res.is_medicine_pack is True
        assert res.brand_name == "Augmentin 625 Duo"
        assert res.dosage_form == DosageForm.TABLET
        assert res.release_type == ReleaseType.IR
        assert res.route == AdministrationRoute.ORAL
        assert len(res.printed_composition) == 2

        # Check composition items and strengths
        salts = {item.salt_text: (item.strength_value, item.strength_unit, item.per) for item in res.printed_composition}
        assert "Amoxycillin" in salts
        assert salts["Amoxycillin"] == (500.0, "mg", "tablet")
        assert "Potassium Clavulanate" in salts
        assert salts["Potassium Clavulanate"] == (125.0, "mg", "tablet")

        # Check field confidence
        assert res.field_confidence.brand_name >= 0.90
        assert res.field_confidence.composition >= 0.90
        assert mock_extractor.last_request_id == "req_001"
        assert mock_extractor.last_image_count == 1

    def test_glycomet_preset_extraction(self, mock_extractor, sample_image_bytes):
        mock_extractor.set_preset(MockPreset.GLYCOMET_500_PR)
        res = mock_extractor.extract([sample_image_bytes])

        assert res.is_medicine_pack is True
        assert res.brand_name == "Glycomet 500 PR"
        assert res.dosage_form == DosageForm.TABLET
        assert res.release_type == ReleaseType.MR
        assert len(res.printed_composition) == 1
        assert res.printed_composition[0].strength_value == 500.0

    def test_dispersible_preset_extraction(self, mock_extractor, sample_image_bytes):
        mock_extractor.set_preset(MockPreset.AMOXICILLIN_DISPERSIBLE)
        res = mock_extractor.extract([sample_image_bytes])

        assert res.is_medicine_pack is True
        assert res.brand_name == "Novamox DT 125"
        assert res.release_type == ReleaseType.DISPERSIBLE
        assert res.printed_composition[0].strength_value == 125.0


class TestExtractionSafetyAndAbstention:
    """Tests proving safe abstention and schema invariants."""

    def test_non_medicine_pack_schema_invariant(self, mock_extractor, sample_image_bytes):
        mock_extractor.set_preset(MockPreset.NON_MEDICINE)
        res = mock_extractor.extract([sample_image_bytes])

        assert res.is_medicine_pack is False
        assert res.brand_name is None
        assert len(res.printed_composition) == 0

        # Enforced by Pydantic model validator:
        # A non-medicine pack CANNOT have brand_name or composition
        with pytest.raises(ValidationError, match="brand_name and composition must be empty"):
            RawMedicineExtraction(
                is_medicine_pack=False,
                brand_name="Hallucinated Brand",
                printed_composition=[],
            )

    def test_unreadable_strength_remains_null(self, mock_extractor, sample_image_bytes):
        mock_extractor.set_preset(MockPreset.UNREADABLE_STRENGTH)
        res = mock_extractor.extract([sample_image_bytes])

        assert res.is_medicine_pack is True
        assert res.brand_name == "Crocin"
        assert len(res.printed_composition) == 1
        item = res.printed_composition[0]
        assert item.salt_text == "Paracetamol"
        # Must NEVER guess 500mg or 650mg when strength is unreadable
        assert item.strength_value is None
        assert item.strength_unit is None
        assert res.field_confidence.strength == 0.0

    def test_empty_composition_safe_abstention(self, mock_extractor, sample_image_bytes):
        mock_extractor.set_preset(MockPreset.EMPTY_COMPOSITION)
        res = mock_extractor.extract([sample_image_bytes])

        assert res.is_medicine_pack is True
        assert len(res.printed_composition) == 0
        assert res.field_confidence.composition == 0.0

    def test_low_confidence_fields_preserved(self, mock_extractor, sample_image_bytes):
        mock_extractor.set_preset(MockPreset.LOW_CONFIDENCE)
        res = mock_extractor.extract([sample_image_bytes])

        assert res.field_confidence.brand_name < 0.50
        assert res.field_confidence.composition < 0.50


class TestExtractorExecutionControls:
    """Tests verifying extractor configuration, queuing, and async execution."""

    def test_queued_custom_response(self, mock_extractor, sample_image_bytes):
        custom = RawMedicineExtraction(
            is_medicine_pack=True,
            brand_name="Custom Brand",
            printed_composition=[
                PrintedCompositionItem(salt_text="Test Salt", strength_value=10.0, strength_unit="mg"),
            ],
            dosage_form=DosageForm.TABLET,
        )
        mock_extractor.queue_response(custom)
        res = mock_extractor.extract([sample_image_bytes])

        assert res.brand_name == "Custom Brand"
        assert mock_extractor.call_count == 1

    def test_empty_images_raises_error(self, mock_extractor):
        with pytest.raises(ValueError, match="at least one image"):
            mock_extractor.extract([])

    def test_simulated_error_mode(self, mock_extractor, sample_image_bytes):
        mock_extractor.set_error_mode(RuntimeError("Vision API rate limit exceeded"))
        with pytest.raises(RuntimeError, match="rate limit exceeded"):
            mock_extractor.extract([sample_image_bytes])

        # Test recovery
        mock_extractor.clear_error_mode()
        res = mock_extractor.extract([sample_image_bytes])
        assert res.is_medicine_pack is True

    @pytest.mark.anyio
    async def test_async_extraction_interface(self, mock_extractor, sample_image_bytes):
        mock_extractor.set_preset(MockPreset.AUGMENTIN_625_DUO)
        res = await mock_extractor.extract_async([sample_image_bytes], request_id="async_123")

        assert res.is_medicine_pack is True
        assert res.brand_name == "Augmentin 625 Duo"
        assert mock_extractor.last_request_id == "async_123"


class TestWorkflowStateAndMatchTierDecoupling:
    """Core safety principle: Image quality success alone is never proof of medicine identity or EXACT match."""

    def test_image_quality_success_alone_cannot_authorize_exact_match(self, sharp_valid_image_bytes):
        # 1. Run image quality check on a sharp image
        validator = ImageQualityValidator()
        report = validator.validate_single_image(sharp_valid_image_bytes)
        assert report.passed is True
        assert report.workflow_state == ScanWorkflowState.READY_FOR_MATCHING

        # 2. Image passing ONLY permits matching to proceed;
        # It does NOT award EXACT tier
        # Domain contract: An unverified or unextracted scan cannot have MatchTier.EXACT
        with pytest.raises(ValueError, match="Invalid state-tier combination"):
            validate_state_tier_combination(ScanWorkflowState.RETAKE_REQUIRED, MatchTier.EXACT)

        with pytest.raises(ValueError, match="Invalid state-tier combination"):
            validate_state_tier_combination(ScanWorkflowState.REJECT_IMAGE, MatchTier.EXACT)

        with pytest.raises(ValueError, match="Invalid state-tier combination"):
            validate_state_tier_combination(ScanWorkflowState.EXTRACTION_INCOMPLETE, MatchTier.EXACT)

        with pytest.raises(ValueError, match="Invalid state-tier combination"):
            validate_state_tier_combination(ScanWorkflowState.NEEDS_USER_CONFIRMATION, MatchTier.EXACT)


class TestMultiImageConflicts:
    """Tests proving multi-image contradictions are preserved as conflicts and block EXACT matching."""

    def test_strength_conflict_across_images_blocks_exact(self):
        # Image 1: Glycomet 500mg, Image 2: Glycomet 1000mg
        ext1 = RawMedicineExtraction(
            is_medicine_pack=True,
            brand_name="Glycomet 500 PR",
            printed_composition=[
                PrintedCompositionItem(
                    salt_text="Metformin Hydrochloride Prolonged Release",
                    strength_value=500.0,
                    strength_unit="mg",
                    per="tablet",
                )
            ],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.MR,
            field_confidence=ExtractionFieldConfidence(strength=0.98),
        )
        ext2 = RawMedicineExtraction(
            is_medicine_pack=True,
            brand_name="Glycomet 1000 PR",
            printed_composition=[
                PrintedCompositionItem(
                    salt_text="Metformin Hydrochloride Prolonged Release",
                    strength_value=1000.0,
                    strength_unit="mg",
                    per="tablet",
                )
            ],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.MR,
            field_confidence=ExtractionFieldConfidence(strength=0.95),
        )

        reconciled = reconcile_extractions([ext1, ext2])

        assert len(reconciled.conflicts) > 0
        strength_conflict = next((c for c in reconciled.conflicts if c.field == ConflictField.STRENGTH), None)
        assert strength_conflict is not None
        assert "500.0 mg per tablet" in strength_conflict.conflicting_values
        assert "1000.0 mg per tablet" in strength_conflict.conflicting_values

        # Conflicting strength MUST be set to None, never guessed or picked
        assert reconciled.printed_composition[0].strength_value is None
        assert reconciled.field_confidence.strength == 0.0

        # State must be NEEDS_USER_CONFIRMATION
        state = determine_workflow_state(reconciled)
        assert state == ScanWorkflowState.NEEDS_USER_CONFIRMATION

        # EXACT matching strictly blocked
        can_proceed, reasons = can_authorize_exact_matching(reconciled)
        assert can_proceed is False
        assert any("contradictory" in r.lower() for r in reasons)

        with pytest.raises(ValueError, match="Invalid state-tier combination"):
            validate_state_tier_combination(state, MatchTier.EXACT)

    def test_ingredient_conflict_across_images_blocks_exact(self):
        # Image 1: Amoxicillin, Image 2: Metformin (completely disjoint active ingredients)
        ext1 = RawMedicineExtraction(
            is_medicine_pack=True,
            printed_composition=[PrintedCompositionItem(salt_text="Amoxicillin", strength_value=500.0, strength_unit="mg")],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
        )
        ext2 = RawMedicineExtraction(
            is_medicine_pack=True,
            printed_composition=[PrintedCompositionItem(salt_text="Metformin", strength_value=500.0, strength_unit="mg")],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
        )

        reconciled = reconcile_extractions([ext1, ext2])
        assert any(c.field == ConflictField.INGREDIENT for c in reconciled.conflicts)
        can_proceed, _ = can_authorize_exact_matching(reconciled)
        assert can_proceed is False

    def test_dosage_form_conflict_across_images_blocks_exact(self):
        # Image 1: Tablet, Image 2: Capsule
        ext1 = RawMedicineExtraction(
            is_medicine_pack=True,
            printed_composition=[PrintedCompositionItem(salt_text="Paracetamol", strength_value=650.0, strength_unit="mg")],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
        )
        ext2 = RawMedicineExtraction(
            is_medicine_pack=True,
            printed_composition=[PrintedCompositionItem(salt_text="Paracetamol", strength_value=650.0, strength_unit="mg")],
            dosage_form=DosageForm.CAPSULE,
            release_type=ReleaseType.IR,
        )

        reconciled = reconcile_extractions([ext1, ext2])
        assert any(c.field == ConflictField.DOSAGE_FORM for c in reconciled.conflicts)
        # Form demoted to UNKNOWN - never selected
        assert reconciled.dosage_form == DosageForm.UNKNOWN
        can_proceed, _ = can_authorize_exact_matching(reconciled)
        assert can_proceed is False

    def test_release_type_conflict_across_images_blocks_exact(self):
        # Image 1: IR, Image 2: SR
        ext1 = RawMedicineExtraction(
            is_medicine_pack=True,
            printed_composition=[PrintedCompositionItem(salt_text="Metformin", strength_value=500.0, strength_unit="mg")],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
        )
        ext2 = RawMedicineExtraction(
            is_medicine_pack=True,
            printed_composition=[PrintedCompositionItem(salt_text="Metformin", strength_value=500.0, strength_unit="mg")],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.SR,
        )

        reconciled = reconcile_extractions([ext1, ext2])
        assert any(c.field == ConflictField.RELEASE_TYPE for c in reconciled.conflicts)
        # Release type demoted to UNKNOWN
        assert reconciled.release_type == ReleaseType.UNKNOWN
        can_proceed, _ = can_authorize_exact_matching(reconciled)
        assert can_proceed is False

    def test_higher_confidence_never_overrides_conflict(self):
        # Image 1: High confidence (0.99) says 500mg
        # Image 2: Lower confidence (0.50) says 250mg
        ext1 = RawMedicineExtraction(
            is_medicine_pack=True,
            printed_composition=[PrintedCompositionItem(salt_text="Ciprofloxacin", strength_value=500.0, strength_unit="mg")],
            dosage_form=DosageForm.TABLET,
            field_confidence=ExtractionFieldConfidence(strength=0.99),
        )
        ext2 = RawMedicineExtraction(
            is_medicine_pack=True,
            printed_composition=[PrintedCompositionItem(salt_text="Ciprofloxacin", strength_value=250.0, strength_unit="mg")],
            dosage_form=DosageForm.TABLET,
            field_confidence=ExtractionFieldConfidence(strength=0.50),
        )

        reconciled = reconcile_extractions([ext1, ext2])
        # NEVER silently select 500.0 because of 0.99 > 0.50
        assert reconciled.printed_composition[0].strength_value is None
        assert reconciled.has_critical_conflicts is True
        assert reconciled.field_confidence.strength == 0.0

    def test_medicine_vs_non_medicine_contradiction_fails_closed(self):
        ext1 = RawMedicineExtraction(
            is_medicine_pack=True,
            brand_name="Crocin 650",
            printed_composition=[PrintedCompositionItem(salt_text="Paracetamol", strength_value=650.0, strength_unit="mg")],
        )
        ext2 = RawMedicineExtraction(
            is_medicine_pack=False,
            brand_name=None,
            printed_composition=[],
        )

        reconciled = reconcile_extractions([ext1, ext2])
        assert reconciled.is_medicine_pack is False
        assert any(c.field == ConflictField.IS_MEDICINE for c in reconciled.conflicts)
        state = determine_workflow_state(reconciled)
        assert state == ScanWorkflowState.REJECT_IMAGE

    def test_mock_extractor_per_image_presets_reconciliation(self, mock_extractor, sample_image_bytes):
        mock_extractor.set_per_image_presets([
            MockPreset.GLYCOMET_500_PR,
            MockPreset.GLYCOMET_1000_PR,
        ])
        result = mock_extractor.extract([sample_image_bytes, sample_image_bytes])

        assert result.has_critical_conflicts is True
        assert any(c.field == ConflictField.STRENGTH for c in result.conflicts)
        assert result.printed_composition[0].strength_value is None


class TestFailClosedSemantics:
    """Tests ensuring incomplete extraction and non-medicine evidence fail closed."""

    def test_incomplete_extraction_fails_closed(self):
        # Composition present but strength is missing
        incomplete = RawMedicineExtraction(
            is_medicine_pack=True,
            brand_name="Incomplete Med",
            printed_composition=[PrintedCompositionItem(salt_text="Amoxicillin", strength_value=None)],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
        )
        state = determine_workflow_state(incomplete)
        assert state == ScanWorkflowState.EXTRACTION_INCOMPLETE

        can_proceed, reasons = can_authorize_exact_matching(incomplete)
        assert can_proceed is False
        assert any("strength" in r.lower() for r in reasons)

        with pytest.raises(ValueError, match="Invalid state-tier combination"):
            validate_state_tier_combination(state, MatchTier.EXACT)

    def test_non_medicine_pack_fails_closed(self):
        non_med = RawMedicineExtraction(
            is_medicine_pack=False,
            brand_name=None,
            printed_composition=[],
        )
        state = determine_workflow_state(non_med)
        assert state == ScanWorkflowState.REJECT_IMAGE

        can_proceed, reasons = can_authorize_exact_matching(non_med)
        assert can_proceed is False
        assert any("not a verified medicine pack" in r.lower() for r in reasons)

        with pytest.raises(ValueError, match="Invalid state-tier combination"):
            validate_state_tier_combination(state, MatchTier.EXACT)

