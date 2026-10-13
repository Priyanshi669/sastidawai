"""Pure, deterministic normalization functions for medicine packaging entities.

This module contains ZERO external dependencies, network calls, databases, or heuristics.
All transformations are deterministic, pure functions operating on explicit input strings.
"""

from decimal import Decimal, InvalidOperation
import re
from typing import Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field

from ml.schemas.enums import AdministrationRoute, DosageForm, ReleaseType
from ml.schemas.extraction import PrintedCompositionItem


# ============================================================================
# Mass and Unit Conversion Constants
# ============================================================================

# Multipliers to convert supported mass units to canonical milligrams (mg)
MASS_TO_MG_MULTIPLIERS: Dict[str, Decimal] = {
    "g": Decimal("1000.0"),
    "gm": Decimal("1000.0"),
    "gram": Decimal("1000.0"),
    "grams": Decimal("1000.0"),
    "mg": Decimal("1.0"),
    "mgs": Decimal("1.0"),
    "milligram": Decimal("1.0"),
    "milligrams": Decimal("1.0"),
    "mcg": Decimal("0.001"),
    "ug": Decimal("0.001"),
    "µg": Decimal("0.001"),
    "microgram": Decimal("0.001"),
    "micrograms": Decimal("0.001"),
}

# Supported non-mass units (cannot be converted to mg, but normalized consistently)
NON_MASS_UNITS = {
    "iu": "iu",
    "i.u.": "iu",
    "international units": "iu",
    "units": "iu",
    "%": "%",
    "% w/v": "% w/v",
    "% w/w": "% w/w",
    "% v/v": "% v/v",
    "ml": "ml",
    "millilitre": "ml",
    "milliliter": "ml",
}

# Common salt modifiers to extract and separate from core moiety
SALT_MODIFIERS: Dict[str, str] = {
    "hydrochloride": "hydrochloride",
    "hcl": "hydrochloride",
    "sodium": "sodium",
    "potassium": "potassium",
    "besylate": "besylate",
    "besilate": "besylate",
    "maleate": "maleate",
    "tartrate": "tartrate",
    "succinate": "succinate",
    "fumarate": "fumarate",
    "valerate": "valerate",
    "propionate": "propionate",
    "dipropionate": "dipropionate",
    "phosphate": "phosphate",
    "sulfate": "sulfate",
    "sulphate": "sulfate",
    "mesylate": "mesylate",
    "mesilate": "mesylate",
    "calcium": "calcium",
    "acetate": "acetate",
    "citrate": "citrate",
    "gluconate": "gluconate",
    "lactate": "lactate",
    "nitrate": "nitrate",
}

# Standard British / Indian to international chemical moiety spelling aliases
MOIETY_SPELLING_MAP: Dict[str, str] = {
    "amoxycillin": "amoxicillin",
    "frusemide": "furosemide",
    "adrenaline": "epinephrine",
    "noradrenaline": "norepinephrine",
    "salbutamol": "albuterol",
    "paracetamol": "paracetamol",
    "acetaminophen": "paracetamol",
}


# ============================================================================
# Normalized Domain Models
# ============================================================================

class NormalizedStrength(BaseModel):
    """Normalized strength representation with strict denominator preservation."""
    raw_value: Optional[float] = None
    raw_unit: Optional[str] = None
    raw_per: Optional[str] = None
    canonical_value: Optional[float] = None
    canonical_unit: Optional[str] = None
    canonical_per: str = "unit"
    is_valid: bool = False
    error_reason: Optional[str] = None


class NormalizedIngredient(BaseModel):
    """Single normalized active ingredient."""
    raw_name: str
    canonical_moiety: str
    salt_modifier: Optional[str] = None
    strength: NormalizedStrength
    detected_release_marker: Optional[str] = None
    is_ambiguous: bool = False


class NormalizedComposition(BaseModel):
    """Order-independent normalized composition for a single or combination medicine."""
    ingredients: List[NormalizedIngredient] = Field(default_factory=list)
    is_combination: bool = False
    is_ambiguous: bool = False
    raw_text: Optional[str] = None


# ============================================================================
# Pure Normalization Functions
# ============================================================================

def normalize_strength(
    raw_value: Optional[Union[float, int, str]],
    raw_unit: Optional[str],
    raw_per: Optional[str] = None,
) -> NormalizedStrength:
    """Normalizes strength value, unit, and denominator.
    
    Invariants:
    1. Mass units (g, mg, mcg) convert strictly to mg using Decimal arithmetic.
    2. Non-mass units (IU, %, ml) preserve their distinct unit identity.
    3. Denominator (per unit vs per 5ml vs per ml) is preserved strictly.
    4. Missing or invalid values produce is_valid=False without guessing.
    """
    if raw_value is None or raw_unit is None:
        return NormalizedStrength(
            raw_value=float(raw_value) if isinstance(raw_value, (int, float)) else None,
            raw_unit=raw_unit,
            raw_per=raw_per,
            is_valid=False,
            error_reason="Missing strength value or unit",
        )

    # 1. Parse numeric value
    try:
        val_str = str(raw_value).strip()
        val_dec = Decimal(val_str)
        if val_dec <= Decimal("0"):
            return NormalizedStrength(
                raw_value=float(val_dec),
                raw_unit=raw_unit,
                raw_per=raw_per,
                is_valid=False,
                error_reason="Strength value must be strictly positive",
            )
    except (InvalidOperation, ValueError):
        return NormalizedStrength(
            raw_unit=raw_unit,
            raw_per=raw_per,
            is_valid=False,
            error_reason=f"Unparseable strength numeric value: '{raw_value}'",
        )

    # 2. Normalize denominator
    canonical_per = "unit"
    if raw_per:
        per_clean = raw_per.strip().lower()
        if re.search(r"\b5\s*ml\b", per_clean):
            canonical_per = "5ml"
        elif re.search(r"\b(ml|1\s*ml)\b", per_clean):
            canonical_per = "ml"
        elif re.search(r"\b(g|gm|1\s*g)\b", per_clean):
            canonical_per = "g"
        elif re.search(r"\b(tab|tablet|cap|capsule|vial|ampoule|dose|unit)\b", per_clean):
            canonical_per = "unit"
        else:
            canonical_per = per_clean

    # 3. Normalize unit and convert mass if applicable
    unit_clean = raw_unit.strip().lower()
    
    # Check mass units (convert to canonical mg)
    if unit_clean in MASS_TO_MG_MULTIPLIERS:
        multiplier = MASS_TO_MG_MULTIPLIERS[unit_clean]
        canonical_val_dec = (val_dec * multiplier).normalize()
        # Round to 6 decimal places to avoid float drift while preserving microgram precision
        canonical_val = float(round(canonical_val_dec, 6))
        return NormalizedStrength(
            raw_value=float(val_dec),
            raw_unit=raw_unit,
            raw_per=raw_per,
            canonical_value=canonical_val,
            canonical_unit="mg",
            canonical_per=canonical_per,
            is_valid=True,
        )

    # Check non-mass units (e.g. IU, %)
    if unit_clean in NON_MASS_UNITS:
        canonical_unit = NON_MASS_UNITS[unit_clean]
        canonical_val = float(round(val_dec, 4))
        return NormalizedStrength(
            raw_value=float(val_dec),
            raw_unit=raw_unit,
            raw_per=raw_per,
            canonical_value=canonical_val,
            canonical_unit=canonical_unit,
            canonical_per=canonical_per,
            is_valid=True,
        )

    # Unrecognized or unsupported unit
    return NormalizedStrength(
        raw_value=float(val_dec),
        raw_unit=raw_unit,
        raw_per=raw_per,
        is_valid=False,
        error_reason=f"Unsupported or ambiguous strength unit: '{raw_unit}'",
    )


def normalize_salt_name(raw_name: str) -> Tuple[str, Optional[str], bool]:
    """Extracts canonical moiety and salt modifier from raw text.
    
    Returns:
        (canonical_moiety, salt_modifier, is_ambiguous)
    """
    if not raw_name or not raw_name.strip():
        return ("", None, True)

    text = raw_name.strip().lower()

    # Remove standard pharmacopoeia marks: IP, BP, USP
    text = re.sub(r"\b(ip|bp|usp)\b", "", text)
    
    # Remove dosage and release profile tokens if erroneously mixed into salt name string
    text = re.sub(r"\b(tablet|tablets|capsule|capsules|syrup|injection|gel|cream|drops|inhaler)\b", "", text)
    text = re.sub(
        r"\b(gastro[\s\-]resistant|enteric[\s\-]coated|prolonged[\s\-]release|sustained[\s\-]release|"
        r"extended[\s\-]release|modified[\s\-]release|mouth[\s\-]dissolving|chewable|dispersible|"
        r"delayed[\s\-]release|immediate[\s\-]release|sr|er|dr|ec|mr|pr|cr|dt|md|odt|ir)\b",
        "",
        text,
    )

    # Remove extraneous symbols
    text = re.sub(r"[^\w\s\-/]", " ", text)
    tokens = [t for t in text.split() if t]

    if not tokens:
        return ("", None, True)

    # Identify salt modifiers
    detected_modifier: Optional[str] = None
    moiety_tokens: List[str] = []

    for token in tokens:
        if token in SALT_MODIFIERS:
            detected_modifier = SALT_MODIFIERS[token]
        else:
            moiety_tokens.append(token)

    if not moiety_tokens:
        # Only salt modifier present without active chemical moiety
        return ("", detected_modifier, True)

    raw_moiety = " ".join(moiety_tokens)
    canonical_moiety = MOIETY_SPELLING_MAP.get(raw_moiety, raw_moiety)

    return (canonical_moiety, detected_modifier, False)


def normalize_dosage_form(raw_text: Optional[str]) -> DosageForm:
    """Deterministically maps text to controlled DosageForm enum.
    
    Never guesses; returns DosageForm.UNKNOWN if unrecognized.
    """
    if not raw_text:
        return DosageForm.UNKNOWN

    text = raw_text.strip().lower()

    if re.search(r"\b(tab|tabs|tablet|tablets)\b", text):
        return DosageForm.TABLET
    if re.search(r"\b(cap|caps|capsule|capsules|softgel)\b", text):
        return DosageForm.CAPSULE
    if re.search(r"\b(syr|syrup)\b", text):
        return DosageForm.SYRUP
    if re.search(r"\b(susp|suspension)\b", text):
        return DosageForm.SUSPENSION
    if re.search(r"\b(inj|injection|infusion)\b", text):
        return DosageForm.INJECTION
    if re.search(r"\b(gel)\b", text):
        return DosageForm.GEL
    if re.search(r"\b(cream|ointment|oint)\b", text):
        return DosageForm.CREAM
    if re.search(r"\b(drop|drops|eye drop|eye drops|ear drops)\b", text):
        return DosageForm.DROPS
    if re.search(r"\b(inhaler|rotacap|respule)\b", text):
        return DosageForm.INHALER

    return DosageForm.UNKNOWN


def normalize_release_type(raw_text: Optional[str]) -> ReleaseType:
    """Deterministically identifies controlled release profile.
    
    Distinguishes IR, SR, ER, XR, DR/EC, MR, ODT, chewable, dispersible.
    Unknown or unspecified values remain ReleaseType.UNKNOWN.
    """
    if not raw_text:
        return ReleaseType.UNKNOWN

    text = raw_text.strip().lower()

    # Explicit sustained release
    if re.search(r"\b(sr|sustained\s+release|slow\s+release)\b", text):
        return ReleaseType.SR

    # Extended release
    if re.search(r"\b(er|extended\s+release|xl)\b", text):
        return ReleaseType.ER

    # XR
    if re.search(r"\b(xr)\b", text):
        return ReleaseType.XR

    # Delayed release / enteric coated / gastro-resistant
    if re.search(r"\b(dr|delayed\s+release|ec|enteric\s+coated|gastro[\s\-]resistant)\b", text):
        return ReleaseType.DR_EC

    # Modified / prolonged / controlled release
    if re.search(r"\b(mr|modified\s+release|pr|prolonged\s+release|cr|controlled\s+release)\b", text):
        return ReleaseType.MR

    # Orally disintegrating / mouth dissolving
    if re.search(r"\b(odt|mouth\s+dissolving|md)\b", text):
        return ReleaseType.ODT

    # Chewable
    if re.search(r"\b(chewable)\b", text):
        return ReleaseType.CHEWABLE

    # Dispersible
    if re.search(r"\b(dispersible|dt)\b", text):
        return ReleaseType.DISPERSIBLE

    # Immediate release
    if re.search(r"\b(ir|immediate\s+release|uncoated|film[\s\-]coated)\b", text):
        return ReleaseType.IR

    return ReleaseType.UNKNOWN


def normalize_route(
    raw_text: Optional[str],
    form: Optional[DosageForm] = None,
) -> AdministrationRoute:
    """Deterministically resolves route of administration."""
    if raw_text:
        text = raw_text.strip().lower()
        if re.search(r"\b(oral|mouth|swallow|po)\b", text):
            return AdministrationRoute.ORAL
        if re.search(r"\b(topical|skin|external)\b", text):
            return AdministrationRoute.TOPICAL
        if re.search(r"\b(ophthalmic|eye|ocular)\b", text):
            return AdministrationRoute.OPHTHALMIC
        if re.search(r"\b(parenteral|iv|im|sc|subcutaneous|intravenous|intramuscular)\b", text):
            return AdministrationRoute.PARENTERAL
        if re.search(r"\b(nasal|nose)\b", text):
            return AdministrationRoute.NASAL
        if re.search(r"\b(inhalation|inhaler)\b", text):
            return AdministrationRoute.INHALATION

    # If route text absent, infer from dosage form if unambiguous
    if form:
        if form in (DosageForm.TABLET, DosageForm.CAPSULE, DosageForm.SYRUP, DosageForm.SUSPENSION):
            return AdministrationRoute.ORAL
        if form in (DosageForm.GEL, DosageForm.CREAM):
            return AdministrationRoute.TOPICAL
        if form == DosageForm.INJECTION:
            return AdministrationRoute.PARENTERAL
        if form == DosageForm.INHALER:
            return AdministrationRoute.INHALATION

    return AdministrationRoute.UNKNOWN


def extract_release_marker_from_text(text: Optional[str]) -> Optional[str]:
    """Extracts explicit release marker token if present in packaging string."""
    if not text:
        return None
    match = re.search(
        r"\b(gastro[\s\-]resistant|enteric[\s\-]coated|prolonged[\s\-]release|sustained[\s\-]release|"
        r"extended[\s\-]release|modified[\s\-]release|mouth[\s\-]dissolving|chewable|dispersible|"
        r"delayed[\s\-]release|immediate[\s\-]release|sr|er|dr|ec|mr|pr|cr|dt|md|odt|ir)\b",
        text,
        re.IGNORECASE,
    )
    return match.group(1).upper() if match else None


def normalize_composition_items(
    items: List[PrintedCompositionItem],
) -> NormalizedComposition:
    """Normalizes an explicit list of PrintedCompositionItem objects.
    
    Treats combination medicines as order-independent by sorting ingredients
    by canonical_moiety ONLY after each item is parsed unambiguously.
    """
    if not items:
        return NormalizedComposition(is_ambiguous=True)

    normalized_ingredients: List[NormalizedIngredient] = []
    has_ambiguity = False

    for item in items:
        moiety, modifier, name_ambiguous = normalize_salt_name(item.salt_text)
        strength = normalize_strength(item.strength_value, item.strength_unit, item.per)
        rel_marker = extract_release_marker_from_text(item.salt_text)

        is_item_ambiguous = name_ambiguous or (not strength.is_valid)
        if is_item_ambiguous:
            has_ambiguity = True

        normalized_ingredients.append(
            NormalizedIngredient(
                raw_name=item.salt_text,
                canonical_moiety=moiety,
                salt_modifier=modifier,
                strength=strength,
                detected_release_marker=rel_marker,
                is_ambiguous=is_item_ambiguous,
            )
        )

    # Sort order-independently by canonical_moiety
    normalized_ingredients.sort(key=lambda x: (x.canonical_moiety, x.salt_modifier or ""))

    return NormalizedComposition(
        ingredients=normalized_ingredients,
        is_combination=len(normalized_ingredients) > 1,
        is_ambiguous=has_ambiguity,
    )


def parse_composition_string(composition_str: str) -> NormalizedComposition:
    """Parses raw compound string into a NormalizedComposition.
    
    Examples handled:
    - 'Amoxycillin (500mg) , Clavulanic Acid (125mg)'
    - 'Aceclofenac 100mg and Paracetamol 325mg Tablets'
    - 'Metformin Hydrochloride IP 500 mg'
    """
    if not composition_str or not composition_str.strip():
        return NormalizedComposition(is_ambiguous=True, raw_text=composition_str)

    raw_text = composition_str.strip()
    
    # Strip dosage form suffixes like 'Tablets', 'Capsules' from the end of the text
    cleaned_text = re.sub(r"\b(tablets?|capsules?|syrup|suspension|injection)\b\s*$", "", raw_text, flags=re.IGNORECASE).strip()

    # Regex pattern to match an ingredient name and its associated strength
    # Example: "Amoxycillin (500mg)" or "Aceclofenac 100mg" or "Paracetamol 325 mg/5ml"
    # Matches: [Name] [Value] [Unit] [/Denominator optional]
    pattern = re.compile(
        r"([a-zA-Z\s\-]+?)\s*\(?\s*(\d+(?:\.\d+)?)\s*([a-zA-Z%]+)(?:\s*/\s*([a-zA-Z0-9]+))?\s*\)?",
        re.IGNORECASE,
    )

    matches = list(pattern.finditer(cleaned_text))

    if not matches:
        # Fallback: single salt with no strength regex match
        moiety, modifier, is_ambiguous = normalize_salt_name(cleaned_text)
        return NormalizedComposition(
            ingredients=[
                NormalizedIngredient(
                    raw_name=cleaned_text,
                    canonical_moiety=moiety,
                    salt_modifier=modifier,
                    strength=NormalizedStrength(is_valid=False, error_reason="No strength detected"),
                    is_ambiguous=True,
                )
            ],
            is_combination=False,
            is_ambiguous=True,
            raw_text=raw_text,
        )

    ingredients: List[NormalizedIngredient] = []
    has_ambiguity = False

    for m in matches:
        raw_name = m.group(1).strip()
        # Clean connecting words like 'and', '+' from salt name
        raw_name = re.sub(r"^(and|\+|\&)\s*", "", raw_name, flags=re.IGNORECASE).strip()

        val_str = m.group(2)
        unit_str = m.group(3)
        per_str = m.group(4)

        moiety, modifier, name_ambiguous = normalize_salt_name(raw_name)
        strength = normalize_strength(val_str, unit_str, per_str)

        is_item_ambiguous = name_ambiguous or (not strength.is_valid)
        if is_item_ambiguous:
            has_ambiguity = True

        rel_marker = extract_release_marker_from_text(raw_name)

        ingredients.append(
            NormalizedIngredient(
                raw_name=raw_name,
                canonical_moiety=moiety,
                salt_modifier=modifier,
                strength=strength,
                detected_release_marker=rel_marker,
                is_ambiguous=is_item_ambiguous,
            )
        )

    # Sort order-independently by canonical moiety
    ingredients.sort(key=lambda x: (x.canonical_moiety, x.salt_modifier or ""))

    return NormalizedComposition(
        ingredients=ingredients,
        is_combination=len(ingredients) > 1,
        is_ambiguous=has_ambiguity,
        raw_text=raw_text,
    )


# ============================================================================
# Equivalence Comparison Helpers
# ============================================================================

def are_strengths_equivalent(s1: NormalizedStrength, s2: NormalizedStrength) -> bool:
    """Evaluates whether two normalized strengths are strictly identical.
    
    Invariants:
    1. Both strengths must be valid (is_valid=True).
    2. Canonical values must be equal (within precision tolerance).
    3. Canonical units must match.
    4. Denominators (canonical_per) must match identically.
    """
    if not s1.is_valid or not s2.is_valid:
        return False

    if s1.canonical_unit != s2.canonical_unit:
        return False

    if s1.canonical_per != s2.canonical_per:
        return False

    if s1.canonical_value is None or s2.canonical_value is None:
        return False

    return abs(s1.canonical_value - s2.canonical_value) < 1e-5


def are_compositions_equivalent(
    c1: NormalizedComposition,
    c2: NormalizedComposition,
) -> bool:
    """Evaluates whether two compositions have identical active ingredients and strengths.
    
    Invariants:
    1. Neither composition can be ambiguous.
    2. Ingredient counts must be equal.
    3. Every ingredient in c1 must match an ingredient in c2 on canonical_moiety and strength.
    """
    if c1.is_ambiguous or c2.is_ambiguous:
        return False

    if len(c1.ingredients) != len(c2.ingredients):
        return False

    # Since ingredients are deterministically sorted by canonical_moiety:
    for i1, i2 in zip(c1.ingredients, c2.ingredients):
        if i1.canonical_moiety != i2.canonical_moiety:
            return False
        if not are_strengths_equivalent(i1.strength, i2.strength):
            return False

    return True
