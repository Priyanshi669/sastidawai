"""Raw vision-language model extraction schema and validation rules."""

from enum import Enum
import re
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from ml.schemas.enums import (
    AdministrationRoute,
    DosageForm,
    LegibilityGrade,
    ReleaseType,
    RxSchedule,
)


class ConflictField(str, Enum):
    """Controlled fields subject to multi-image conflict detection."""
    STRENGTH = "strength"
    INGREDIENT = "ingredient"
    DOSAGE_FORM = "dosage_form"
    RELEASE_TYPE = "release_type"
    ROUTE = "route"
    BRAND_NAME = "brand_name"
    IS_MEDICINE = "is_medicine"


class ExtractionConflict(BaseModel):
    """Preserved contradiction between evidence observed across multiple images."""
    field: ConflictField = Field(..., description="The field where conflicting values were detected.")
    image_indices: List[int] = Field(..., description="0-indexed image positions where conflicting evidence appeared.")
    conflicting_values: List[str] = Field(..., description="The contradictory observed values.")
    description: str = Field(..., description="Human-readable explanation of why this is contradictory.")


class PrintedCompositionItem(BaseModel):
    """A single printed active ingredient read from packaging text."""
    salt_text: str = Field(
        ...,
        min_length=1,
        description="Exact printed name of the chemical moiety or salt as visible on packaging."
    )
    strength_value: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Numerical strength value as printed. Null if unreadable or absent; never guess."
    )
    strength_unit: Optional[str] = Field(
        default=None,
        description="Unit of measurement: mg, mcg, g, IU, %, ml. Null if unreadable; never guess."
    )
    per: Optional[str] = Field(
        default=None,
        description="Denominator per unit: tablet, capsule, 5ml, ml, dose. Null if not explicitly printed."
    )


class ExtractedPackSize(BaseModel):
    """Printed pack size count and unit."""
    count: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Number of units in the pack (e.g. 10 tablets, 100 ml)."
    )
    unit: Optional[str] = Field(
        default=None,
        description="Unit of packaging: tablets, capsules, ml, g, ampoules, vials."
    )


class ExtractionFieldConfidence(BaseModel):
    """Estimated confidence score (0.0 to 1.0) per critical field as reported by model or ensemble."""
    brand_name: float = Field(default=0.0, ge=0.0, le=1.0)
    composition: float = Field(default=0.0, ge=0.0, le=1.0)
    strength: float = Field(default=0.0, ge=0.0, le=1.0)
    dosage_form: float = Field(default=0.0, ge=0.0, le=1.0)
    release_type: float = Field(default=0.0, ge=0.0, le=1.0)
    mrp_inr: float = Field(default=0.0, ge=0.0, le=1.0)


class RawMedicineExtraction(BaseModel):
    """Strict schema for perception extraction output.
    
    Invariants:
    1. Unreadable or missing fields remain None / UNKNOWN.
    2. Never infer a salt from a brand name.
    3. If is_medicine_pack is False, brand and composition must be empty.
    """
    is_medicine_pack: bool = Field(
        ...,
        description="False if image is not a recognizable medicine strip, blister, or pack."
    )
    brand_name: Optional[str] = Field(
        default=None,
        description="Printed commercial trade name. Null if not visible or unreadable."
    )
    manufacturer: Optional[str] = Field(
        default=None,
        description="Printed manufacturer/marketer name. Null if not visible."
    )
    printed_composition: List[PrintedCompositionItem] = Field(
        default_factory=list,
        description="List of active ingredients and strengths visibly printed on pack."
    )
    dosage_form: DosageForm = Field(
        default=DosageForm.UNKNOWN,
        description="Controlled dosage form read from pack."
    )
    release_type: ReleaseType = Field(
        default=ReleaseType.UNKNOWN,
        description="Controlled release mechanism read from pack (e.g. IR, SR, ER)."
    )
    route: AdministrationRoute = Field(
        default=AdministrationRoute.UNKNOWN,
        description="Route of administration if stated on packaging."
    )
    pack_size: Optional[ExtractedPackSize] = Field(
        default=None,
        description="Pack quantity count and unit."
    )
    mrp_inr: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Printed Maximum Retail Price in INR. Null if obscured, scratched, or unprinted."
    )
    expiry: Optional[str] = Field(
        default=None,
        description="Expiry date string in YYYY-MM format if confidently read."
    )
    rx_schedule: RxSchedule = Field(
        default=RxSchedule.UNKNOWN,
        description="Regulatory schedule warning label if visible (e.g. Schedule H)."
    )
    legibility: LegibilityGrade = Field(
        default=LegibilityGrade.PARTIAL,
        description="Overall human-reading legibility assessment."
    )
    field_confidence: ExtractionFieldConfidence = Field(
        default_factory=ExtractionFieldConfidence,
        description="Per-field confidence indicators."
    )
    conflicts: List[ExtractionConflict] = Field(
        default_factory=list,
        description="Preserved contradictory critical fields across multi-image captures."
    )

    @property
    def has_critical_conflicts(self) -> bool:
        """True if any contradictory evidence exists for safety-critical dimensions."""
        critical_fields = {
            ConflictField.STRENGTH,
            ConflictField.INGREDIENT,
            ConflictField.DOSAGE_FORM,
            ConflictField.RELEASE_TYPE,
        }
        return any(c.field in critical_fields for c in self.conflicts)

    @field_validator("expiry")
    @classmethod
    def validate_expiry_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        # Strict YYYY-MM regex
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", v):
            raise ValueError(f"Expiry must be formatted as YYYY-MM, got: '{v}'")
        return v

    @model_validator(mode="after")
    def validate_non_medicine_pack(self) -> "RawMedicineExtraction":
        if not self.is_medicine_pack:
            if self.brand_name is not None or len(self.printed_composition) > 0:
                raise ValueError(
                    "When is_medicine_pack is False, brand_name and composition must be empty."
                )
        return self
