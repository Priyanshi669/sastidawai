"""Deterministic matching contract, savings calculations, and state transition guards."""

import re
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from ml.schemas.canonical import CanonicalMedicine
from ml.schemas.enums import MatchTier, ScanWorkflowState

MANDATORY_DISCLAIMER = "Always confirm with your doctor or pharmacist."


def validate_state_tier_combination(
    workflow_state: ScanWorkflowState,
    tier: MatchTier,
) -> None:
    """Enforces legal pairings between workflow state and match tier.
    
    CRITICAL: Perception workflow state and clinical equivalence tier are strictly separate.
    Only READY_FOR_MATCHING may evaluate to EXACT or CLOSE.
    Any non-ready state (incomplete, unconfirmed, rejected) must have tier NONE.
    """
    if workflow_state != ScanWorkflowState.READY_FOR_MATCHING:
        if tier != MatchTier.NONE:
            raise ValueError(
                f"Invalid state-tier combination: Workflow state '{workflow_state.value}' "
                f"cannot be paired with match tier '{tier.value}'. Must be '{MatchTier.NONE.value}'."
            )


class SavingsCalculation(BaseModel):
    """Transparent, verifiable financial savings calculation.
    
    Invariants:
    1. Only computed for EXACT matches.
    2. Computed from verified, dated prices.
    3. Math must be exactly reproducible by hand.
    """
    brand_unit_price_inr: float = Field(
        ...,
        gt=0.0,
        description="Verified price per unit (tablet/ml/g) of the brand medicine."
    )
    generic_unit_price_inr: float = Field(
        ...,
        gt=0.0,
        description="Verified price per unit of the Jan Aushadhi generic equivalent."
    )
    doses_per_day: float = Field(
        default=2.0,
        gt=0.0,
        description="Prescribed doses per day (defaults to 2 if not confirmed by user)."
    )
    units_per_month: float = Field(
        default=60.0,
        gt=0.0,
        description="Monthly units consumed (doses_per_day * 30)."
    )
    monthly_savings_inr: float = Field(
        ...,
        ge=0.0,
        description="(brand_unit_price_inr - generic_unit_price_inr) * units_per_month."
    )
    yearly_savings_inr: float = Field(
        ...,
        ge=0.0,
        description="monthly_savings_inr * 12."
    )
    price_as_of: str = Field(
        ...,
        description="Effective date of the generic catalogue price (YYYY-MM-DD)."
    )
    calculation_basis: str = Field(
        default="per_unit",
        description="Unit type used for comparison: 'per_tablet', 'per_ml', 'per_g', 'per_vial'."
    )

    @field_validator("price_as_of")
    @classmethod
    def validate_price_date(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"price_as_of must be formatted as YYYY-MM-DD, got: '{v}'")
        return v

    @model_validator(mode="after")
    def validate_savings_arithmetic(self) -> "SavingsCalculation":
        if self.generic_unit_price_inr > self.brand_unit_price_inr:
            raise ValueError(
                f"Generic unit price ({self.generic_unit_price_inr}) exceeds brand unit price ({self.brand_unit_price_inr}). "
                "Negative savings cannot be claimed as a discount."
            )
        
        expected_monthly = round((self.brand_unit_price_inr - self.generic_unit_price_inr) * self.units_per_month, 2)
        if abs(self.monthly_savings_inr - expected_monthly) > 0.05:
            raise ValueError(
                f"monthly_savings_inr ({self.monthly_savings_inr}) does not match "
                f"({self.brand_unit_price_inr} - {self.generic_unit_price_inr}) * {self.units_per_month} = {expected_monthly}"
            )
        
        expected_yearly = round(self.monthly_savings_inr * 12, 2)
        if abs(self.yearly_savings_inr - expected_yearly) > 0.05:
            raise ValueError(
                f"yearly_savings_inr ({self.yearly_savings_inr}) does not match monthly_savings_inr * 12 = {expected_yearly}"
            )
        
        return self


class MatchAlternative(BaseModel):
    """A verified catalogue alternative with traceable pricing."""
    generic_product_id: str = Field(..., min_length=1)
    generic_name: str = Field(..., min_length=1)
    manufacturer: Optional[str] = Field(default=None)
    strip_mrp_inr: float = Field(..., gt=0.0)
    pack_count: float = Field(..., gt=0.0)
    unit_price_inr: float = Field(..., gt=0.0)
    price_date: str = Field(...)
    source: str = Field(default="PMBI product list")
    savings: Optional[SavingsCalculation] = Field(
        default=None,
        description="Savings calculation. STRICT: Only populated for EXACT tier matches."
    )

    @field_validator("price_date")
    @classmethod
    def validate_price_date(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"price_date must be formatted as YYYY-MM-DD, got: '{v}'")
        return v


class MatchRequest(BaseModel):
    """Input payload to evaluate deterministic medicine equivalence."""
    scanned_canonical: CanonicalMedicine = Field(
        ...,
        description="Cleanly normalized scanned medicine record."
    )
    units_per_month: float = Field(
        default=60.0,
        gt=0.0,
        description="Patient's expected monthly unit consumption."
    )
    request_id: Optional[str] = Field(
        default=None,
        description="Idempotency key."
    )


class MatchResult(BaseModel):
    """Result of deterministic equivalence matching and savings evaluation.
    
    Safety Rules Enforced:
    1. If tier != EXACT, NO alternative may contain savings calculations.
    2. If workflow_state != READY_FOR_MATCHING, tier MUST be NONE.
    3. If tier == EXACT, workflow_state MUST be READY_FOR_MATCHING.
    4. Mandatory disclaimer is unconditionally present.
    """
    tier: MatchTier = Field(
        ...,
        description="Deterministic equivalence tier: EXACT, CLOSE, or NONE."
    )
    workflow_state: ScanWorkflowState = Field(
        ...,
        description="Perception workflow state."
    )
    scanned_product_id: Optional[str] = Field(
        default=None,
        description="ID of scanned product if successfully registered."
    )
    matched_alternatives: List[MatchAlternative] = Field(
        default_factory=list,
        description="Ranked generic alternatives from catalogue."
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Safety warnings (e.g. 'Release type differs', 'NTI precaution')."
    )
    disclaimer: str = Field(
        default=MANDATORY_DISCLAIMER,
        description="Mandatory medical safety disclaimer."
    )
    data_version: str = Field(
        default="1.0.0",
        description="Version/date of the reference generic catalogue."
    )

    @field_validator("disclaimer")
    @classmethod
    def validate_disclaimer_presence(cls, v: str) -> str:
        if MANDATORY_DISCLAIMER not in v:
            raise ValueError(f"Mandatory disclaimer cannot be omitted or altered. Must contain: '{MANDATORY_DISCLAIMER}'")
        return v

    @model_validator(mode="after")
    def validate_safety_and_tier_invariants(self) -> "MatchResult":
        # 1. Enforce workflow state vs match tier legality
        validate_state_tier_combination(self.workflow_state, self.tier)

        # 2. Enforce savings prohibition on non-EXACT tiers
        if self.tier != MatchTier.EXACT:
            for alt in self.matched_alternatives:
                if alt.savings is not None:
                    raise ValueError(
                        f"Non-EXACT tier '{self.tier.value}' is prohibited from containing savings calculations."
                    )
        
        # 3. Enforce that EXACT tier requires at least one alternative
        if self.tier == MatchTier.EXACT and not self.matched_alternatives:
            raise ValueError("MatchResult cannot claim EXACT tier with zero matched alternatives.")

        return self
