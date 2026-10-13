"""Reproducible ETL pipeline for Jan Aushadhi and commercial medicine catalogues.

Invariants:
1. Source CSV files are NEVER modified.
2. Full provenance audit trail attached to every ingested record.
3. Ingestion is idempotent: can be rerun deterministically.
4. Ambiguous salt compositions, unparseable units, or non-positive prices are quarantined.
5. Quarantined or unverified records are flagged and prohibited from EXACT matching.
"""

from datetime import datetime, timezone
import hashlib
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
from sqlalchemy.orm import Session

from ml.data.database import DEFAULT_DB_URL, get_db_session, init_db
from ml.data.models import ProductRecord, ProductSaltRecord, QuarantinedRecord
from ml.resolver.normalize import (
    normalize_dosage_form,
    normalize_release_type,
    normalize_route,
    parse_composition_string,
)
from ml.schemas.enums import DosageForm, ReleaseType


def compute_sha256(filepath: str) -> str:
    """Calculates SHA-256 hash of a file for immutable provenance recording."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def parse_unit_size(raw_unit_size: Optional[str]) -> Tuple[Optional[float], Optional[str], bool]:
    """Parses Jan Aushadhi Unit Size strings into numerical pack count and unit.
    
    Examples:
    - "10's", "15's", "30's", "1's" -> (10.0, "tablets", True)
    - "100 ml", "5ml Drops", "2 ml" -> (100.0, "ml", True)
    - "Vial & Wfi", "Vial" -> (1.0, "vial", True)
    - "One in Mono-Pack" -> (1.0, "unit", True)
    """
    if not raw_unit_size or not str(raw_unit_size).strip():
        return (None, None, False)

    text = str(raw_unit_size).strip()

    # Pattern 1: e.g. "10's", "15's", "1's", "10s", "30's Bottle", "1's mono-carton", "60's in Bottle"
    m_count = re.search(r"^(\d+)\s*(?:'s|s)(?:\s+(?:in\s+)?(?:bottle|mono[\s\-]carton|tin))?$", text, re.IGNORECASE)
    if m_count:
        return (float(m_count.group(1)), "tablets", True)

    # Pattern 2: e.g. "100 ml", "5ml Drops", "10 ml", "100 ml Bottle", "2ml Ampoule", "1ml Ampoule"
    m_ml = re.search(r"^(\d+(?:\.\d+)?)\s*ml(?:\s+(?:drops|bottles?|ampoules?))?$", text, re.IGNORECASE)
    if m_ml:
        return (float(m_ml.group(1)), "ml", True)

    # Pattern 3: e.g. "15 g", "20 gm", "15 g tubes", "15g tube"
    m_g = re.search(r"^(\d+(?:\.\d+)?)\s*(?:g|gm|gms)(?:\s+tubes?)?$", text, re.IGNORECASE)
    if m_g:
        return (float(m_g.group(1)), "g", True)

    # Pattern 4: Vials
    if re.search(r"\bvial\b", text, re.IGNORECASE):
        return (1.0, "vial", True)

    # Pattern 5: Mono-pack / single unit
    if re.search(r"\bmono[\s\-]pack\b", text, re.IGNORECASE):
        return (1.0, "unit", True)

    return (None, None, False)


def parse_im_pack_size(pack_label: Optional[str]) -> Tuple[Optional[float], Optional[str], bool]:
    """Parses Indian Medicine Dataset pack size label.
    
    Examples:
    - "strip of 10 tablets" -> (10.0, "tablets", True)
    - "bottle of 100 ml Syrup" -> (100.0, "ml", True)
    - "strip of 15 tablets" -> (15.0, "tablets", True)
    - "vial of 1 ml Injection" -> (1.0, "ml", True)
    - "tube of 15 gm Gel" -> (15.0, "g", True)
    - "box of 1 pack" -> (1.0, "pack", True)
    """
    if not pack_label or not str(pack_label).strip():
        return (None, None, False)

    text = str(pack_label).strip()

    # Look for number followed by unit
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(tablets?|capsules?|ml|gm?|vials?|ampoules?|s|pack|units?)\b",
        text,
        re.IGNORECASE,
    )
    if match:
        val = float(match.group(1))
        unit = match.group(2).lower()
        if unit in ("tablets", "tablet", "capsules", "capsule", "s"):
            norm_unit = "tablets"
        elif unit in ("g", "gm"):
            norm_unit = "g"
        elif unit == "ml":
            norm_unit = "ml"
        elif unit in ("vials", "vial"):
            norm_unit = "vial"
        else:
            norm_unit = "unit"
        return (val, norm_unit, True)

    return (None, None, False)


class CatalogueETL:
    """ETL coordinator for populating and auditing the local medicine catalogue."""

    def __init__(self, db_url: str = DEFAULT_DB_URL):
        self.db_url = db_url
        self.engine = init_db(db_url)

    def clear_database(self, session: Session) -> None:
        """Clears existing catalogue tables for idempotent re-ingestion."""
        session.query(ProductSaltRecord).delete()
        session.query(ProductRecord).delete()
        session.query(QuarantinedRecord).delete()
        session.commit()

    def ingest_jan_aushadhi(
        self,
        csv_path: str,
        limit: Optional[int] = None,
        session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Ingests official PMBJP Jan Aushadhi product catalogue into SQLite.
        
        Source Metadata:
        - Source: PMBI Official Product List
        - Retrieval / File Date: 2026-10-08
        - Verified Price: True (Fixed Government MRP)
        """
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Jan Aushadhi CSV not found at: {csv_path}")

        sha256 = compute_sha256(csv_path)
        ingested_at = datetime.now(timezone.utc).isoformat()
        price_date = "2026-10-08"

        close_session = False
        if session is None:
            session = get_db_session(self.db_url)
            close_session = True

        df = pd.read_csv(csv_path)
        if limit:
            df = df.head(limit)

        total_rows = len(df)
        accepted_count = 0
        quarantined_count = 0
        quarantine_reasons: Dict[str, int] = {}

        try:
            for idx, row in df.iterrows():
                drug_code = str(row["Drug Code"]).strip()
                raw_name = str(row["Generic Name"]).strip()
                raw_unit_size = str(row["Unit Size"]).strip()
                mrp_val = row["MRP"]

                # 1. Validate MRP
                try:
                    mrp = float(mrp_val)
                    if mrp <= 0.0:
                        raise ValueError("Non-positive MRP")
                except (ValueError, TypeError):
                    quarantined_count += 1
                    reason = f"Invalid MRP: '{mrp_val}'"
                    quarantine_reasons[reason] = quarantine_reasons.get(reason, 0) + 1
                    session.add(
                        QuarantinedRecord(
                            source_name="PMBI_JAN_AUSHADHI",
                            source_row_id=drug_code,
                            raw_text=raw_name,
                            quarantine_reason=reason,
                            ingested_at=ingested_at,
                        )
                    )
                    continue

                # 2. Parse pack size
                pack_count, pack_unit, pack_ok = parse_unit_size(raw_unit_size)
                if not pack_ok or pack_count is None or pack_count <= 0:
                    quarantined_count += 1
                    reason = f"Unparseable unit size: '{raw_unit_size}'"
                    quarantine_reasons[reason] = quarantine_reasons.get(reason, 0) + 1
                    session.add(
                        QuarantinedRecord(
                            source_name="PMBI_JAN_AUSHADHI",
                            source_row_id=drug_code,
                            raw_text=raw_name,
                            quarantine_reason=reason,
                            ingested_at=ingested_at,
                        )
                    )
                    continue

                # 3. Parse composition using Phase 1B
                comp = parse_composition_string(raw_name)
                if comp.is_ambiguous or not comp.ingredients:
                    quarantined_count += 1
                    reason = f"Ambiguous composition: '{raw_name}'"
                    quarantine_reasons[reason] = quarantine_reasons.get(reason, 0) + 1
                    session.add(
                        QuarantinedRecord(
                            source_name="PMBI_JAN_AUSHADHI",
                            source_row_id=drug_code,
                            raw_text=raw_name,
                            quarantine_reason=reason,
                            ingested_at=ingested_at,
                        )
                    )
                    continue

                # Check each ingredient strength validity
                has_invalid_strength = False
                for ing in comp.ingredients:
                    if not ing.strength.is_valid:
                        has_invalid_strength = True
                        break
                if has_invalid_strength:
                    quarantined_count += 1
                    reason = f"Invalid strength in composition: '{raw_name}'"
                    quarantine_reasons[reason] = quarantine_reasons.get(reason, 0) + 1
                    session.add(
                        QuarantinedRecord(
                            source_name="PMBI_JAN_AUSHADHI",
                            source_row_id=drug_code,
                            raw_text=raw_name,
                            quarantine_reason=reason,
                            ingested_at=ingested_at,
                        )
                    )
                    continue

                # 4. Normalize dosage form, release type, and route
                form = normalize_dosage_form(raw_name)
                release = normalize_release_type(raw_name)
                route = normalize_route(None, form)

                unit_price = round(mrp / pack_count, 4)
                product_id = f"ja_{drug_code}"

                # Eligibility for exact generic matching:
                # Must be unquarantined, non-discontinued, known form, known release, known route, with active salts
                is_eligible = (
                    form != DosageForm.UNKNOWN
                    and release != ReleaseType.UNKNOWN
                    and route.value != "unknown"
                    and len(comp.ingredients) > 0
                    and unit_price > 0
                )

                product = ProductRecord(
                    id=product_id,
                    kind="generic",
                    name=raw_name,
                    raw_name=raw_name,
                    manufacturer="Jan Aushadhi (PMBI)",
                    dosage_form=form.value,
                    release_type=release.value,
                    route=route.value,
                    pack_count=pack_count,
                    pack_unit=pack_unit,
                    mrp_inr=mrp,
                    unit_price_inr=unit_price,
                    price_date=price_date,
                    price_provenance_notes="PMBI official export filename timestamp: 2026-10-08",
                    is_verified_price=True,  # Verified government MRP
                    is_discontinued=False,
                    is_quarantined=False,
                    is_eligible_for_matching=is_eligible,
                    quarantine_reason=None,
                    source_name="PMBI_JAN_AUSHADHI",
                    source_row_id=drug_code,
                    source_file_sha256=sha256,
                    ingested_at=ingested_at,
                )

                # Add salts
                for ing in comp.ingredients:
                    salt_rec = ProductSaltRecord(
                        salt_name=ing.canonical_moiety,
                        salt_modifier=ing.salt_modifier,
                        strength_value=ing.strength.canonical_value,
                        strength_unit=ing.strength.canonical_unit,
                        per_unit=ing.strength.canonical_per,
                    )
                    product.salts.append(salt_rec)

                session.add(product)
                accepted_count += 1

            session.commit()
        finally:
            if close_session:
                session.close()

        return {
            "source": "PMBI_JAN_AUSHADHI",
            "sha256": sha256,
            "total_rows": total_rows,
            "accepted": accepted_count,
            "quarantined": quarantined_count,
            "quarantine_reasons": quarantine_reasons,
            "price_date": price_date,
            "is_verified_price": True,
        }

    def ingest_indian_medicines(
        self,
        csv_path: str,
        limit: Optional[int] = None,
        session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Ingests commercial medicine candidate reference records into SQLite.
        
        Source Metadata:
        - Source: Indian Medicine Dataset (Open e-pharmacy scrape)
        - Retrieval Date: 2026-10-13
        - Price Status: Unverified scraped prices (is_verified_price=False)
        - Discontinued tracking: Preserved from 'Is_discontinued'
        """
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Indian Medicine CSV not found at: {csv_path}")

        sha256 = compute_sha256(csv_path)
        ingested_at = datetime.now(timezone.utc).isoformat()
        price_date = "unverified"

        close_session = False
        if session is None:
            session = get_db_session(self.db_url)
            close_session = True

        # Read only required columns to optimize memory
        cols = [
            "id",
            "name",
            "price(₹)",
            "Is_discontinued",
            "manufacturer_name",
            "pack_size_label",
            "short_composition1",
            "short_composition2",
        ]
        df = pd.read_csv(csv_path, usecols=cols, nrows=limit)

        total_rows = len(df)
        accepted_count = 0
        quarantined_count = 0
        discontinued_count = 0
        quarantine_reasons: Dict[str, int] = {}

        try:
            for idx, row in df.iterrows():
                row_id = str(row["id"])
                brand_name = str(row["name"]).strip() if pd.notna(row["name"]) else "Unknown Brand"
                manufacturer = str(row["manufacturer_name"]).strip() if pd.notna(row["manufacturer_name"]) else None
                is_discontinued = bool(row["Is_discontinued"]) if pd.notna(row["Is_discontinued"]) else False
                if is_discontinued:
                    discontinued_count += 1

                raw_price = row["price(₹)"]
                pack_label = str(row["pack_size_label"]) if pd.notna(row["pack_size_label"]) else None
                c1 = str(row["short_composition1"]).strip() if pd.notna(row["short_composition1"]) else ""
                c2 = str(row["short_composition2"]).strip() if pd.notna(row["short_composition2"]) else ""

                # 1. Parse price
                try:
                    price = float(raw_price)
                    if price <= 0:
                        raise ValueError("Non-positive price")
                except (ValueError, TypeError):
                    quarantined_count += 1
                    reason = f"Invalid price: '{raw_price}'"
                    quarantine_reasons[reason] = quarantine_reasons.get(reason, 0) + 1
                    session.add(
                        QuarantinedRecord(
                            source_name="INDIAN_MEDICINE_DATASET",
                            source_row_id=row_id,
                            raw_text=brand_name,
                            quarantine_reason=reason,
                            ingested_at=ingested_at,
                        )
                    )
                    continue

                # 2. Parse pack size
                pack_count, pack_unit, pack_ok = parse_im_pack_size(pack_label)
                if not pack_ok or pack_count is None or pack_count <= 0:
                    quarantined_count += 1
                    reason = f"Unparseable pack size: '{pack_label}'"
                    quarantine_reasons[reason] = quarantine_reasons.get(reason, 0) + 1
                    session.add(
                        QuarantinedRecord(
                            source_name="INDIAN_MEDICINE_DATASET",
                            source_row_id=row_id,
                            raw_text=brand_name,
                            quarantine_reason=reason,
                            ingested_at=ingested_at,
                        )
                    )
                    continue

                # 3. Parse composition
                comp_parts = [p for p in [c1, c2] if p]
                if not comp_parts:
                    quarantined_count += 1
                    reason = "Missing composition"
                    quarantine_reasons[reason] = quarantine_reasons.get(reason, 0) + 1
                    session.add(
                        QuarantinedRecord(
                            source_name="INDIAN_MEDICINE_DATASET",
                            source_row_id=row_id,
                            raw_text=brand_name,
                            quarantine_reason=reason,
                            ingested_at=ingested_at,
                        )
                    )
                    continue

                full_comp_str = " + ".join(comp_parts)
                comp = parse_composition_string(full_comp_str)
                if comp.is_ambiguous or not comp.ingredients:
                    quarantined_count += 1
                    reason = f"Ambiguous composition: '{full_comp_str}'"
                    quarantine_reasons[reason] = quarantine_reasons.get(reason, 0) + 1
                    session.add(
                        QuarantinedRecord(
                            source_name="INDIAN_MEDICINE_DATASET",
                            source_row_id=row_id,
                            raw_text=brand_name,
                            quarantine_reason=reason,
                            ingested_at=ingested_at,
                        )
                    )
                    continue

                # Check ingredient validity
                has_invalid_strength = any(not ing.strength.is_valid for ing in comp.ingredients)
                if has_invalid_strength:
                    quarantined_count += 1
                    reason = f"Invalid strength in composition: '{full_comp_str}'"
                    quarantine_reasons[reason] = quarantine_reasons.get(reason, 0) + 1
                    session.add(
                        QuarantinedRecord(
                            source_name="INDIAN_MEDICINE_DATASET",
                            source_row_id=row_id,
                            raw_text=brand_name,
                            quarantine_reason=reason,
                            ingested_at=ingested_at,
                        )
                    )
                    continue

                # 4. Form, release, route
                form = normalize_dosage_form(brand_name)
                release = normalize_release_type(brand_name)
                route = normalize_route(None, form)

                unit_price = round(price / pack_count, 4)
                product_id = f"im_{row_id}"

                product = ProductRecord(
                    id=product_id,
                    kind="brand",
                    name=brand_name,
                    raw_name=brand_name,
                    manufacturer=manufacturer,
                    dosage_form=form.value,
                    release_type=release.value,
                    route=route.value,
                    pack_count=pack_count,
                    pack_unit=pack_unit,
                    mrp_inr=price,
                    unit_price_inr=unit_price,
                    price_date=price_date,
                    price_provenance_notes="Unverified retail web scrape (missing publication date)",
                    is_verified_price=False,  # Unverified commercial scrape
                    is_discontinued=is_discontinued,
                    is_quarantined=False,
                    is_eligible_for_matching=False,  # Commercial brands cannot serve as generic match targets
                    quarantine_reason=None,
                    source_name="INDIAN_MEDICINE_DATASET",
                    source_row_id=row_id,
                    source_file_sha256=sha256,
                    ingested_at=ingested_at,
                )

                for ing in comp.ingredients:
                    salt_rec = ProductSaltRecord(
                        salt_name=ing.canonical_moiety,
                        salt_modifier=ing.salt_modifier,
                        strength_value=ing.strength.canonical_value,
                        strength_unit=ing.strength.canonical_unit,
                        per_unit=ing.strength.canonical_per,
                    )
                    product.salts.append(salt_rec)

                session.add(product)
                accepted_count += 1

            session.commit()
        finally:
            if close_session:
                session.close()

        return {
            "source": "INDIAN_MEDICINE_DATASET",
            "sha256": sha256,
            "total_rows": total_rows,
            "accepted": accepted_count,
            "quarantined": quarantined_count,
            "discontinued": discontinued_count,
            "quarantine_reasons": quarantine_reasons,
            "price_date": price_date,
            "is_verified_price": False,
        }

    def run_full_etl(
        self,
        ja_csv: str = "data/raw/jan_aushadhi_products.csv",
        im_csv: str = "data/raw/indian_medicine_data.csv",
        ja_limit: Optional[int] = None,
        im_limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Runs reproducible ETL pipeline across both raw datasets."""
        session = get_db_session(self.db_url)
        try:
            self.clear_database(session)
            ja_stats = self.ingest_jan_aushadhi(ja_csv, limit=ja_limit, session=session)
            im_stats = self.ingest_indian_medicines(im_csv, limit=im_limit, session=session)
            return {"jan_aushadhi": ja_stats, "indian_medicines": im_stats}
        finally:
            session.close()


def run_catalogue_etl(
    db_url: str = DEFAULT_DB_URL,
    ja_csv: str = "data/raw/jan_aushadhi_products.csv",
    im_csv: str = "data/raw/indian_medicine_data.csv",
    ja_limit: Optional[int] = None,
    im_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Functional convenience wrapper for CatalogueETL.run_full_etl."""
    etl = CatalogueETL(db_url)
    return etl.run_full_etl(ja_csv, im_csv, ja_limit, im_limit)
