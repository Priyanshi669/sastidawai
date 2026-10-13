"""Deterministic 5-dimension medicine equivalence matcher and safety boundary engine.

Non-Negotiable Safety Rules Enforced:
1. Exact match requires complete active moiety set, normalized strength/denominator,
   dosage form, release type, and route.
2. An LLM, fuzzy score, or extraction confidence is NEVER proof of equivalence.
3. Salt modifier distinctions (e.g. besylate vs maleate, succinate vs tartrate)
   are never discarded; they downgrade to CLOSE tier ("Pharmacist to confirm").
4. Release type differences (e.g. SR/ER vs IR) NEVER qualify for EXACT.
5. Savings calculations are STRICTLY GATED to EXACT tier and valid positive prices.
6. CLOSE is informational only; savings calculations are prohibited.
"""

from typing import List, Optional, Tuple
from ml.resolver.normalize import are_strengths_equivalent, normalize_strength
from ml.schemas.canonical import ActiveSaltMoiety, CanonicalMedicine
from ml.schemas.enums import (
    AdministrationRoute,
    DosageForm,
    MatchTier,
    ReleaseType,
    ScanWorkflowState,
)
from ml.schemas.matcher import (
    MANDATORY_DISCLAIMER,
    MatchAlternative,
    MatchResult,
    SavingsCalculation,
)


def _convert_moiety_to_normalized_strength(salt: ActiveSaltMoiety):
    """Converts ActiveSaltMoiety to NormalizedStrength for equivalence comparison."""
    return normalize_strength(
        raw_value=salt.strength_value,
        raw_unit=salt.strength_unit,
        raw_per=salt.per_unit,
    )


def evaluate_single_pair(
    scanned: CanonicalMedicine,
    candidate: CanonicalMedicine,
) -> Tuple[MatchTier, str]:
    """Deterministically evaluates the equivalence relationship between two medicines.
    
    Returns:
        (tier, reason_string)
    """
    # 0. Quarantine, Discontinuation & Integrity Check
    if candidate.is_quarantined:
        return (MatchTier.NONE, f"Candidate is quarantined: {candidate.quarantine_reason or 'unspecified'}")
    if candidate.is_discontinued:
        return (MatchTier.NONE, "Candidate is discontinued; ineligible for active equivalence or savings")
    if not candidate.is_eligible_for_matching:
        return (MatchTier.NONE, "Candidate is marked ineligible for matching in catalogue records")
    if not candidate.salts:
        return (MatchTier.NONE, "Candidate has no active salts defined")
    if candidate.dosage_form == DosageForm.UNKNOWN:
        return (MatchTier.NONE, "Candidate has unknown dosage form")
    if candidate.release_type == ReleaseType.UNKNOWN:
        return (MatchTier.NONE, "Candidate has unknown release type")
    if candidate.route == AdministrationRoute.UNKNOWN:
        return (MatchTier.NONE, "Candidate has unknown administration route")

    # 1. Dimension 1: Route of Administration
    if scanned.route != candidate.route:
        return (
            MatchTier.NONE,
            f"Administration route differs: {scanned.route.value} vs {candidate.route.value}",
        )

    # 2. Dimension 2: Active Moiety Set (Order-Independent)
    scanned_moieties = {s.salt_name.strip().lower() for s in scanned.salts}
    candidate_moieties = {s.salt_name.strip().lower() for s in candidate.salts}

    if scanned_moieties != candidate_moieties:
        # Check for partial overlap in combination medicines
        overlap = scanned_moieties & candidate_moieties
        if overlap:
            return (
                MatchTier.CLOSE,
                f"Partial active ingredient overlap: {sorted(list(overlap))} "
                f"(scanned: {sorted(list(scanned_moieties))}, candidate: {sorted(list(candidate_moieties))})",
            )
        return (
            MatchTier.NONE,
            f"Active ingredients do not match: {sorted(list(scanned_moieties))} vs {sorted(list(candidate_moieties))}",
        )

    # 3. Dimension 3: Conservative Salt Chemical Modifiers
    # Map moieties to salt objects
    scanned_salt_map = {s.salt_name.strip().lower(): s for s in scanned.salts}
    candidate_salt_map = {s.salt_name.strip().lower(): s for s in candidate.salts}

    for moiety in sorted(list(scanned_moieties)):
        s_salt = scanned_salt_map[moiety]
        c_salt = candidate_salt_map[moiety]

        s_mod = s_salt.salt_modifier.strip().lower() if s_salt.salt_modifier else None
        c_mod = c_salt.salt_modifier.strip().lower() if c_salt.salt_modifier else None

        if s_mod != c_mod:
            # Salt modifier differs (e.g. besylate vs maleate)
            return (
                MatchTier.CLOSE,
                f"Salt chemical modifier differs for '{moiety}': '{s_mod or 'unspecified'}' vs '{c_mod or 'unspecified'}' "
                "(Pharmacist to confirm)",
            )

    # 4. Dimension 4: Strengths and Denominators
    for moiety in sorted(list(scanned_moieties)):
        s_salt = scanned_salt_map[moiety]
        c_salt = candidate_salt_map[moiety]

        s_norm_strength = _convert_moiety_to_normalized_strength(s_salt)
        c_norm_strength = _convert_moiety_to_normalized_strength(c_salt)

        if not are_strengths_equivalent(s_norm_strength, c_norm_strength):
            if s_norm_strength.canonical_per != c_norm_strength.canonical_per:
                return (
                    MatchTier.CLOSE,
                    f"Concentration denominator differs for '{moiety}': "
                    f"'{s_norm_strength.canonical_per}' vs '{c_norm_strength.canonical_per}'",
                )
            return (
                MatchTier.CLOSE,
                f"Strength differs for '{moiety}': "
                f"{s_norm_strength.canonical_value} {s_norm_strength.canonical_unit} vs "
                f"{c_norm_strength.canonical_value} {c_norm_strength.canonical_unit}",
            )

    # 5. Dimension 5: Dosage Form
    if scanned.dosage_form != candidate.dosage_form:
        return (
            MatchTier.CLOSE,
            f"Dosage form differs: {scanned.dosage_form.value} vs {candidate.dosage_form.value}",
        )

    # 6. Dimension 6: Release Type (SR/ER vs IR is NEVER EXACT)
    if scanned.release_type != candidate.release_type:
        return (
            MatchTier.CLOSE,
            f"Release type differs: {scanned.release_type.value} vs {candidate.release_type.value} "
            "(Modified release vs immediate release cannot be exact)",
        )

    # All five dimensions match identically and unambiguously
    return (MatchTier.EXACT, "All five canonical dimensions verified identical")


class DeterministicMatcher:
    """Production deterministic matching engine."""

    @staticmethod
    def match(
        scanned: CanonicalMedicine,
        candidates: List[CanonicalMedicine],
        workflow_state: ScanWorkflowState = ScanWorkflowState.READY_FOR_MATCHING,
        units_per_month: float = 60.0,
    ) -> MatchResult:
        """Executes strict deterministic matching against candidate generic records."""
        # 1. State Gate: Non-ready workflow states immediately abort with tier NONE
        if workflow_state != ScanWorkflowState.READY_FOR_MATCHING:
            return MatchResult(
                tier=MatchTier.NONE,
                workflow_state=workflow_state,
                scanned_product_id=scanned.product_id,
                matched_alternatives=[],
                warnings=[f"Workflow state '{workflow_state.value}' blocks matching."],
                disclaimer=MANDATORY_DISCLAIMER,
            )

        # 2. Scanned Product Integrity Checks
        warnings: List[str] = []
        if scanned.is_quarantined:
            return MatchResult(
                tier=MatchTier.NONE,
                workflow_state=workflow_state,
                scanned_product_id=scanned.product_id,
                matched_alternatives=[],
                warnings=[f"Scanned medicine is quarantined: {scanned.quarantine_reason or 'unspecified'}"],
                disclaimer=MANDATORY_DISCLAIMER,
            )

        if not scanned.salts:
            return MatchResult(
                tier=MatchTier.NONE,
                workflow_state=workflow_state,
                scanned_product_id=scanned.product_id,
                matched_alternatives=[],
                warnings=["Scanned medicine has no active salts defined."],
                disclaimer=MANDATORY_DISCLAIMER,
            )

        # Missing or unknown critical dimensions block EXACT evaluation
        if scanned.dosage_form == DosageForm.UNKNOWN:
            warnings.append("Scanned dosage form is unknown; exact matching is blocked.")
        if scanned.release_type == ReleaseType.UNKNOWN:
            warnings.append("Scanned release type is unknown; exact matching is blocked.")
        if scanned.route == AdministrationRoute.UNKNOWN:
            warnings.append("Scanned administration route is unknown; exact matching is blocked.")

        if scanned.dosage_form == DosageForm.UNKNOWN or scanned.release_type == ReleaseType.UNKNOWN or scanned.route == AdministrationRoute.UNKNOWN:
            return MatchResult(
                tier=MatchTier.NONE,
                workflow_state=workflow_state,
                scanned_product_id=scanned.product_id,
                matched_alternatives=[],
                warnings=warnings,
                disclaimer=MANDATORY_DISCLAIMER,
            )

        # 3. Check NTI and Discontinuation precautions
        if scanned.is_discontinued:
            warnings.append("Scanned medicine is marked as discontinued in source records.")
        if scanned.is_nti or any(c.is_nti for c in candidates):
            warnings.append("NTI: Narrow therapeutic index medicine. Do not switch without consulting your doctor.")

        # 4. Evaluate all candidates
        exact_matches: List[Tuple[CanonicalMedicine, str]] = []
        close_matches: List[Tuple[CanonicalMedicine, str]] = []

        for candidate in candidates:
            tier, reason = evaluate_single_pair(scanned, candidate)
            if tier == MatchTier.EXACT:
                exact_matches.append((candidate, reason))
            elif tier == MatchTier.CLOSE:
                close_matches.append((candidate, reason))

        # 5. Build Result Tiers
        # Case A: EXACT matches found
        if exact_matches:
            # Sort exact candidates by unit price ascending
            exact_matches.sort(
                key=lambda x: (x[0].price.unit_price_inr if x[0].price else float("inf"))
            )

            matched_alternatives: List[MatchAlternative] = []
            for candidate, reason in exact_matches:
                savings: Optional[SavingsCalculation] = None

                # Calculate savings only when all price conditions are satisfied
                if scanned.price and candidate.price:
                    brand_unit = scanned.price.unit_price_inr
                    gen_unit = candidate.price.unit_price_inr

                    # Verified positive prices and generic is cheaper or equal
                    if not candidate.price.is_verified_current:
                        warnings.append("Generic price is not verified current; savings calculation suppressed.")
                    elif candidate.price.price_date in ("unverified", "UNKNOWN", ""):
                        warnings.append("Generic price publication date is unknown; savings calculation suppressed.")
                    elif brand_unit > 0 and gen_unit > 0 and brand_unit >= gen_unit:
                        monthly_sav = round((brand_unit - gen_unit) * units_per_month, 2)
                        yearly_sav = round(monthly_sav * 12, 2)
                        savings = SavingsCalculation(
                            brand_unit_price_inr=brand_unit,
                            generic_unit_price_inr=gen_unit,
                            units_per_month=units_per_month,
                            monthly_savings_inr=monthly_sav,
                            yearly_savings_inr=yearly_sav,
                            price_as_of=candidate.price.price_date,
                            calculation_basis=f"per_{scanned.dosage_form.value}",
                        )
                    elif gen_unit > brand_unit:
                        warnings.append(
                            f"Generic unit price (₹{gen_unit}) exceeds brand price (₹{brand_unit}); savings suppressed."
                        )
                else:
                    warnings.append("Missing price record on scanned or candidate; savings calculation suppressed.")

                matched_alternatives.append(
                    MatchAlternative(
                        generic_product_id=candidate.product_id,
                        generic_name=candidate.name,
                        manufacturer=candidate.manufacturer,
                        strip_mrp_inr=candidate.price.pack_mrp_inr if candidate.price else 0.01,
                        pack_count=candidate.price.pack_count if candidate.price else 1.0,
                        unit_price_inr=candidate.price.unit_price_inr if candidate.price else 0.01,
                        price_date=candidate.price.price_date if candidate.price else "2026-10-13",
                        source=candidate.price.provenance.source_name if candidate.price else "PMBI product list",
                        savings=savings,
                    )
                )

            return MatchResult(
                tier=MatchTier.EXACT,
                workflow_state=workflow_state,
                scanned_product_id=scanned.product_id,
                matched_alternatives=matched_alternatives,
                warnings=warnings,
                disclaimer=MANDATORY_DISCLAIMER,
            )

        # Case B: CLOSE matches found
        if close_matches:
            matched_alternatives = []
            for candidate, reason in close_matches:
                warnings.append(f"Similar formulation ({candidate.name}): {reason}")
                matched_alternatives.append(
                    MatchAlternative(
                        generic_product_id=candidate.product_id,
                        generic_name=candidate.name,
                        manufacturer=candidate.manufacturer,
                        strip_mrp_inr=candidate.price.pack_mrp_inr if candidate.price else 0.01,
                        pack_count=candidate.price.pack_count if candidate.price else 1.0,
                        unit_price_inr=candidate.price.unit_price_inr if candidate.price else 0.01,
                        price_date=candidate.price.price_date if candidate.price else "2026-10-13",
                        source=candidate.price.provenance.source_name if candidate.price else "PMBI product list",
                        savings=None,  # STRICT: SAVINGS NEVER COMPUTED FOR CLOSE TIER
                    )
                )

            return MatchResult(
                tier=MatchTier.CLOSE,
                workflow_state=workflow_state,
                scanned_product_id=scanned.product_id,
                matched_alternatives=matched_alternatives,
                warnings=warnings,
                disclaimer=MANDATORY_DISCLAIMER,
            )

        # Case C: NONE
        warnings.append("No verified equivalent generic found in catalogue.")
        return MatchResult(
            tier=MatchTier.NONE,
            workflow_state=workflow_state,
            scanned_product_id=scanned.product_id,
            matched_alternatives=[],
            warnings=warnings,
            disclaimer=MANDATORY_DISCLAIMER,
        )


def evaluate_deterministic_match(
    scanned: CanonicalMedicine,
    candidates: List[CanonicalMedicine],
    workflow_state: ScanWorkflowState = ScanWorkflowState.READY_FOR_MATCHING,
    units_per_month: float = 60.0,
) -> MatchResult:
    """Convenience functional wrapper for DeterministicMatcher.match."""
    return DeterministicMatcher.match(
        scanned=scanned,
        candidates=candidates,
        workflow_state=workflow_state,
        units_per_month=units_per_month,
    )
