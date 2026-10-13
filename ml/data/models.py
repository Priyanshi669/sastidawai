"""SQLAlchemy relational models for medicine catalogue, provenance, and quarantine."""

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ml.data.database import Base


class ProductRecord(Base):
    """Normalized catalogue product record with provenance audit fields."""
    __tablename__ = "products"

    id = Column(String(64), primary_key=True, index=True)
    kind = Column(String(16), nullable=False, index=True)  # 'generic' or 'brand'
    name = Column(String(255), nullable=False, index=True)
    raw_name = Column(Text, nullable=False)
    manufacturer = Column(String(255), nullable=True)

    dosage_form = Column(String(32), nullable=False, index=True)
    release_type = Column(String(32), nullable=False, index=True)
    route = Column(String(32), nullable=False)

    pack_count = Column(Float, nullable=False)
    pack_unit = Column(String(32), nullable=False)
    mrp_inr = Column(Float, nullable=False)
    unit_price_inr = Column(Float, nullable=False)

    price_date = Column(String(32), nullable=False)
    price_provenance_notes = Column(String(128), nullable=True)
    is_verified_price = Column(Boolean, default=False, nullable=False)
    is_discontinued = Column(Boolean, default=False, nullable=False)
    is_quarantined = Column(Boolean, default=False, nullable=False, index=True)
    is_eligible_for_matching = Column(Boolean, default=False, nullable=False, index=True)
    quarantine_reason = Column(Text, nullable=True)

    # Provenance tracking
    source_name = Column(String(64), nullable=False)
    source_row_id = Column(String(64), nullable=False)
    source_file_sha256 = Column(String(64), nullable=False)
    ingested_at = Column(String(32), nullable=False)

    salts = relationship("ProductSaltRecord", back_populates="product", cascade="all, delete-orphan")


class ProductSaltRecord(Base):
    """Active salt ingredient associated with a product."""
    __tablename__ = "product_salts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(String(64), ForeignKey("products.id"), nullable=False, index=True)

    salt_name = Column(String(128), nullable=False, index=True)  # canonical moiety
    salt_modifier = Column(String(64), nullable=True)
    strength_value = Column(Float, nullable=False)
    strength_unit = Column(String(32), nullable=False)
    per_unit = Column(String(32), nullable=False)

    product = relationship("ProductRecord", back_populates="salts")


class QuarantinedRecord(Base):
    """Audit log of records rejected or quarantined during ETL."""
    __tablename__ = "quarantined_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_name = Column(String(64), nullable=False)
    source_row_id = Column(String(64), nullable=False)
    raw_text = Column(Text, nullable=False)
    quarantine_reason = Column(Text, nullable=False)
    ingested_at = Column(String(32), nullable=False)
