"""Provider-independent vision extraction interface and mock implementation for testing.

Core Architectural Rules:
1. Provider-independent extraction interface decoupling vision providers (Gemini, Claude, Mock)
   from core domain logic.
2. Unreadable or missing fields remain null / UNKNOWN; never inferred from brand names.
3. If is_medicine_pack is False, brand_name and composition must be empty.
4. Field-level confidence scores are preserved for evidence reconciliation.
5. Extraction confidence alone can NEVER establish clinical equivalence.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional
from pydantic import ValidationError

from ml.schemas.enums import (
    AdministrationRoute,
    DosageForm,
    LegibilityGrade,
    ReleaseType,
    RxSchedule,
)
from ml.schemas.extraction import (
    ExtractedPackSize,
    ExtractionFieldConfidence,
    PrintedCompositionItem,
    RawMedicineExtraction,
)


class MockPreset(str, Enum):
    """Pre-configured synthetic extraction fixtures for offline test suites."""
    AUGMENTIN_625_DUO = "AUGMENTIN_625_DUO"
    GLYCOMET_500_PR = "GLYCOMET_500_PR"
    NON_MEDICINE = "NON_MEDICINE"
    UNREADABLE_STRENGTH = "UNREADABLE_STRENGTH"
    EMPTY_COMPOSITION = "EMPTY_COMPOSITION"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    AMOXICILLIN_DISPERSIBLE = "AMOXICILLIN_DISPERSIBLE"
    GLYCOMET_1000_PR = "GLYCOMET_1000_PR"


class BaseVisionExtractor(ABC):
    """Abstract interface defining the contract for all vision-language extraction providers."""

    @abstractmethod
    def extract(
        self,
        images: List[bytes],
        request_id: Optional[str] = None,
    ) -> RawMedicineExtraction:
        """Synchronously processes 1 to 3 images and extracts structured packaging fields."""
        pass

    @abstractmethod
    async def extract_async(
        self,
        images: List[bytes],
        request_id: Optional[str] = None,
    ) -> RawMedicineExtraction:
        """Asynchronously processes 1 to 3 images and extracts structured packaging fields."""
        pass


class MockVisionExtractor(BaseVisionExtractor):
    """Deterministic mock provider enabling reproducible testing without live VLM credentials."""

    def __init__(self, default_preset: MockPreset = MockPreset.AUGMENTIN_625_DUO):
        self.current_preset = default_preset
        self._queued_responses: List[RawMedicineExtraction] = []
        self._per_image_presets: List[MockPreset] = []
        self._should_raise_error: bool = False
        self._error_to_raise: Optional[Exception] = None
        self.call_count: int = 0
        self.last_request_id: Optional[str] = None
        self.last_image_count: int = 0

    def set_preset(self, preset: MockPreset) -> None:
        """Sets the active preset response."""
        self.current_preset = preset

    def set_per_image_presets(self, presets: List[MockPreset]) -> None:
        """Sets individual presets for simulating multiple distinct uploaded images."""
        self._per_image_presets = list(presets)

    def queue_response(self, extraction: RawMedicineExtraction) -> None:
        """Queues an explicit custom extraction response for the next extraction call."""
        self._queued_responses.append(extraction)

    def set_error_mode(self, error: Optional[Exception] = None) -> None:
        """Configures the mock to raise a simulated provider failure (e.g. timeout or malformed)."""
        self._should_raise_error = True
        self._error_to_raise = error or RuntimeError("Simulated vision provider upstream failure.")

    def clear_error_mode(self) -> None:
        """Clears simulated error mode."""
        self._should_raise_error = False
        self._error_to_raise = None

    def _generate_preset_response(self, preset: MockPreset) -> RawMedicineExtraction:
        """Generates standard synthetic fixture responses."""
        if preset == MockPreset.AUGMENTIN_625_DUO:
            return RawMedicineExtraction(
                is_medicine_pack=True,
                brand_name="Augmentin 625 Duo",
                manufacturer="GlaxoSmithKline Pharmaceuticals Ltd",
                printed_composition=[
                    PrintedCompositionItem(
                        salt_text="Amoxycillin",
                        strength_value=500.0,
                        strength_unit="mg",
                        per="tablet",
                    ),
                    PrintedCompositionItem(
                        salt_text="Potassium Clavulanate",
                        strength_value=125.0,
                        strength_unit="mg",
                        per="tablet",
                    ),
                ],
                dosage_form=DosageForm.TABLET,
                release_type=ReleaseType.IR,
                route=AdministrationRoute.ORAL,
                pack_size=ExtractedPackSize(count=10.0, unit="tablets"),
                mrp_inr=201.71,
                expiry="2027-08",
                rx_schedule=RxSchedule.SCHEDULE_H1,
                legibility=LegibilityGrade.GOOD,
                field_confidence=ExtractionFieldConfidence(
                    brand_name=0.98,
                    composition=0.95,
                    strength=0.96,
                    dosage_form=0.99,
                    release_type=0.90,
                    mrp_inr=0.92,
                ),
            )

        elif preset == MockPreset.GLYCOMET_500_PR:
            return RawMedicineExtraction(
                is_medicine_pack=True,
                brand_name="Glycomet 500 PR",
                manufacturer="USV Private Limited",
                printed_composition=[
                    PrintedCompositionItem(
                        salt_text="Metformin Hydrochloride Prolonged Release",
                        strength_value=500.0,
                        strength_unit="mg",
                        per="tablet",
                    ),
                ],
                dosage_form=DosageForm.TABLET,
                release_type=ReleaseType.MR,
                route=AdministrationRoute.ORAL,
                pack_size=ExtractedPackSize(count=10.0, unit="tablets"),
                mrp_inr=35.0,
                expiry="2028-01",
                rx_schedule=RxSchedule.SCHEDULE_H,
                legibility=LegibilityGrade.GOOD,
                field_confidence=ExtractionFieldConfidence(
                    brand_name=0.97,
                    composition=0.94,
                    strength=0.95,
                    dosage_form=0.98,
                    release_type=0.95,
                    mrp_inr=0.88,
                ),
            )

        elif preset == MockPreset.GLYCOMET_1000_PR:
            return RawMedicineExtraction(
                is_medicine_pack=True,
                brand_name="Glycomet 1000 PR",
                manufacturer="USV Private Limited",
                printed_composition=[
                    PrintedCompositionItem(
                        salt_text="Metformin Hydrochloride Prolonged Release",
                        strength_value=1000.0,
                        strength_unit="mg",
                        per="tablet",
                    ),
                ],
                dosage_form=DosageForm.TABLET,
                release_type=ReleaseType.MR,
                route=AdministrationRoute.ORAL,
                pack_size=ExtractedPackSize(count=10.0, unit="tablets"),
                mrp_inr=65.0,
                expiry="2028-01",
                rx_schedule=RxSchedule.SCHEDULE_H,
                legibility=LegibilityGrade.GOOD,
                field_confidence=ExtractionFieldConfidence(
                    brand_name=0.98,
                    composition=0.95,
                    strength=0.96,
                    dosage_form=0.98,
                    release_type=0.95,
                    mrp_inr=0.90,
                ),
            )

        elif preset == MockPreset.NON_MEDICINE:
            return RawMedicineExtraction(
                is_medicine_pack=False,
                brand_name=None,
                manufacturer=None,
                printed_composition=[],
                dosage_form=DosageForm.UNKNOWN,
                release_type=ReleaseType.UNKNOWN,
                route=AdministrationRoute.UNKNOWN,
                pack_size=None,
                mrp_inr=None,
                expiry=None,
                rx_schedule=RxSchedule.UNKNOWN,
                legibility=LegibilityGrade.POOR,
                field_confidence=ExtractionFieldConfidence(
                    brand_name=0.0,
                    composition=0.0,
                    strength=0.0,
                    dosage_form=0.0,
                    release_type=0.0,
                    mrp_inr=0.0,
                ),
            )

        elif preset == MockPreset.UNREADABLE_STRENGTH:
            return RawMedicineExtraction(
                is_medicine_pack=True,
                brand_name="Crocin",
                manufacturer="GlaxoSmithKline",
                printed_composition=[
                    PrintedCompositionItem(
                        salt_text="Paracetamol",
                        strength_value=None,  # Unreadable / smudged
                        strength_unit=None,
                        per="tablet",
                    ),
                ],
                dosage_form=DosageForm.TABLET,
                release_type=ReleaseType.IR,
                route=AdministrationRoute.ORAL,
                pack_size=ExtractedPackSize(count=15.0, unit="tablets"),
                mrp_inr=None,
                expiry=None,
                rx_schedule=RxSchedule.OTC,
                legibility=LegibilityGrade.PARTIAL,
                field_confidence=ExtractionFieldConfidence(
                    brand_name=0.95,
                    composition=0.80,
                    strength=0.0,
                    dosage_form=0.90,
                    release_type=0.70,
                    mrp_inr=0.0,
                ),
            )

        elif preset == MockPreset.EMPTY_COMPOSITION:
            return RawMedicineExtraction(
                is_medicine_pack=True,
                brand_name="Unknown Strip",
                manufacturer=None,
                printed_composition=[],
                dosage_form=DosageForm.TABLET,
                release_type=ReleaseType.UNKNOWN,
                route=AdministrationRoute.ORAL,
                pack_size=None,
                mrp_inr=None,
                expiry=None,
                rx_schedule=RxSchedule.UNKNOWN,
                legibility=LegibilityGrade.POOR,
                field_confidence=ExtractionFieldConfidence(
                    brand_name=0.40,
                    composition=0.0,
                    strength=0.0,
                    dosage_form=0.50,
                    release_type=0.0,
                    mrp_inr=0.0,
                ),
            )

        elif preset == MockPreset.LOW_CONFIDENCE:
            return RawMedicineExtraction(
                is_medicine_pack=True,
                brand_name="Partial Brand",
                manufacturer=None,
                printed_composition=[
                    PrintedCompositionItem(
                        salt_text="Amlodipine",
                        strength_value=5.0,
                        strength_unit="mg",
                        per="tablet",
                    ),
                ],
                dosage_form=DosageForm.TABLET,
                release_type=ReleaseType.UNKNOWN,
                route=AdministrationRoute.ORAL,
                pack_size=None,
                mrp_inr=None,
                expiry=None,
                rx_schedule=RxSchedule.UNKNOWN,
                legibility=LegibilityGrade.PARTIAL,
                field_confidence=ExtractionFieldConfidence(
                    brand_name=0.35,  # Low confidence
                    composition=0.40,
                    strength=0.45,
                    dosage_form=0.60,
                    release_type=0.0,
                    mrp_inr=0.0,
                ),
            )

        elif preset == MockPreset.AMOXICILLIN_DISPERSIBLE:
            return RawMedicineExtraction(
                is_medicine_pack=True,
                brand_name="Novamox DT 125",
                manufacturer="Cipla Ltd",
                printed_composition=[
                    PrintedCompositionItem(
                        salt_text="Amoxycillin Trihydrate",
                        strength_value=125.0,
                        strength_unit="mg",
                        per="tablet",
                    ),
                ],
                dosage_form=DosageForm.TABLET,
                release_type=ReleaseType.DISPERSIBLE,
                route=AdministrationRoute.ORAL,
                pack_size=ExtractedPackSize(count=10.0, unit="tablets"),
                mrp_inr=28.50,
                expiry="2027-04",
                rx_schedule=RxSchedule.SCHEDULE_H1,
                legibility=LegibilityGrade.GOOD,
                field_confidence=ExtractionFieldConfidence(
                    brand_name=0.96,
                    composition=0.97,
                    strength=0.98,
                    dosage_form=0.99,
                    release_type=0.96,
                    mrp_inr=0.90,
                ),
            )

        raise ValueError(f"Unknown mock preset: {preset}")

    def extract(
        self,
        images: List[bytes],
        request_id: Optional[str] = None,
    ) -> RawMedicineExtraction:
        """Synchronously returns queued or preset extraction response."""
        self.call_count += 1
        self.last_request_id = request_id
        self.last_image_count = len(images)

        if self._should_raise_error:
            raise self._error_to_raise or RuntimeError("Simulated vision provider failure.")

        if not images:
            raise ValueError("Extractor requires at least one image byte payload.")

        if self._queued_responses:
            return self._queued_responses.pop(0)

        if len(images) > 1 and self._per_image_presets:
            from ml.vision.reconciliation import reconcile_extractions
            sub_extractions = [
                self._generate_preset_response(p)
                for p in self._per_image_presets[: len(images)]
            ]
            return reconcile_extractions(sub_extractions)

        return self._generate_preset_response(self.current_preset)

    async def extract_async(
        self,
        images: List[bytes],
        request_id: Optional[str] = None,
    ) -> RawMedicineExtraction:
        """Asynchronously returns queued or preset extraction response."""
        return self.extract(images, request_id=request_id)
