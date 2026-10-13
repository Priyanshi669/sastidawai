"""Synthetic, clearly-marked isolated medicine fixtures for Phase 1C testing.

WARNING: These records are exclusively for safety boundary tests.
They must NEVER be exported or loaded into the live catalogue database.
"""

from ml.schemas.canonical import (
    ActiveSaltMoiety,
    CanonicalMedicine,
    PriceRecord,
    ProvenanceRecord,
)
from ml.schemas.enums import AdministrationRoute, DosageForm, ReleaseType

SYNTHETIC_PROVENANCE_BRAND = ProvenanceRecord(
    source_name="SYNTHETIC_FIXTURE_BRAND",
    source_row_id="mock_brand_001",
    raw_text="Mock Commercial Strip Label",
    retrieval_date="2026-10-13",
    price_date="2026-10-12",
    checksum_sha256="mock_hash_brand_1234567890",
)

SYNTHETIC_PROVENANCE_GENERIC = ProvenanceRecord(
    source_name="SYNTHETIC_FIXTURE_GENERIC",
    source_row_id="mock_gen_001",
    raw_text="Mock Jan Aushadhi Product List",
    retrieval_date="2026-10-13",
    price_date="2026-10-12",
    checksum_sha256="mock_hash_gen_1234567890",
)


def make_synthetic_medicine(
    product_id: str,
    name: str,
    salts: list[ActiveSaltMoiety],
    dosage_form: DosageForm = DosageForm.TABLET,
    release_type: ReleaseType = ReleaseType.IR,
    route: AdministrationRoute = AdministrationRoute.ORAL,
    mrp: float = 50.0,
    pack_count: float = 10.0,
    price_date: str = "2026-10-12",
    is_quarantined: bool = False,
    quarantine_reason: str = None,
    is_nti: bool = False,
    is_brand: bool = True,
) -> CanonicalMedicine:
    """Factory creating isolated synthetic CanonicalMedicine records."""
    prov = SYNTHETIC_PROVENANCE_BRAND if is_brand else SYNTHETIC_PROVENANCE_GENERIC
    unit_price = round(mrp / pack_count, 4)

    price_rec = PriceRecord(
        pack_mrp_inr=mrp,
        pack_count=pack_count,
        unit_price_inr=unit_price,
        price_date=price_date,
        is_verified_current=True,
        provenance=prov,
    )

    return CanonicalMedicine(
        product_id=product_id,
        name=name,
        brand_name=name if is_brand else None,
        generic_name=name if not is_brand else None,
        manufacturer="Mock Pharma Ltd" if is_brand else "Jan Aushadhi (PMBI)",
        salts=salts,
        dosage_form=dosage_form,
        release_type=release_type,
        route=route,
        price=price_rec,
        is_quarantined=is_quarantined,
        quarantine_reason=quarantine_reason,
        is_nti=is_nti,
        provenance=prov,
    )


# Standard Single Salt: Metformin SR 500mg
SYNTHETIC_BRAND_METFORMIN_SR = make_synthetic_medicine(
    product_id="synth_brand_glycomet_sr_500",
    name="Glycomet SR 500",
    salts=[
        ActiveSaltMoiety(
            salt_name="metformin",
            salt_modifier="hydrochloride",
            strength_value=500.0,
            strength_unit="mg",
            per_unit="unit",
        )
    ],
    dosage_form=DosageForm.TABLET,
    release_type=ReleaseType.SR,
    route=AdministrationRoute.ORAL,
    mrp=40.0,
    pack_count=10.0,
    is_brand=True,
)

SYNTHETIC_GENERIC_METFORMIN_SR = make_synthetic_medicine(
    product_id="synth_gen_metformin_sr_500",
    name="Metformin Prolonged Release Tablets IP 500 mg",
    salts=[
        ActiveSaltMoiety(
            salt_name="metformin",
            salt_modifier="hydrochloride",
            strength_value=500.0,
            strength_unit="mg",
            per_unit="unit",
        )
    ],
    dosage_form=DosageForm.TABLET,
    release_type=ReleaseType.SR,
    route=AdministrationRoute.ORAL,
    mrp=12.50,
    pack_count=10.0,
    is_brand=False,
)

# Release Mismatch: Metformin IR 500mg (Immediate Release)
SYNTHETIC_GENERIC_METFORMIN_IR = make_synthetic_medicine(
    product_id="synth_gen_metformin_ir_500",
    name="Metformin Tablets IP 500 mg",
    salts=[
        ActiveSaltMoiety(
            salt_name="metformin",
            salt_modifier="hydrochloride",
            strength_value=500.0,
            strength_unit="mg",
            per_unit="unit",
        )
    ],
    dosage_form=DosageForm.TABLET,
    release_type=ReleaseType.IR,  # Mismatch vs SR!
    route=AdministrationRoute.ORAL,
    mrp=10.0,
    pack_count=10.0,
    is_brand=False,
)

# Combination Salt: Amoxicillin 500mg + Clavulanic Acid 125mg
SYNTHETIC_BRAND_AUGMENTIN_625 = make_synthetic_medicine(
    product_id="synth_brand_augmentin_625",
    name="Augmentin 625 Duo Tablet",
    salts=[
        ActiveSaltMoiety(
            salt_name="amoxicillin",
            strength_value=500.0,
            strength_unit="mg",
            per_unit="unit",
        ),
        ActiveSaltMoiety(
            salt_name="clavulanic acid",
            strength_value=125.0,
            strength_unit="mg",
            per_unit="unit",
        ),
    ],
    dosage_form=DosageForm.TABLET,
    release_type=ReleaseType.IR,
    route=AdministrationRoute.ORAL,
    mrp=220.0,
    pack_count=10.0,
    is_brand=True,
)

SYNTHETIC_GENERIC_AUGMENTIN_625 = make_synthetic_medicine(
    product_id="synth_gen_amox_clav_625",
    name="Amoxycillin and Potassium Clavulanate Tablets IP 625 mg",
    salts=[
        # Note order reversed to test order independence in matcher
        ActiveSaltMoiety(
            salt_name="clavulanic acid",
            strength_value=125.0,
            strength_unit="mg",
            per_unit="unit",
        ),
        ActiveSaltMoiety(
            salt_name="amoxicillin",
            strength_value=500.0,
            strength_unit="mg",
            per_unit="unit",
        ),
    ],
    dosage_form=DosageForm.TABLET,
    release_type=ReleaseType.IR,
    route=AdministrationRoute.ORAL,
    mrp=65.0,
    pack_count=10.0,
    is_brand=False,
)
