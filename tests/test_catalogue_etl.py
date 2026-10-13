"""Unit and integration tests for Phase 1D: Catalogue ETL, Eligibility & Provenance."""

import os
import tempfile
import pytest
import pandas as pd

from ml.data.database import Base, get_db_session, get_engine
from ml.data.etl import (
    CatalogueETL,
    compute_sha256,
    parse_im_pack_size,
    parse_unit_size,
)
from ml.data.models import ProductRecord, ProductSaltRecord, QuarantinedRecord


@pytest.fixture
def temp_db_url():
    """Provides an isolated SQLite database URL for each test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    db_url = f"sqlite:///{db_path}"
    yield db_url
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


class TestEtlUnitParsers:
    """Unit tests for pack size parsing across Jan Aushadhi and commercial formats."""

    @pytest.mark.parametrize(
        "raw, expected_count, expected_unit, expected_ok",
        [
            ("10's", 10.0, "tablets", True),
            ("15's", 15.0, "tablets", True),
            ("1's", 1.0, "tablets", True),
            ("30's", 30.0, "tablets", True),
            ("100 ml", 100.0, "ml", True),
            ("5ml Drops", 5.0, "ml", True),
            ("15 g tubes", 15.0, "g", True),
            ("15 gm", 15.0, "g", True),
            ("Vial & Wfi", 1.0, "vial", True),
            ("One in Mono-Pack", 1.0, "unit", True),
            ("", None, None, False),
            ("invalid format xyz", None, None, False),
        ],
    )
    def test_jan_aushadhi_unit_size_parsing(self, raw, expected_count, expected_unit, expected_ok):
        count, unit, ok = parse_unit_size(raw)
        assert ok == expected_ok
        assert count == expected_count
        assert unit == expected_unit

    @pytest.mark.parametrize(
        "label, expected_count, expected_unit, expected_ok",
        [
            ("strip of 10 tablets", 10.0, "tablets", True),
            ("bottle of 100 ml Syrup", 100.0, "ml", True),
            ("strip of 15 tablets", 15.0, "tablets", True),
            ("vial of 1 ml Injection", 1.0, "ml", True),
            ("tube of 15 gm Gel", 15.0, "g", True),
            ("box of 1 pack", 1.0, "unit", True),
            (None, None, None, False),
            ("unparseable string", None, None, False),
        ],
    )
    def test_indian_medicine_pack_size_parsing(self, label, expected_count, expected_unit, expected_ok):
        count, unit, ok = parse_im_pack_size(label)
        assert ok == expected_ok
        assert count == expected_count
        assert unit == expected_unit


class TestCatalogueETLIntegrity:
    """Tests verifying ETL ingestion, quarantine filters, provenance, and idempotency."""

    def test_synthetic_jan_aushadhi_ingestion_and_provenance(self, temp_db_url):
        # Create a small synthetic Jan Aushadhi CSV
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="", encoding="utf-8") as f:
            f.write('"Sr No","Drug Code","Generic Name","Unit Size","MRP","Group Name"\n')
            f.write('"1","101","Metformin Prolonged Release Tablets IP 500 mg","10\'s","12.50","Diabetic"\n')
            f.write('"2","102","Paracetamol Tablets IP 500 mg","10\'s","5.00","Analgesic"\n')
            f.write('"3","103","Invalid Medicine Name Without Salt","10\'s","10.00","Misc"\n')  # Ambiguous!
            f.write('"4","104","Aspirin 75mg Tablets","Invalid Unit Size","8.00","CVS"\n')  # Bad pack size!
            f.write('"5","105","Atorvastatin 10mg Tablets","10\'s","-1.00","Lipid"\n')  # Negative price!
            csv_path = f.name

        try:
            etl = CatalogueETL(temp_db_url)
            stats = etl.ingest_jan_aushadhi(csv_path)

            assert stats["total_rows"] == 5
            assert stats["accepted"] == 2
            assert stats["quarantined"] == 3
            assert stats["is_verified_price"] is True

            session = get_db_session(temp_db_url)
            try:
                # 1. Verify accepted records
                accepted = session.query(ProductRecord).filter_by(is_quarantined=False).all()
                assert len(accepted) == 2
                metformin = session.query(ProductRecord).filter_by(id="ja_101").first()
                assert metformin is not None
                assert metformin.name == "Metformin Prolonged Release Tablets IP 500 mg"
                assert metformin.pack_count == 10.0
                assert metformin.unit_price_inr == 1.25
                assert metformin.price_date == "2026-10-08"
                assert metformin.is_verified_price is True
                assert metformin.source_name == "PMBI_JAN_AUSHADHI"

                # Check salt preservation
                assert len(metformin.salts) == 1
                assert metformin.salts[0].salt_name == "metformin"
                assert metformin.salts[0].strength_value == 500.0

                # 2. Verify quarantined records
                quarantined = session.query(QuarantinedRecord).all()
                assert len(quarantined) == 3
                reasons = [q.quarantine_reason for q in quarantined]
                assert any("Ambiguous composition" in r for r in reasons)
                assert any("Unparseable unit size" in r for r in reasons)
                assert any("Invalid MRP" in r for r in reasons)
            finally:
                session.close()

        finally:
            if os.path.exists(csv_path):
                os.remove(csv_path)

    def test_synthetic_commercial_medicine_discontinued_and_unverified_prices(self, temp_db_url):
        # Create a synthetic commercial medicines CSV
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="", encoding="utf-8") as f:
            f.write("id,name,price(₹),Is_discontinued,manufacturer_name,type,pack_size_label,short_composition1,short_composition2\n")
            f.write("1,Augmentin 625 Duo Tablet,223.42,FALSE,GSK,allopathy,strip of 10 tablets,Amoxycillin (500mg),Clavulanic Acid (125mg)\n")
            f.write("2,Old Discontinued Brand,50.0,TRUE,Old Pharma,allopathy,strip of 10 tablets,Paracetamol (500mg),\n")
            f.write("3,Zero Price Drug,0.0,FALSE,Pharma X,allopathy,strip of 10 tablets,Metformin (500mg),\n")
            csv_path = f.name

        try:
            etl = CatalogueETL(temp_db_url)
            stats = etl.ingest_indian_medicines(csv_path)

            assert stats["total_rows"] == 3
            assert stats["accepted"] == 2  # Discontinued is accepted into catalogue, but flagged is_discontinued=True!
            assert stats["quarantined"] == 1  # Zero price quarantined!
            assert stats["discontinued"] == 1

            session = get_db_session(temp_db_url)
            try:
                discontinued_item = session.query(ProductRecord).filter_by(id="im_2").first()
                assert discontinued_item is not None
                assert discontinued_item.is_discontinued is True
                assert discontinued_item.is_verified_price is False  # Must NOT be marked as verified!

                augmentin = session.query(ProductRecord).filter_by(id="im_1").first()
                assert augmentin is not None
                assert augmentin.is_discontinued is False
                assert len(augmentin.salts) == 2
                salt_names = {s.salt_name for s in augmentin.salts}
                assert salt_names == {"amoxicillin", "clavulanic acid"}
            finally:
                session.close()

        finally:
            if os.path.exists(csv_path):
                os.remove(csv_path)

    def test_idempotent_reingestion_produces_identical_counts(self, temp_db_url):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="", encoding="utf-8") as f:
            f.write('"Sr No","Drug Code","Generic Name","Unit Size","MRP","Group Name"\n')
            f.write('"1","201","Metformin Tablets IP 500 mg","10\'s","10.00","Diabetic"\n')
            csv_path = f.name

        try:
            etl = CatalogueETL(temp_db_url)
            # Run 1
            session1 = get_db_session(temp_db_url)
            etl.clear_database(session1)
            etl.ingest_jan_aushadhi(csv_path, session=session1)
            count1 = session1.query(ProductRecord).count()
            session1.close()

            # Run 2 (re-ingestion)
            session2 = get_db_session(temp_db_url)
            etl.clear_database(session2)
            etl.ingest_jan_aushadhi(csv_path, session=session2)
            count2 = session2.query(ProductRecord).count()
            session2.close()

            assert count1 == 1
            assert count2 == 1
        finally:
            if os.path.exists(csv_path):
                os.remove(csv_path)

    def test_real_jan_aushadhi_provenance_and_sha256(self):
        """Verifies real Jan Aushadhi CSV file presence and SHA-256 calculation."""
        csv_path = "data/raw/jan_aushadhi_products.csv"
        assert os.path.exists(csv_path)
        sha = compute_sha256(csv_path)
        assert len(sha) == 64
        # SHA matches calculated hash
        assert sha == "4fb1753879b75946372496c8fe8e104f3bc8f55e868dbcb329ac8f4712b66a2f"

    def test_is_eligible_for_matching_safety_rules(self, temp_db_url):
        """Verifies that only clean, unquarantined, non-discontinued generics with known form/release are eligible."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="", encoding="utf-8") as f:
            f.write('"Sr No","Drug Code","Generic Name","Unit Size","MRP","Group Name"\n')
            f.write('"1","301","Metformin Prolonged Release Tablets IP 500 mg","10\'s","12.50","Diabetic"\n')
            f.write('"2","302","Aspirin Tablets IP 100 mg","10\'s","5.00","CVS"\n')  # release is unknown!
            csv_path = f.name

        try:
            etl = CatalogueETL(temp_db_url)
            etl.ingest_jan_aushadhi(csv_path)

            session = get_db_session(temp_db_url)
            try:
                # 301 has known form (tablet) and known release (MR) -> eligible!
                med301 = session.query(ProductRecord).filter_by(id="ja_301").first()
                assert med301.is_eligible_for_matching is True
                assert med301.price_provenance_notes is not None

                # 302 has release_type 'unknown' -> NOT eligible for exact matching!
                med302 = session.query(ProductRecord).filter_by(id="ja_302").first()
                assert med302.is_eligible_for_matching is False
            finally:
                session.close()
        finally:
            if os.path.exists(csv_path):
                os.remove(csv_path)

    def test_release_evidence_preservation_and_no_false_exact(self):
        """Proves that release-marker stripping from moiety cannot erase release evidence or enable false EXACT."""
        from ml.resolver.normalize import parse_composition_string, normalize_release_type
        from ml.safety.matcher import DeterministicMatcher
        from tests.fixtures.synthetic_medicines import SYNTHETIC_BRAND_METFORMIN_SR, SYNTHETIC_GENERIC_METFORMIN_IR

        # 1. Parsing preserves raw text and captures explicit release marker
        comp = parse_composition_string("Metformin Prolonged Release 500mg")
        ing = comp.ingredients[0]
        assert ing.canonical_moiety == "metformin"
        assert ing.raw_name == "Metformin Prolonged Release"
        assert ing.detected_release_marker == "PROLONGED RELEASE"

        # 2. Release type distinguishes SR vs IR
        rel_sr = normalize_release_type("Metformin SR 500")
        rel_ir = normalize_release_type("Metformin IR 500")
        assert rel_sr != rel_ir

        # 3. Matcher comparing SR vs IR returns CLOSE, NEVER EXACT!
        result = DeterministicMatcher.match(
            scanned=SYNTHETIC_BRAND_METFORMIN_SR,
            candidates=[SYNTHETIC_GENERIC_METFORMIN_IR],
        )
        assert result.tier != "exact"
        assert result.tier == "close"
        assert result.matched_alternatives[0].savings is None

    def test_discontinued_and_unverified_candidates_fail_closed(self):
        """Proves that discontinued products or unverified prices cannot produce false EXACT or savings."""
        from ml.safety.matcher import DeterministicMatcher, evaluate_single_pair
        from tests.fixtures.synthetic_medicines import SYNTHETIC_BRAND_METFORMIN_SR, make_synthetic_medicine

        # Candidate marked discontinued
        discontinued_cand = make_synthetic_medicine(
            product_id="disc_cand",
            name="Discontinued Metformin SR",
            salts=SYNTHETIC_BRAND_METFORMIN_SR.salts,
            dosage_form=SYNTHETIC_BRAND_METFORMIN_SR.dosage_form,
            release_type=SYNTHETIC_BRAND_METFORMIN_SR.release_type,
            route=SYNTHETIC_BRAND_METFORMIN_SR.route,
            is_brand=False,
        )
        discontinued_cand.is_discontinued = True

        tier, reason = evaluate_single_pair(SYNTHETIC_BRAND_METFORMIN_SR, discontinued_cand)
        assert tier == "none"
        assert "discontinued" in reason.lower()

        # Candidate with unverified price
        unverified_cand = make_synthetic_medicine(
            product_id="unver_cand",
            name="Unverified Metformin SR",
            salts=SYNTHETIC_BRAND_METFORMIN_SR.salts,
            dosage_form=SYNTHETIC_BRAND_METFORMIN_SR.dosage_form,
            release_type=SYNTHETIC_BRAND_METFORMIN_SR.release_type,
            route=SYNTHETIC_BRAND_METFORMIN_SR.route,
            is_brand=False,
        )
        unverified_cand.price.is_verified_current = False

        res = DeterministicMatcher.match(SYNTHETIC_BRAND_METFORMIN_SR, [unverified_cand])
        assert res.tier == "exact"  # Clinically equivalent
        # BUT savings MUST be suppressed due to unverified price!
        assert res.matched_alternatives[0].savings is None
        assert any("generic price is not verified" in w.lower() for w in res.warnings)
