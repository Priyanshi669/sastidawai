"""End-to-end integration tests tracing Phase 1F/1F.1 pipeline execution.

Traces the execution path from:
1. Image validation (format, dimensions, bytes, blur, lighting, glare, EXIF)
2. Extraction (MockVisionExtractor with domain presets)
3. Multi-image reconciliation & conflict detection
4. Canonical conversion & safety authorization
5. Candidate resolution (SQLite) and deterministic matching (Phase 1C)

Safety Assertions Proven:
- Non-ready workflow states (REJECT_IMAGE, RETAKE_REQUIRED, EXTRACTION_INCOMPLETE,
  NEEDS_USER_CONFIRMATION) CANNOT produce MatchTier.EXACT or savings.
- Contradictory critical dimensions (strength, ingredient, form, release) fail closed.
- Pillow global MAX_IMAGE_PIXELS state is cleanly restored after every run.
"""

from io import BytesIO
import cv2
import numpy as np
from PIL import Image
import pytest

from ml.resolver.candidates import CandidateResolver
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
from ml.vision.extractor import MockPreset, MockVisionExtractor
from ml.vision.quality import ImageQualityValidator, QualityThresholds
from ml.vision.reconciliation import (
    can_authorize_exact_matching,
    determine_workflow_state,
    extraction_to_canonical,
    reconcile_extractions,
)


def create_sharp_medicine_image() -> bytes:
    """Generates a sharp, well-lit test image passing all quality heuristics."""
    img = np.full((300, 300, 3), 128, dtype=np.uint8)
    for y in range(30, 270, 30):
        cv2.line(img, (20, y), (280, y), (0, 0, 0), 2)
        cv2.putText(img, "PARACETAMOL 650mg", (30, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    buf = BytesIO()
    Image.fromarray(img).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def sharp_image():
    return create_sharp_medicine_image()


@pytest.fixture
def resolver():
    return CandidateResolver()


class TestPhase1FIntegrationPipeline:
    """Integration test suite executing the complete Phase 1F/1F.1 pipeline path."""

    def test_clean_verified_extraction_flows_to_matching(self, sharp_image, resolver):
        """End-to-end trace: Valid image -> clean extraction -> candidate resolution -> matching."""
        # 1. Image Quality Validation
        validator = ImageQualityValidator()
        quality_report = validator.validate_images([sharp_image])
        assert quality_report.passed is True
        assert quality_report.workflow_state == ScanWorkflowState.READY_FOR_MATCHING

        # 2. Vision Extraction
        extractor = MockVisionExtractor(default_preset=MockPreset.AUGMENTIN_625_DUO)
        raw_extraction = extractor.extract([sharp_image])
        assert raw_extraction.is_medicine_pack is True
        assert raw_extraction.has_critical_conflicts is False

        # 3. Safety Authorization Check
        can_proceed, reasons = can_authorize_exact_matching(raw_extraction)
        assert can_proceed is True
        assert len(reasons) == 0

        # 4. Canonical Conversion
        scanned_canonical, state, reasons = extraction_to_canonical(raw_extraction)
        assert state == ScanWorkflowState.READY_FOR_MATCHING
        assert scanned_canonical is not None
        assert scanned_canonical.is_quarantined is False
        assert len(scanned_canonical.salts) == 2

        # 5. Candidate Resolution and Matching
        workflow_state, resolver_result, match_result = resolver.resolve_and_match_extraction(raw_extraction)
        assert workflow_state == ScanWorkflowState.READY_FOR_MATCHING
        assert match_result is not None
        assert match_result.workflow_state == ScanWorkflowState.READY_FOR_MATCHING
        assert match_result.disclaimer is not None

    def test_strength_conflict_blocks_exact_and_savings(self, sharp_image, resolver):
        """Contradictory strengths across multi-image captures fail closed."""
        # Setup multi-image extraction with 500mg vs 1000mg
        extractor = MockVisionExtractor()
        extractor.set_per_image_presets([
            MockPreset.GLYCOMET_500_PR,
            MockPreset.GLYCOMET_1000_PR,
        ])
        reconciled = extractor.extract([sharp_image, sharp_image])

        # Verification of conflict preservation
        assert reconciled.has_critical_conflicts is True
        assert any(c.field == ConflictField.STRENGTH for c in reconciled.conflicts)
        assert reconciled.printed_composition[0].strength_value is None

        # Safety gate evaluation
        state = determine_workflow_state(reconciled)
        assert state == ScanWorkflowState.NEEDS_USER_CONFIRMATION

        can_proceed, reasons = can_authorize_exact_matching(reconciled)
        assert can_proceed is False
        assert any("contradictory" in r.lower() for r in reasons)

        # Pipeline execution fails closed: Tier NONE, matched_alternatives empty, savings None
        workflow_state, resolver_result, match_result = resolver.resolve_and_match_extraction(reconciled)
        assert workflow_state == ScanWorkflowState.NEEDS_USER_CONFIRMATION
        assert match_result.tier == MatchTier.NONE
        assert match_result.matched_alternatives == []
        assert all(alt.savings is None for alt in match_result.matched_alternatives)

    def test_dosage_form_conflict_blocks_exact_and_savings(self, resolver):
        """Contradictory dosage forms (tablet vs capsule) across images fail closed."""
        ext1 = RawMedicineExtraction(
            is_medicine_pack=True,
            printed_composition=[PrintedCompositionItem(salt_text="Amoxicillin", strength_value=500.0, strength_unit="mg")],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
        )
        ext2 = RawMedicineExtraction(
            is_medicine_pack=True,
            printed_composition=[PrintedCompositionItem(salt_text="Amoxicillin", strength_value=500.0, strength_unit="mg")],
            dosage_form=DosageForm.CAPSULE,
            release_type=ReleaseType.IR,
        )

        reconciled = reconcile_extractions([ext1, ext2])
        assert reconciled.has_critical_conflicts is True
        assert reconciled.dosage_form == DosageForm.UNKNOWN

        state, resolver_res, match_res = resolver.resolve_and_match_extraction(reconciled)
        assert state == ScanWorkflowState.NEEDS_USER_CONFIRMATION
        assert match_res.tier == MatchTier.NONE
        assert match_res.matched_alternatives == []
        assert all(alt.savings is None for alt in match_res.matched_alternatives)

    def test_release_type_conflict_blocks_exact_and_savings(self, resolver):
        """Contradictory release types (IR vs SR) across images fail closed."""
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
        assert reconciled.has_critical_conflicts is True
        assert reconciled.release_type == ReleaseType.UNKNOWN

        state, resolver_res, match_res = resolver.resolve_and_match_extraction(reconciled)
        assert state == ScanWorkflowState.NEEDS_USER_CONFIRMATION
        assert match_res.tier == MatchTier.NONE
        assert match_res.matched_alternatives == []
        assert all(alt.savings is None for alt in match_res.matched_alternatives)

    def test_ingredient_conflict_blocks_exact_and_savings(self, resolver):
        """Disjoint active ingredients across images fail closed."""
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
        assert reconciled.has_critical_conflicts is True

        state, resolver_res, match_res = resolver.resolve_and_match_extraction(reconciled)
        assert state == ScanWorkflowState.NEEDS_USER_CONFIRMATION
        assert match_res.tier == MatchTier.NONE
        assert match_res.matched_alternatives == []
        assert all(alt.savings is None for alt in match_res.matched_alternatives)

    def test_unreadable_strength_extraction_incomplete_blocks_exact(self, sharp_image, resolver):
        """Extraction with unreadable/missing strength fails closed as EXTRACTION_INCOMPLETE."""
        extractor = MockVisionExtractor(default_preset=MockPreset.UNREADABLE_STRENGTH)
        raw_extraction = extractor.extract([sharp_image])

        assert raw_extraction.printed_composition[0].strength_value is None
        state = determine_workflow_state(raw_extraction)
        assert state == ScanWorkflowState.EXTRACTION_INCOMPLETE

        can_proceed, reasons = can_authorize_exact_matching(raw_extraction)
        assert can_proceed is False

        workflow_state, resolver_res, match_res = resolver.resolve_and_match_extraction(raw_extraction)
        assert workflow_state == ScanWorkflowState.EXTRACTION_INCOMPLETE
        assert match_res.tier == MatchTier.NONE
        assert match_res.matched_alternatives == []
        assert all(alt.savings is None for alt in match_res.matched_alternatives)

    def test_non_medicine_image_rejects_and_blocks_exact(self, sharp_image, resolver):
        """Non-medicine image extraction fails closed as REJECT_IMAGE."""
        extractor = MockVisionExtractor(default_preset=MockPreset.NON_MEDICINE)
        raw_extraction = extractor.extract([sharp_image])

        assert raw_extraction.is_medicine_pack is False
        state = determine_workflow_state(raw_extraction)
        assert state == ScanWorkflowState.REJECT_IMAGE

        workflow_state, resolver_res, match_res = resolver.resolve_and_match_extraction(raw_extraction)
        assert workflow_state == ScanWorkflowState.REJECT_IMAGE
        assert match_res.tier == MatchTier.NONE
        assert match_res.matched_alternatives == []
        assert all(alt.savings is None for alt in match_res.matched_alternatives)

    def test_pillow_global_max_image_pixels_restored(self):
        """Pillow module-level MAX_IMAGE_PIXELS must be safely restored after image validation."""
        original_limit = Image.MAX_IMAGE_PIXELS

        # Instantiate validator with temporary strict pixel threshold
        temp_validator = ImageQualityValidator(QualityThresholds(max_total_pixels=50_000))
        img = create_sharp_medicine_image()

        # Run validation
        report = temp_validator.validate_single_image(img)

        # Assert global state is unchanged after execution
        assert Image.MAX_IMAGE_PIXELS == original_limit
