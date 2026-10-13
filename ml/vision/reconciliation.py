"""Multi-image extraction reconciliation and safety conflict resolution.

Safety Principles:
1. Contradictory critical fields (strength, active ingredient, dosage form, release type)
   across multi-image captures are NEVER silently merged or resolved by picking
   the highest-confidence value as truth.
2. Contradictions are explicitly preserved as `ExtractionConflict` records.
3. Any unresolved critical conflict blocks automatic `EXACT` matching and demotes
   the workflow state to `NEEDS_USER_CONFIRMATION` or `EXTRACTION_INCOMPLETE`.
4. Image quality success alone is never evidence of medicine identity or equivalence.
"""

from typing import List, Optional, Set, Tuple

from ml.resolver.normalize import normalize_salt_name, normalize_strength
from ml.schemas.canonical import ActiveSaltMoiety, CanonicalMedicine
from ml.schemas.enums import (
    AdministrationRoute,
    DosageForm,
    LegibilityGrade,
    ReleaseType,
    RxSchedule,
    ScanWorkflowState,
)
from ml.schemas.extraction import (
    ConflictField,
    ExtractionConflict,
    ExtractionFieldConfidence,
    PrintedCompositionItem,
    RawMedicineExtraction,
)


def detect_dosage_form_conflict(
    extractions: List[RawMedicineExtraction],
) -> Tuple[DosageForm, Optional[ExtractionConflict]]:
    """Detects conflicting dosage forms across extractions. Unknowns are ignored as non-conflicting."""
    known_forms = {}
    for idx, ext in enumerate(extractions):
        if ext.dosage_form not in (DosageForm.UNKNOWN, DosageForm.OTHER):
            known_forms[idx] = ext.dosage_form

    if not known_forms:
        return DosageForm.UNKNOWN, None

    unique_forms = set(known_forms.values())
    if len(unique_forms) == 1:
        return next(iter(unique_forms)), None

    # Contradictory dosage forms observed across distinct images (e.g. tablet vs capsule)
    conflict = ExtractionConflict(
        field=ConflictField.DOSAGE_FORM,
        image_indices=list(known_forms.keys()),
        conflicting_values=[f.value for f in known_forms.values()],
        description=f"Conflicting dosage forms observed across images: {', '.join(sorted(set(f.value for f in known_forms.values())))}.",
    )
    # Demote to UNKNOWN - never guess or pick highest confidence
    return DosageForm.UNKNOWN, conflict


def detect_release_type_conflict(
    extractions: List[RawMedicineExtraction],
) -> Tuple[ReleaseType, Optional[ExtractionConflict]]:
    """Detects conflicting release types across extractions. Unknowns are ignored."""
    known_types = {}
    for idx, ext in enumerate(extractions):
        if ext.release_type != ReleaseType.UNKNOWN:
            known_types[idx] = ext.release_type

    if not known_types:
        return ReleaseType.UNKNOWN, None

    unique_types = set(known_types.values())
    if len(unique_types) == 1:
        return next(iter(unique_types)), None

    conflict = ExtractionConflict(
        field=ConflictField.RELEASE_TYPE,
        image_indices=list(known_types.keys()),
        conflicting_values=[r.value for r in known_types.values()],
        description=f"Conflicting release types observed across images: {', '.join(sorted(set(r.value for r in known_types.values())))}.",
    )
    return ReleaseType.UNKNOWN, conflict


def detect_route_conflict(
    extractions: List[RawMedicineExtraction],
) -> Tuple[AdministrationRoute, Optional[ExtractionConflict]]:
    """Detects conflicting administration routes across extractions."""
    known_routes = {}
    for idx, ext in enumerate(extractions):
        if ext.route != AdministrationRoute.UNKNOWN:
            known_routes[idx] = ext.route

    if not known_routes:
        return AdministrationRoute.UNKNOWN, None

    unique_routes = set(known_routes.values())
    if len(unique_routes) == 1:
        return next(iter(unique_routes)), None

    conflict = ExtractionConflict(
        field=ConflictField.ROUTE,
        image_indices=list(known_routes.keys()),
        conflicting_values=[r.value for r in known_routes.values()],
        description=f"Conflicting administration routes observed across images: {', '.join(sorted(set(r.value for r in known_routes.values())))}.",
    )
    return AdministrationRoute.UNKNOWN, conflict


def detect_composition_and_strength_conflicts(
    extractions: List[RawMedicineExtraction],
) -> Tuple[List[PrintedCompositionItem], List[ExtractionConflict]]:
    """Reconciles active ingredient composition and strength across multiple images.
    
    Rules:
    1. If two images observe the same salt moiety but different strengths, mark conflict.
       Do NOT select the highest confidence strength; set strength to None.
    2. If two images have completely disjoint, contradictory active ingredients, mark conflict.
    """
    conflicts: List[ExtractionConflict] = []

    # Map normalized salt -> list of (image_index, item)
    salt_occurrences = {}
    for idx, ext in enumerate(extractions):
        for item in ext.printed_composition:
            norm_salt = normalize_salt_name(item.salt_text)[0]
            if norm_salt not in salt_occurrences:
                salt_occurrences[norm_salt] = []
            salt_occurrences[norm_salt].append((idx, item))

    # Check for disjoint ingredients across images that each have non-empty compositions
    active_exts = [(idx, ext) for idx, ext in enumerate(extractions) if ext.printed_composition]
    if len(active_exts) > 1:
        salt_sets = []
        for idx, ext in active_exts:
            s_set = {normalize_salt_name(i.salt_text)[0] for i in ext.printed_composition}
            salt_sets.append((idx, s_set))

        # Check all pairs for complete disjointness
        for i in range(len(salt_sets)):
            for j in range(i + 1, len(salt_sets)):
                idx1, set1 = salt_sets[i]
                idx2, set2 = salt_sets[j]
                if set1 and set2 and set1.isdisjoint(set2):
                    conflicts.append(
                        ExtractionConflict(
                            field=ConflictField.INGREDIENT,
                            image_indices=[idx1, idx2],
                            conflicting_values=[", ".join(sorted(set1)), ", ".join(sorted(set2))],
                            description=f"Disjoint active ingredients observed between image {idx1 + 1} and image {idx2 + 1}.",
                        )
                    )

    # Check per-salt strength consistency
    reconciled_items: List[PrintedCompositionItem] = []
    for norm_salt, occurrences in salt_occurrences.items():
        base_item = occurrences[0][1]

        # Collect observed strengths with non-null values
        observed_strengths = []
        for idx, item in occurrences:
            if item.strength_value is not None:
                observed_strengths.append((idx, item))

        if not observed_strengths:
            # Strength unreadable in all observations
            reconciled_items.append(
                PrintedCompositionItem(
                    salt_text=base_item.salt_text,
                    strength_value=None,
                    strength_unit=None,
                    per=base_item.per,
                )
            )
            continue

        # Normalize observed strengths for comparison
        norm_strengths = []
        for idx, item in observed_strengths:
            n_str = normalize_strength(
                item.strength_value,
                item.strength_unit,
                item.per,
            )
            norm_strengths.append((idx, n_str.canonical_value, n_str.canonical_unit, n_str.canonical_per, item))

        # Compare against first observed strength
        ref_val, ref_unit, ref_per = norm_strengths[0][1], norm_strengths[0][2], norm_strengths[0][3]
        has_strength_conflict = False
        conflict_values = []
        conflict_indices = []

        for idx, n_val, n_unit, n_per, item in norm_strengths:
            val_str = f"{item.strength_value} {item.strength_unit or ''} {('per ' + item.per) if item.per else ''}".strip()
            conflict_values.append(val_str)
            conflict_indices.append(idx)
            if n_val != ref_val or n_unit != ref_unit or n_per != ref_per:
                has_strength_conflict = True

        if has_strength_conflict:
            conflicts.append(
                ExtractionConflict(
                    field=ConflictField.STRENGTH,
                    image_indices=conflict_indices,
                    conflicting_values=conflict_values,
                    description=f"Contradictory strengths observed for ingredient '{norm_salt}': {', '.join(set(conflict_values))}.",
                )
            )
            # Crucial rule: Never pick the highest confidence value. Set to None.
            reconciled_items.append(
                PrintedCompositionItem(
                    salt_text=base_item.salt_text,
                    strength_value=None,
                    strength_unit=None,
                    per=None,
                )
            )
        else:
            first_obs = observed_strengths[0][1]
            reconciled_items.append(
                PrintedCompositionItem(
                    salt_text=base_item.salt_text,
                    strength_value=first_obs.strength_value,
                    strength_unit=first_obs.strength_unit,
                    per=first_obs.per,
                )
            )

    return reconciled_items, conflicts


def reconcile_extractions(
    extractions: List[RawMedicineExtraction],
) -> RawMedicineExtraction:
    """Fuses 1 to 3 extractions into a unified extraction while preserving all conflicts."""
    if not extractions:
        raise ValueError("At least one extraction required for multi-image reconciliation.")

    if len(extractions) == 1:
        return extractions[0]

    all_conflicts: List[ExtractionConflict] = []

    # 1. Check medicine pack consensus
    med_flags = [ext.is_medicine_pack for ext in extractions]
    if False in med_flags and True in med_flags:
        all_conflicts.append(
            ExtractionConflict(
                field=ConflictField.IS_MEDICINE,
                image_indices=list(range(len(extractions))),
                conflicting_values=[str(f) for f in med_flags],
                description="Contradictory classification: some images depict medicine packs while others do not.",
            )
        )
        # Fail-closed: treat as non-medicine pack with conflicts
        return RawMedicineExtraction(
            is_medicine_pack=False,
            brand_name=None,
            printed_composition=[],
            conflicts=all_conflicts,
        )

    if all(not f for f in med_flags):
        return RawMedicineExtraction(
            is_medicine_pack=False,
            brand_name=None,
            printed_composition=[],
        )

    # 2. Dosage Form
    reconciled_form, form_conflict = detect_dosage_form_conflict(extractions)
    if form_conflict:
        all_conflicts.append(form_conflict)

    # 3. Release Type
    reconciled_release, release_conflict = detect_release_type_conflict(extractions)
    if release_conflict:
        all_conflicts.append(release_conflict)

    # 4. Route
    reconciled_route, route_conflict = detect_route_conflict(extractions)
    if route_conflict:
        all_conflicts.append(route_conflict)

    # 5. Composition and Strength
    reconciled_comp, comp_conflicts = detect_composition_and_strength_conflicts(extractions)
    all_conflicts.extend(comp_conflicts)

    # 6. Brand Name
    brand_names = {}
    for idx, ext in enumerate(extractions):
        if ext.brand_name:
            brand_names[idx] = ext.brand_name.strip()

    unique_brands = set(brand_names.values())
    reconciled_brand = None
    if len(unique_brands) == 1:
        reconciled_brand = next(iter(unique_brands))
    elif len(unique_brands) > 1:
        all_conflicts.append(
            ExtractionConflict(
                field=ConflictField.BRAND_NAME,
                image_indices=list(brand_names.keys()),
                conflicting_values=list(brand_names.values()),
                description=f"Contradictory brand names observed across images: {', '.join(sorted(unique_brands))}.",
            )
        )
        reconciled_brand = None  # Do not select one

    # 7. Confidence scores: if there's a conflict on a field, confidence is zeroed out
    field_conf = ExtractionFieldConfidence(
        brand_name=0.0 if any(c.field == ConflictField.BRAND_NAME for c in all_conflicts) else max((e.field_confidence.brand_name for e in extractions), default=0.0),
        composition=0.0 if any(c.field == ConflictField.INGREDIENT for c in all_conflicts) else max((e.field_confidence.composition for e in extractions), default=0.0),
        strength=0.0 if any(c.field == ConflictField.STRENGTH for c in all_conflicts) else max((e.field_confidence.strength for e in extractions), default=0.0),
        dosage_form=0.0 if any(c.field == ConflictField.DOSAGE_FORM for c in all_conflicts) else max((e.field_confidence.dosage_form for e in extractions), default=0.0),
        release_type=0.0 if any(c.field == ConflictField.RELEASE_TYPE for c in all_conflicts) else max((e.field_confidence.release_type for e in extractions), default=0.0),
    )

    return RawMedicineExtraction(
        is_medicine_pack=True,
        brand_name=reconciled_brand,
        manufacturer=next((e.manufacturer for e in extractions if e.manufacturer), None),
        printed_composition=reconciled_comp,
        dosage_form=reconciled_form,
        release_type=reconciled_release,
        route=reconciled_route,
        pack_size=next((e.pack_size for e in extractions if e.pack_size), None),
        mrp_inr=next((e.mrp_inr for e in extractions if e.mrp_inr), None),
        expiry=next((e.expiry for e in extractions if e.expiry), None),
        rx_schedule=next((e.rx_schedule for e in extractions if e.rx_schedule != RxSchedule.UNKNOWN), RxSchedule.UNKNOWN),
        legibility=min((e.legibility for e in extractions), default=LegibilityGrade.PARTIAL),
        field_confidence=field_conf,
        conflicts=all_conflicts,
    )


def determine_workflow_state(extraction: RawMedicineExtraction) -> ScanWorkflowState:
    """Evaluates the perception workflow state for an extraction result.
    
    Safety Rules:
    1. Non-medicine packs -> REJECT_IMAGE.
    2. Contradictory critical conflicts -> NEEDS_USER_CONFIRMATION.
    3. Missing or unreadable critical fields -> EXTRACTION_INCOMPLETE.
    4. Complete, unambiguous evidence -> READY_FOR_MATCHING.
    """
    if not extraction.is_medicine_pack:
        return ScanWorkflowState.REJECT_IMAGE

    if extraction.has_critical_conflicts:
        return ScanWorkflowState.NEEDS_USER_CONFIRMATION

    if not extraction.printed_composition:
        return ScanWorkflowState.EXTRACTION_INCOMPLETE

    for item in extraction.printed_composition:
        if item.strength_value is None:
            return ScanWorkflowState.EXTRACTION_INCOMPLETE

    if extraction.dosage_form == DosageForm.UNKNOWN:
        return ScanWorkflowState.EXTRACTION_INCOMPLETE

    return ScanWorkflowState.READY_FOR_MATCHING


def can_authorize_exact_matching(extraction: RawMedicineExtraction) -> Tuple[bool, List[str]]:
    """Strict gating check evaluating whether an extraction is eligible for EXACT matching.
    
    Returns (can_proceed, reasons).
    """
    reasons = []

    if not extraction.is_medicine_pack:
        reasons.append("Subject is not a verified medicine pack.")

    if extraction.has_critical_conflicts:
        conflict_types = [c.field.value for c in extraction.conflicts]
        reasons.append(f"Contradictory evidence across images on critical dimensions: {', '.join(conflict_types)}.")

    if not extraction.printed_composition:
        reasons.append("Active ingredient composition is missing or unreadable.")
    else:
        for item in extraction.printed_composition:
            if item.strength_value is None:
                reasons.append(f"Strength value for ingredient '{item.salt_text}' is missing or unreadable.")

    if extraction.dosage_form == DosageForm.UNKNOWN:
        reasons.append("Dosage form is unknown or unverified.")

    if extraction.release_type == ReleaseType.UNKNOWN:
        reasons.append("Release type is unknown or unverified.")

    state = determine_workflow_state(extraction)
    if state != ScanWorkflowState.READY_FOR_MATCHING:
        reasons.append(f"Workflow state '{state.value}' prohibits EXACT matching.")

    return len(reasons) == 0, reasons


def extraction_to_canonical(
    extraction: RawMedicineExtraction,
    product_id: str = "scanned_extracted",
) -> Tuple[Optional[CanonicalMedicine], ScanWorkflowState, List[str]]:
    """Converts a perception extraction into a CanonicalMedicine record with strict safety gating.
    
    Returns:
        (canonical_record, workflow_state, blocking_reasons)
        
    Safety Enforcements:
    1. If is_medicine_pack is False -> returns (None, REJECT_IMAGE, reasons).
    2. If has_critical_conflicts is True -> returns (quarantined_record, NEEDS_USER_CONFIRMATION, reasons).
    3. If critical fields missing/unreadable -> returns (quarantined_record, EXTRACTION_INCOMPLETE, reasons).
    4. Quarantined records and non-ready workflow states block EXACT matching deterministically.
    """
    state = determine_workflow_state(extraction)
    can_authorize, reasons = can_authorize_exact_matching(extraction)

    if not extraction.is_medicine_pack:
        return None, state, reasons

    # If matching cannot be authorized, return a quarantined canonical record that fails closed
    if not can_authorize or state != ScanWorkflowState.READY_FOR_MATCHING:
        quarantined = CanonicalMedicine(
            product_id=product_id,
            name=extraction.brand_name or "Unidentified Scanned Medicine",
            brand_name=extraction.brand_name,
            dosage_form=extraction.dosage_form,
            release_type=extraction.release_type,
            route=extraction.route,
            is_quarantined=True,
            quarantine_reason="; ".join(reasons) if reasons else f"Workflow state: {state.value}",
            is_eligible_for_matching=False,
            salts=[],
        )
        return quarantined, state, reasons

    # Build fully verified canonical salts
    salts: List[ActiveSaltMoiety] = []
    for item in extraction.printed_composition:
        norm_moiety, modifier, _ = normalize_salt_name(item.salt_text)
        n_str = normalize_strength(item.strength_value, item.strength_unit, item.per)
        salts.append(
            ActiveSaltMoiety(
                salt_name=norm_moiety or item.salt_text.strip().lower(),
                salt_modifier=modifier,
                strength_value=n_str.canonical_value if n_str.canonical_value is not None else item.strength_value,
                strength_unit=n_str.canonical_unit or item.strength_unit or "mg",
                per_unit=n_str.canonical_per or item.per or "unit",
                raw_text=item.salt_text,
            )
        )

    canonical = CanonicalMedicine(
        product_id=product_id,
        name=extraction.brand_name or "Scanned Medicine",
        brand_name=extraction.brand_name,
        salts=salts,
        dosage_form=extraction.dosage_form,
        release_type=extraction.release_type,
        route=extraction.route,
        is_quarantined=False,
        is_eligible_for_matching=True,
    )
    return canonical, ScanWorkflowState.READY_FOR_MATCHING, []
