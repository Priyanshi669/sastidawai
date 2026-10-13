"""Evidence reconciliation and cross-modal safety gates (Vision vs OCR vs Rules).

Safety Invariants:
1. OCR is strictly supporting evidence, NEVER the final authority on equivalence.
2. Contradictions between VLM perception and OCR text across critical dimensions
   (strength, active moiety, dosage form, release type) IMMEDIATELY block EXACT tier.
3. Confidence scores from VLM and OCR are NEVER averaged into proof of identity.
4. OCR agreement alone does not authorize an EXACT match; match authorization
   remains exclusively governed by the deterministic 5-dimension catalogue matcher.
5. OCR failure or unavailability may be bypassed ONLY when independent vision
   evidence is fully verified and non-conflicting.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from ml.resolver.normalize import (
    are_strengths_equivalent,
    normalize_dosage_form,
    normalize_release_type,
    normalize_salt_name,
    normalize_strength,
)
from ml.schemas.enums import (
    AdministrationRoute,
    DosageForm,
    ReleaseType,
    ScanWorkflowState,
)
from ml.schemas.extraction import (
    ConflictField,
    ExtractionConflict,
    RawMedicineExtraction,
)
from ml.schemas.ocr import OCRResult, OCRTextLine


class CrossVerificationConflict(BaseModel):
    """Detailed record of a discrepancy detected between vision and OCR evidence."""
    field: ConflictField
    vision_value: Optional[str] = Field(default=None)
    ocr_value: Optional[str] = Field(default=None)
    description: str


class EvidenceCrossVerificationResult(BaseModel):
    """Outcome of multi-modal evidence reconciliation between vision and OCR."""
    workflow_state: ScanWorkflowState
    is_concordant: bool = Field(..., description="True if vision and OCR agree without contradictions.")
    can_authorize_exact: bool = Field(..., description="True if no critical conflicts or deficiencies exist.")
    conflicts: List[CrossVerificationConflict] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    parsed_ocr_dimensions: Dict[str, Any] = Field(default_factory=dict)
    reconciled_extraction: RawMedicineExtraction


def parse_dimensions_from_ocr(ocr_result: OCRResult) -> Dict[str, Any]:
    """Extracts candidate clinical dimensions from raw OCR text using deterministic normalizers."""
    if not ocr_result.is_successful or not ocr_result.raw_text:
        return {
            "salts": [],
            "dosage_form": DosageForm.UNKNOWN,
            "release_type": ReleaseType.UNKNOWN,
            "strengths": {},
        }

    text = ocr_result.raw_text.lower()

    # 1. Dosage form parsing
    dosage_form = normalize_dosage_form(text)

    # 2. Release type parsing
    release_type = normalize_release_type(text)

    # 3. Strength and salt parsing via regex patterns commonly on Indian medicine packaging
    # Matches patterns like: "amoxycillin 500 mg", "metformin hydrochloride 1000 mg", "500mg", "125 mg"
    found_salts: Set[str] = set()
    found_strengths: Dict[str, List[Tuple[float, str, Optional[str]]]] = {}

    # Scan lines for salt names and associated numbers
    candidate_moieties = [
        ("amoxicillin", "amoxicillin"),
        ("amoxycillin", "amoxicillin"),
        ("clavulanic acid", "clavulanic acid"),
        ("clavulanic", "clavulanic acid"),
        ("clavulanate", "clavulanic acid"),
        ("metformin", "metformin"),
        ("paracetamol", "paracetamol"),
        ("acetaminophen", "paracetamol"),
        ("ciprofloxacin", "ciprofloxacin"),
        ("azithromycin", "azithromycin"),
        ("atorvastatin", "atorvastatin"),
        ("pantoprazole", "pantoprazole"),
        ("omeprazole", "omeprazole"),
        ("telmisartan", "telmisartan"),
        ("amlodipine", "amlodipine"),
        ("losartan", "losartan"),
        ("glimepiride", "glimepiride"),
        ("ibuprofen", "ibuprofen"),
        ("cetirizine", "cetirizine"),
        ("montelukast", "montelukast"),
        ("ranitidine", "ranitidine"),
    ]

    for line in ocr_result.lines:
        line_txt = line.text.lower()

        for search_token, canonical_m in candidate_moieties:
            if search_token in line_txt:
                found_salts.add(canonical_m)

                # Extract numeric strength associated with this line
                matches = re.findall(r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|iu|%|ml)\b", line_txt)
                for val_str, unit in matches:
                    try:
                        val = float(val_str)
                        per = "5ml" if ("5ml" in line_txt or "5 ml" in line_txt) else ("tablet" if "tablet" in line_txt else None)
                        if canonical_m not in found_strengths:
                            found_strengths[canonical_m] = []
                        strength_entry = (val, unit, per)
                        if strength_entry not in found_strengths[canonical_m]:
                            found_strengths[canonical_m].append(strength_entry)
                    except ValueError:
                        continue

    return {
        "salts": sorted(list(found_salts)),
        "dosage_form": dosage_form,
        "release_type": release_type,
        "strengths": found_strengths,
    }


def cross_verify_vision_and_ocr(
    vision_extraction: RawMedicineExtraction,
    ocr_result: OCRResult,
) -> EvidenceCrossVerificationResult:
    """Cross-checks vision-language model readings against independent local OCR evidence.
    
    Safety Rules:
    1. If OCR fails or is unavailable:
       - If vision extraction is complete and verified -> passes with a warning.
       - If vision extraction is incomplete -> fails closed as EXTRACTION_INCOMPLETE.
    2. If OCR extracts contradictory critical dimensions:
       - Conflicting strength -> marks conflict, blocks EXACT, state = NEEDS_USER_CONFIRMATION.
       - Conflicting active moiety -> marks conflict, blocks EXACT, state = NEEDS_USER_CONFIRMATION.
       - Conflicting dosage form -> marks conflict, blocks EXACT, state = NEEDS_USER_CONFIRMATION.
       - Conflicting release type -> marks conflict, blocks EXACT, state = NEEDS_USER_CONFIRMATION.
    3. Confidence scores are never averaged into proof of equivalence.
    4. Agreement alone does not produce an EXACT match.
    """
    conflicts: List[CrossVerificationConflict] = []
    warnings: List[str] = []

    # 1. Handle OCR failure, timeout, or unavailability
    if not ocr_result.is_successful:
        warnings.append(
            f"Local OCR verification unavailable: {ocr_result.error_message or 'Engine error'}. "
            "Proceeding with vision evidence alone under fail-safe monitoring."
        )

        # Check if vision extraction alone is complete and verified
        is_complete = (
            vision_extraction.is_medicine_pack
            and not vision_extraction.has_critical_conflicts
            and len(vision_extraction.printed_composition) > 0
            and all(item.strength_value is not None for item in vision_extraction.printed_composition)
            and vision_extraction.dosage_form != DosageForm.UNKNOWN
            and vision_extraction.release_type != ReleaseType.UNKNOWN
        )

        state = ScanWorkflowState.READY_FOR_MATCHING if is_complete else (
            ScanWorkflowState.REJECT_IMAGE if not vision_extraction.is_medicine_pack else ScanWorkflowState.EXTRACTION_INCOMPLETE
        )

        return EvidenceCrossVerificationResult(
            workflow_state=state,
            is_concordant=False,
            can_authorize_exact=is_complete,
            conflicts=[],
            warnings=warnings,
            parsed_ocr_dimensions={},
            reconciled_extraction=vision_extraction,
        )

    # 2. Parse clinical dimensions from OCR plaintext
    ocr_dims = parse_dimensions_from_ocr(ocr_result)

    # 3. Cross-Check Active Ingredients (Moiety Identity)
    vision_moieties = {
        normalize_salt_name(item.salt_text)[0]: item
        for item in vision_extraction.printed_composition
        if normalize_salt_name(item.salt_text)[0]
    }
    ocr_moieties = set(ocr_dims["salts"])

    if ocr_moieties:
        # Check if OCR observed active moieties completely disjoint from vision
        disjoint_with_vision = ocr_moieties.isdisjoint(set(vision_moieties.keys()))
        if disjoint_with_vision and vision_moieties:
            conflicts.append(
                CrossVerificationConflict(
                    field=ConflictField.INGREDIENT,
                    vision_value=", ".join(sorted(vision_moieties.keys())),
                    ocr_value=", ".join(sorted(ocr_moieties)),
                    description=(
                        f"Active ingredient contradiction: Vision read '{', '.join(sorted(vision_moieties.keys()))}', "
                        f"but OCR read '{', '.join(sorted(ocr_moieties))}'."
                    ),
                )
            )
        elif len(vision_moieties) > 1 and len(ocr_moieties) < len(vision_moieties):
            # Vision detected combination formula, but OCR text only detected single-ingredient formulation
            missing_in_ocr = set(vision_moieties.keys()) - ocr_moieties
            conflicts.append(
                CrossVerificationConflict(
                    field=ConflictField.INGREDIENT,
                    vision_value=", ".join(sorted(vision_moieties.keys())),
                    ocr_value=", ".join(sorted(ocr_moieties)),
                    description=(
                        f"Combination formula discrepancy: Vision detected combination with "
                        f"'{', '.join(sorted(missing_in_ocr))}', but OCR text does not contain it."
                    ),
                )
            )
        elif len(ocr_moieties) > len(vision_moieties):
            # OCR detected additional ingredients not present in vision extraction
            extra_in_ocr = ocr_moieties - set(vision_moieties.keys())
            conflicts.append(
                CrossVerificationConflict(
                    field=ConflictField.INGREDIENT,
                    vision_value=", ".join(sorted(vision_moieties.keys())),
                    ocr_value=", ".join(sorted(ocr_moieties)),
                    description=(
                        f"Ingredient count discrepancy: OCR detected additional active ingredients: "
                        f"'{', '.join(sorted(extra_in_ocr))}'."
                    ),
                )
            )

    # 4. Cross-Check Strengths and Denominators
    for salt_name, item in vision_moieties.items():
        if salt_name in ocr_dims["strengths"] and item.strength_value is not None:
            observed_ocr_list = ocr_dims["strengths"][salt_name]
            # Check if any OCR strength matches normalized vision strength
            norm_v = normalize_strength(item.strength_value, item.strength_unit, item.per)

            matches_any_ocr = False
            for ocr_v, ocr_u, ocr_p in observed_ocr_list:
                norm_o = normalize_strength(ocr_v, ocr_u, ocr_p)
                if (
                    norm_v.canonical_value == norm_o.canonical_value
                    and norm_v.canonical_unit == norm_o.canonical_unit
                    and norm_v.canonical_per == norm_o.canonical_per
                ):
                    matches_any_ocr = True
                    break

            if not matches_any_ocr and observed_ocr_list:
                # Contradictory strength read by OCR
                first_ocr = observed_ocr_list[0]
                conflicts.append(
                    CrossVerificationConflict(
                        field=ConflictField.STRENGTH,
                        vision_value=f"{item.strength_value} {item.strength_unit or ''} {('per ' + item.per) if item.per else ''}".strip(),
                        ocr_value=f"{first_ocr[0]} {first_ocr[1]} {('per ' + first_ocr[2]) if first_ocr[2] else ''}".strip(),
                        description=(
                            f"Strength contradiction for '{salt_name}': Vision extracted "
                            f"{item.strength_value} {item.strength_unit}, but OCR detected {first_ocr[0]} {first_ocr[1]}."
                        ),
                    )
                )

    # 5. Cross-Check Dosage Form
    if (
        ocr_dims["dosage_form"] not in (DosageForm.UNKNOWN, DosageForm.OTHER)
        and vision_extraction.dosage_form not in (DosageForm.UNKNOWN, DosageForm.OTHER)
    ):
        if ocr_dims["dosage_form"] != vision_extraction.dosage_form:
            conflicts.append(
                CrossVerificationConflict(
                    field=ConflictField.DOSAGE_FORM,
                    vision_value=vision_extraction.dosage_form.value,
                    ocr_value=ocr_dims["dosage_form"].value,
                    description=(
                        f"Dosage form discrepancy: Vision extracted '{vision_extraction.dosage_form.value}', "
                        f"but OCR read '{ocr_dims['dosage_form'].value}'."
                    ),
                )
            )

    # 6. Cross-Check Release Type
    if (
        ocr_dims["release_type"] != ReleaseType.UNKNOWN
        and vision_extraction.release_type != ReleaseType.UNKNOWN
    ):
        if ocr_dims["release_type"] != vision_extraction.release_type:
            conflicts.append(
                CrossVerificationConflict(
                    field=ConflictField.RELEASE_TYPE,
                    vision_value=vision_extraction.release_type.value,
                    ocr_value=ocr_dims["release_type"].value,
                    description=(
                        f"Release type discrepancy: Vision extracted '{vision_extraction.release_type.value}', "
                        f"but OCR read '{ocr_dims['release_type'].value}'."
                    ),
                )
            )

    # 7. Synthesize Reconciled Extraction
    # Convert CrossVerificationConflicts into ExtractionConflicts
    combined_conflicts: List[ExtractionConflict] = list(vision_extraction.conflicts)
    for c in conflicts:
        combined_conflicts.append(
            ExtractionConflict(
                field=c.field,
                image_indices=[0],
                conflicting_values=[c.vision_value or "None", c.ocr_value or "None"],
                description=c.description,
            )
        )

    # Demote conflicting fields in extraction: never select one over another
    reconciled_items = list(vision_extraction.printed_composition)
    if any(c.field == ConflictField.STRENGTH for c in conflicts):
        reconciled_items = [
            item.model_copy(update={"strength_value": None, "strength_unit": None})
            for item in reconciled_items
        ]

    reconciled_form = (
        DosageForm.UNKNOWN
        if any(c.field == ConflictField.DOSAGE_FORM for c in conflicts)
        else vision_extraction.dosage_form
    )

    reconciled_release = (
        ReleaseType.UNKNOWN
        if any(c.field == ConflictField.RELEASE_TYPE for c in conflicts)
        else vision_extraction.release_type
    )

    # Confidence penalty on conflicting fields: NEVER average confidences
    reconciled_conf = vision_extraction.field_confidence.model_copy()
    if any(c.field == ConflictField.STRENGTH for c in conflicts):
        reconciled_conf.strength = 0.0
    if any(c.field == ConflictField.INGREDIENT for c in conflicts):
        reconciled_conf.composition = 0.0
    if any(c.field == ConflictField.DOSAGE_FORM for c in conflicts):
        reconciled_conf.dosage_form = 0.0
    if any(c.field == ConflictField.RELEASE_TYPE for c in conflicts):
        reconciled_conf.release_type = 0.0

    reconciled_extraction = vision_extraction.model_copy(
        update={
            "printed_composition": reconciled_items,
            "dosage_form": reconciled_form,
            "release_type": reconciled_release,
            "field_confidence": reconciled_conf,
            "conflicts": combined_conflicts,
        }
    )

    # 8. Determine Workflow State
    if not vision_extraction.is_medicine_pack:
        state = ScanWorkflowState.REJECT_IMAGE
    elif conflicts or combined_conflicts:
        state = ScanWorkflowState.NEEDS_USER_CONFIRMATION
    elif (
        not vision_extraction.printed_composition
        or any(item.strength_value is None for item in vision_extraction.printed_composition)
        or vision_extraction.dosage_form == DosageForm.UNKNOWN
        or vision_extraction.release_type == ReleaseType.UNKNOWN
    ):
        state = ScanWorkflowState.EXTRACTION_INCOMPLETE
    else:
        state = ScanWorkflowState.READY_FOR_MATCHING

    can_authorize = (len(conflicts) == 0 and state == ScanWorkflowState.READY_FOR_MATCHING)

    return EvidenceCrossVerificationResult(
        workflow_state=state,
        is_concordant=len(conflicts) == 0,
        can_authorize_exact=can_authorize,
        conflicts=conflicts,
        warnings=warnings,
        parsed_ocr_dimensions=ocr_dims,
        reconciled_extraction=reconciled_extraction,
    )
