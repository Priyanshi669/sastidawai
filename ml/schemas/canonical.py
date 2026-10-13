"""Canonical medicine representation, provenance, and pricing schemas."""

import re
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from ml.schemas.enums import AdministrationRoute, DosageForm, ReleaseType


class ActiveSaltMoiety(BaseModel):
    """Normalized active chemical moiety and its strength per unit."""
    salt_name: str = Field(
        ...,
        min_length=1,
        description="Canonical normalized lowercase name of the active moiety (e.g. 'metformin')."
    )
    salt_modifier: Optional[str] = Field(
        default=None,
        description="Optional salt chemical modifier (e.g. 'hydrochloride', 'besylate', 'potassium')."
    )
    strength_value: float = Field(
        ...,
        gt=0.0,
        description="Normalized numeric strength value in standardized units."
    )
    strength_unit: str = Field(
        ...,
        description="Standardized unit: 'mg', 'mcg', 'g', 'iu', 'ml', '%'."
    )
    per_unit: str = Field(
        default="unit",
        description="Denominator per dose: 'unit', 'tablet', 'capsule', '5ml', 'ml', 'g'."
    )

    @field_validator("salt_name")
    @classmethod
    def sanitize_salt_name(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if not cleaned:
            raise ValueError("salt_name cannot be empty or whitespace.")
        return cleaned

    @field_validator("strength_unit")
    @classmethod
    def sanitize_unit(cls, v: str) -> str:
        return v.strip().lower()


class ProvenanceRecord(BaseModel):
    """Immutable audit trail tracing a product or price to its source."""
    source_name: str = Field(
        ...,
        description="Source identifier (e.g. 'PMBI_JAN_AUSHADHI', 'INDIAN_MEDICINE_DATASET')."
    )
    source_row_id: Optional[str] = Field(
        default=None,
        description="Row ID or primary key in the original raw dataset."
    )
    raw_text: str = Field(
        ...,
        description="Original unmodified text or name from the source document."
    )
    retrieval_date: str = Field(
        ...,
        description="Date when the dataset was downloaded or refreshed (YYYY-MM-DD)."
    )
    price_date: Optional[str] = Field(
        default=None,
        description="Official publication or effective date of the price (YYYY-MM-DD)."
    )
    checksum_sha256: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of the source data file to guarantee immutability."
    )

    @field_validator("retrieval_date", "price_date")
    @classmethod
    def validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"Date must be formatted as YYYY-MM-DD, got: '{v}'")
        return v


class PriceRecord(BaseModel):
    """Verified pricing information with explicit provenance and pack normalization."""
    pack_mrp_inr: float = Field(
        ...,
        gt=0.0,
        description="Maximum retail price in INR for the full package."
    )
    pack_count: float = Field(
        ...,
        gt=0.0,
        description="Total number of units in the pack (e.g. 10 tablets, 100 ml)."
    )
    unit_price_inr: float = Field(
        ...,
        gt=0.0,
        description="Calculated unit price in INR (pack_mrp_inr / pack_count)."
    )
    price_date: str = Field(
        ...,
        description="Mandatory publication date of the price (YYYY-MM-DD). Never claim price without date."
    )
    is_verified_current: bool = Field(
        default=False,
        description="True only if price has been verified against current authoritative source."
    )
    provenance: ProvenanceRecord = Field(
        ...,
        description="Source provenance for this price."
    )

    @field_validator("price_date")
    @classmethod
    def validate_price_date(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"price_date must be formatted as YYYY-MM-DD, got: '{v}'")
        return v

    @model_validator(mode="after")
    def validate_unit_price(self) -> "PriceRecord":
        expected = round(self.pack_mrp_inr / self.pack_count, 4)
        actual = round(self.unit_price_inr, 4)
        if abs(expected - actual) > 0.01:
            raise ValueError(
                f"unit_price_inr ({self.unit_price_inr}) does not match pack_mrp_inr / pack_count ({expected})"
            )
        return self


class CanonicalMedicine(BaseModel):
    """Canonical representation of a medicine record.
    
    All products (scanned or catalogue) are mapped to this structure.
    Two products are comparable for EXACT matching only if all 5 canonical dimensions match.
    """
    product_id: str = Field(
        ...,
        min_length=1,
        description="Unique stable system identifier."
    )
    name: str = Field(
        ...,
        description="Standardized display name."
    )
    brand_name: Optional[str] = Field(
        default=None,
        description="Commercial brand name if branded product; None if generic."
    )
    generic_name: Optional[str] = Field(
        default=None,
        description="Official generic formulation title."
    )
    manufacturer: Optional[str] = Field(
        default=None,
        description="Manufacturer or marketing entity."
    )
    salts: List[ActiveSaltMoiety] = Field(
        default_factory=list,
        description="Complete list of active chemical moieties and normalized strengths."
    )
    dosage_form: DosageForm = Field(
        default=DosageForm.UNKNOWN,
        description="Normalized dosage form."
    )
    release_type: ReleaseType = Field(
        default=ReleaseType.UNKNOWN,
        description="Normalized release characteristics (IR, SR, ER, etc.)."
    )
    route: AdministrationRoute = Field(
        default=AdministrationRoute.UNKNOWN,
        description="Route of administration."
    )
    price: Optional[PriceRecord] = Field(
        default=None,
        description="Verified price record with provenance."
    )
    is_quarantined: bool = Field(
        default=False,
        description="True if record has ambiguous composition, missing critical fields, or parsing defects."
    )
    quarantine_reason: Optional[str] = Field(
        default=None,
        description="Explicit reason explaining why record was quarantined."
    )
    is_nti: bool = Field(
        default=False,
        description="Narrow Therapeutic Index flag. Note: automated NTI filtering is currently BLOCKED pending clinical review."
    )
    is_discontinued: bool = Field(
        default=False,
        description="True if source dataset reports this formulation as discontinued."
    )
    is_eligible_for_matching: bool = Field(
        default=True,
        description="True if record meets all eligibility criteria for exact matching in catalogue."
    )
    provenance: Optional[ProvenanceRecord] = Field(
        default=None,
        description="Audit trail of origin dataset."
    )

    @model_validator(mode="after")
    def validate_active_eligibility(self) -> "CanonicalMedicine":
        # An unquarantined medicine eligible for matching MUST have active salts and defined dimensions
        if not self.is_quarantined:
            if not self.salts:
                raise ValueError("Unquarantined CanonicalMedicine must have at least one active salt.")
        return self
