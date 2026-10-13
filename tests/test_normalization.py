"""Table-driven unit tests for Phase 1B: Pure Normalization and Canonical Representations."""

import pytest
from ml.resolver.normalize import (
    NormalizedStrength,
    are_compositions_equivalent,
    are_strengths_equivalent,
    normalize_composition_items,
    normalize_dosage_form,
    normalize_release_type,
    normalize_route,
    normalize_salt_name,
    normalize_strength,
    parse_composition_string,
)
from ml.schemas.enums import AdministrationRoute, DosageForm, ReleaseType
from ml.schemas.extraction import PrintedCompositionItem


class TestUnitEquivalenceAndDecimals:
    """Table-driven tests verifying mass conversion to mg with precision preservation."""

    @pytest.mark.parametrize(
        "val1, unit1, val2, unit2, expected_mg",
        [
            (1.0, "g", 1000.0, "mg", 1000.0),
            (0.5, "g", 500.0, "mg", 500.0),
            (500.0, "mcg", 0.5, "mg", 0.5),
            (1000.0, "mcg", 1.0, "mg", 1.0),
            (250.0, "mcg", 0.25, "mg", 0.25),
            (50.0, "mcg", 0.05, "mg", 0.05),
            (0.05, "mg", 50.0, "mcg", 0.05),
            (100.0, "mgs", 100.0, "milligrams", 100.0),
            (2.5, "gm", 2500.0, "mg", 2500.0),
        ],
    )
    def test_mass_unit_conversions_and_equivalence(self, val1, unit1, val2, unit2, expected_mg):
        s1 = normalize_strength(val1, unit1)
        s2 = normalize_strength(val2, unit2)

        assert s1.is_valid is True
        assert s2.is_valid is True
        assert s1.canonical_value == pytest.approx(expected_mg, rel=1e-5)
        assert s2.canonical_value == pytest.approx(expected_mg, rel=1e-5)
        assert s1.canonical_unit == "mg"
        assert s2.canonical_unit == "mg"
        assert are_strengths_equivalent(s1, s2) is True


class TestDenominatorsAndConcentrations:
    """Tests ensuring denominator and concentration semantics are strictly preserved."""

    def test_solid_unit_vs_liquid_5ml_are_not_equivalent(self):
        s_tablet = normalize_strength(100.0, "mg", raw_per="tablet")
        s_syrup = normalize_strength(100.0, "mg", raw_per="5ml")

        assert s_tablet.canonical_per == "unit"
        assert s_syrup.canonical_per == "5ml"
        # Same 100 mg, but different denominators must NOT be equivalent!
        assert are_strengths_equivalent(s_tablet, s_syrup) is False

    def test_liquid_per_ml_vs_per_5ml_are_not_equivalent(self):
        s_1ml = normalize_strength(20.0, "mg", raw_per="ml")
        s_5ml = normalize_strength(20.0, "mg", raw_per="5ml")

        assert are_strengths_equivalent(s_1ml, s_5ml) is False

    def test_equivalent_solid_denominators(self):
        s_tab = normalize_strength(500.0, "mg", raw_per="tablet")
        s_cap = normalize_strength(500.0, "mg", raw_per="unit")

        assert s_tab.canonical_per == "unit"
        assert s_cap.canonical_per == "unit"
        assert are_strengths_equivalent(s_tab, s_cap) is True


class TestNonMassUnitsAndAmbiguity:
    """Tests for IU, %, unsupported units, and missing values."""

    def test_international_units_preserved(self):
        s_iu = normalize_strength(1000.0, "IU")
        assert s_iu.is_valid is True
        assert s_iu.canonical_unit == "iu"
        assert s_iu.canonical_value == 1000.0

        # Cannot be equivalent to 1000 mg
        s_mg = normalize_strength(1000.0, "mg")
        assert are_strengths_equivalent(s_iu, s_mg) is False

    def test_percentage_concentration_preserved(self):
        s_pct = normalize_strength(2.0, "% w/v")
        assert s_pct.is_valid is True
        assert s_pct.canonical_unit == "% w/v"
        assert s_pct.canonical_value == 2.0

    @pytest.mark.parametrize(
        "val, unit",
        [
            (None, "mg"),
            (500, None),
            (-10, "mg"),
            (0, "mg"),
            ("unreadable", "mg"),
            (500, "drops"),
            (10, "tablets"),
            (5, "puffs"),
        ],
    )
    def test_invalid_and_ambiguous_strengths(self, val, unit):
        s = normalize_strength(val, unit)
        assert s.is_valid is False
        assert s.error_reason is not None


class TestSaltNameNormalization:
    """Tests for salt modifiers, pharmacopoeia marks, and British/Indian spellings."""

    @pytest.mark.parametrize(
        "raw_text, expected_moiety, expected_modifier",
        [
            ("Metformin Hydrochloride IP", "metformin", "hydrochloride"),
            ("Metformin HCL", "metformin", "hydrochloride"),
            ("Telmisartan Potassium BP", "telmisartan", "potassium"),
            ("Amlodipine Besylate USP", "amlodipine", "besylate"),
            ("Atorvastatin Calcium", "atorvastatin", "calcium"),
            ("Amoxycillin", "amoxicillin", None),
            ("Paracetamol", "paracetamol", None),
            ("Acetaminophen", "paracetamol", None),
            ("Frusemide", "furosemide", None),
            ("  GLIMEPIRIDE   ", "glimepiride", None),
            ("Losartan Potassium Tablets", "losartan", "potassium"),
        ],
    )
    def test_salt_name_parsing(self, raw_text, expected_moiety, expected_modifier):
        moiety, modifier, is_ambiguous = normalize_salt_name(raw_text)
        assert is_ambiguous is False
        assert moiety == expected_moiety
        assert modifier == expected_modifier

    def test_empty_or_modifier_only_is_ambiguous(self):
        _, _, amb1 = normalize_salt_name("")
        assert amb1 is True

        _, _, amb2 = normalize_salt_name("   ")
        assert amb2 is True

        _, _, amb3 = normalize_salt_name("Sodium")
        assert amb3 is True


class TestDosageFormNormalization:
    """Tests controlled dosage form mapping."""

    @pytest.mark.parametrize(
        "raw, expected_form",
        [
            ("Film-coated tablet", DosageForm.TABLET),
            ("Tablets IP", DosageForm.TABLET),
            ("Tab", DosageForm.TABLET),
            ("Hard Gelatin Capsule", DosageForm.CAPSULE),
            ("Softgel Caps", DosageForm.CAPSULE),
            ("Pediatric Syrup", DosageForm.SYRUP),
            ("Oral Suspension", DosageForm.SUSPENSION),
            ("Sterile Injection", DosageForm.INJECTION),
            ("Topical Gel", DosageForm.GEL),
            ("Skin Ointment", DosageForm.CREAM),
            ("Ophthalmic Eye Drops", DosageForm.DROPS),
            ("Metered Dose Inhaler", DosageForm.INHALER),
            ("Unknown Formulation X", DosageForm.UNKNOWN),
            (None, DosageForm.UNKNOWN),
        ],
    )
    def test_dosage_form_mapping(self, raw, expected_form):
        assert normalize_dosage_form(raw) == expected_form


class TestReleaseTypeNormalization:
    """Tests release profile distinctions."""

    @pytest.mark.parametrize(
        "raw, expected_release",
        [
            ("Glycomet SR 500", ReleaseType.SR),
            ("Sustained Release Tablets", ReleaseType.SR),
            ("Glipizide XL", ReleaseType.ER),
            ("Extended Release Capsules", ReleaseType.ER),
            ("Pantoprazole Gastro-resistant Tablets IP", ReleaseType.DR_EC),
            ("Enteric Coated", ReleaseType.DR_EC),
            ("Prolonged Release Tablets IP", ReleaseType.MR),
            ("Mouth Dissolving MD", ReleaseType.ODT),
            ("Chewable Tablets", ReleaseType.CHEWABLE),
            ("Dispersible DT", ReleaseType.DISPERSIBLE),
            ("Immediate Release", ReleaseType.IR),
            ("Uncoated Tablet", ReleaseType.IR),
            ("Standard Tablets 500mg", ReleaseType.UNKNOWN),
            (None, ReleaseType.UNKNOWN),
        ],
    )
    def test_release_type_mapping(self, raw, expected_release):
        assert normalize_release_type(raw) == expected_release


class TestRouteNormalization:
    """Tests route resolution with explicit text and dosage form fallback."""

    @pytest.mark.parametrize(
        "raw, form, expected_route",
        [
            ("For Oral Use Only", None, AdministrationRoute.ORAL),
            ("External Application Only", None, AdministrationRoute.TOPICAL),
            ("For Eye Drops", None, AdministrationRoute.OPHTHALMIC),
            ("Intravenous Injection", None, AdministrationRoute.PARENTERAL),
            (None, DosageForm.TABLET, AdministrationRoute.ORAL),
            (None, DosageForm.CREAM, AdministrationRoute.TOPICAL),
            (None, DosageForm.INJECTION, AdministrationRoute.PARENTERAL),
            (None, None, AdministrationRoute.UNKNOWN),
        ],
    )
    def test_route_mapping(self, raw, form, expected_route):
        assert normalize_route(raw, form) == expected_route


class TestCombinationOrderIndependence:
    """Tests order-independent combination normalization and equivalence."""

    def test_two_salt_combination_order_independence(self):
        comp1 = normalize_composition_items(
            [
                PrintedCompositionItem(salt_text="Amoxycillin", strength_value=500.0, strength_unit="mg"),
                PrintedCompositionItem(salt_text="Clavulanic Acid", strength_value=125.0, strength_unit="mg"),
            ]
        )
        comp2 = normalize_composition_items(
            [
                PrintedCompositionItem(salt_text="Clavulanic Acid", strength_value=125.0, strength_unit="mg"),
                PrintedCompositionItem(salt_text="Amoxicillin", strength_value=500.0, strength_unit="mg"),
            ]
        )

        assert comp1.is_ambiguous is False
        assert comp2.is_ambiguous is False
        assert comp1.is_combination is True
        assert comp2.is_combination is True

        # Ingredients sorted alphabetically by canonical moiety
        assert comp1.ingredients[0].canonical_moiety == "amoxicillin"
        assert comp1.ingredients[1].canonical_moiety == "clavulanic acid"
        assert comp2.ingredients[0].canonical_moiety == "amoxicillin"
        assert comp2.ingredients[1].canonical_moiety == "clavulanic acid"

        assert are_compositions_equivalent(comp1, comp2) is True

    def test_strength_mismatch_in_combination_fails_equivalence(self):
        comp1 = normalize_composition_items(
            [
                PrintedCompositionItem(salt_text="Metformin", strength_value=500.0, strength_unit="mg"),
                PrintedCompositionItem(salt_text="Glimepiride", strength_value=2.0, strength_unit="mg"),
            ]
        )
        comp2 = normalize_composition_items(
            [
                PrintedCompositionItem(salt_text="Metformin", strength_value=500.0, strength_unit="mg"),
                PrintedCompositionItem(salt_text="Glimepiride", strength_value=1.0, strength_unit="mg"),  # Different strength!
            ]
        )
        assert are_compositions_equivalent(comp1, comp2) is False

    def test_missing_salt_in_combination_fails_equivalence(self):
        comp_single = normalize_composition_items(
            [PrintedCompositionItem(salt_text="Metformin", strength_value=500.0, strength_unit="mg")]
        )
        comp_combo = normalize_composition_items(
            [
                PrintedCompositionItem(salt_text="Metformin", strength_value=500.0, strength_unit="mg"),
                PrintedCompositionItem(salt_text="Glimepiride", strength_value=2.0, strength_unit="mg"),
            ]
        )
        assert are_compositions_equivalent(comp_single, comp_combo) is False

    def test_parse_composition_string_with_various_separators(self):
        comp_and = parse_composition_string("Aceclofenac 100mg and Paracetamol 325mg Tablets")
        assert comp_and.is_combination is True
        assert len(comp_and.ingredients) == 2
        assert comp_and.ingredients[0].canonical_moiety == "aceclofenac"
        assert comp_and.ingredients[0].strength.canonical_value == 100.0
        assert comp_and.ingredients[1].canonical_moiety == "paracetamol"
        assert comp_and.ingredients[1].strength.canonical_value == 325.0

        comp_parens = parse_composition_string("Amoxycillin (500mg) , Clavulanic Acid (125mg)")
        assert comp_parens.is_combination is True
        assert len(comp_parens.ingredients) == 2
        assert comp_parens.ingredients[0].canonical_moiety == "amoxicillin"
        assert comp_parens.ingredients[1].canonical_moiety == "clavulanic acid"


class TestAmbiguityBlocksEquivalence:
    """Critical safety tests verifying that ambiguous inputs can never support equivalence."""

    def test_ambiguous_item_blocks_composition_equivalence(self):
        comp_valid = normalize_composition_items(
            [PrintedCompositionItem(salt_text="Metformin", strength_value=500.0, strength_unit="mg")]
        )
        comp_unreadable = normalize_composition_items(
            [PrintedCompositionItem(salt_text="Metformin", strength_value=None, strength_unit="mg")]
        )

        assert comp_valid.is_ambiguous is False
        assert comp_unreadable.is_ambiguous is True
        # An ambiguous composition can NEVER be equivalent to anything!
        assert are_compositions_equivalent(comp_valid, comp_unreadable) is False
        assert are_compositions_equivalent(comp_unreadable, comp_unreadable) is False
