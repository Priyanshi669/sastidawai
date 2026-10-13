import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import date

from .config import CATALOGUE_CSV, DATABASE_PATH


@contextmanager
def connect():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS data_sources (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL,
            retrieved_at TEXT, imported_at TEXT NOT NULL, row_count INTEGER NOT NULL,
            sha256 TEXT NOT NULL, licence_notes TEXT NOT NULL, etl_version TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY, brand_name TEXT NOT NULL, manufacturer TEXT,
            dosage_form TEXT, release_type TEXT, route TEXT, pack_size REAL, pack_unit TEXT, price_inr REAL,
            price_date TEXT, discontinued INTEGER NOT NULL DEFAULT 0,
            ingredients_json TEXT NOT NULL, raw_composition TEXT,
            source_id INTEGER NOT NULL REFERENCES data_sources(id)
        );
        CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand_name COLLATE NOCASE);
        CREATE TABLE IF NOT EXISTS scans (
            id TEXT PRIMARY KEY, status TEXT NOT NULL, tier TEXT, latency_ms INTEGER NOT NULL,
            extractor_version TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT, scan_id TEXT NOT NULL,
            field_name TEXT NOT NULL, corrected_value TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL
        );
        """)


def seed_catalogue() -> None:
    if not CATALOGUE_CSV.exists():
        return
    import ast
    import csv

    content = CATALOGUE_CSV.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    with connect() as db:
        found = db.execute("SELECT id FROM data_sources WHERE sha256 = ?", (digest,)).fetchone()
        if found:
            return
        rows = list(csv.DictReader(content.decode("utf-8-sig").splitlines()))
        cursor = db.execute("""INSERT INTO data_sources
            (name,path,retrieved_at,imported_at,row_count,sha256,licence_notes,etl_version)
            VALUES (?,?,NULL,?,?,?,?,?)""", (
            CATALOGUE_CSV.name, str(CATALOGUE_CSV), date.today().isoformat(), len(rows), digest,
            "Local repository CSV; source licence and price retrieval date were not supplied. Prices are undated.",
            "catalogue-import-1",
        ))
        source_id = cursor.lastrowid
        for row in rows:
            try:
                ingredients = ast.literal_eval(row.get("active_ingredients") or "[]")
                if not isinstance(ingredients, list):
                    ingredients = []
            except (ValueError, SyntaxError):
                ingredients = []
            normalized_ingredients = []
            for ingredient in ingredients:
                if isinstance(ingredient, dict) and ingredient.get("name"):
                    normalized_ingredients.append({
                        "name": str(ingredient.get("name", "")).strip(),
                        "strength": str(ingredient.get("strength", "")).strip(),
                        "full_description": str(ingredient.get("full_description", "")).strip(),
                    })
            price = _float(row.get("price_inr"))
            pack_size = _float(row.get("pack_size"))
            db.execute("""INSERT OR IGNORE INTO products
                (id,brand_name,manufacturer,dosage_form,release_type,route,pack_size,pack_unit,price_inr,
                 price_date,discontinued,ingredients_json,raw_composition,source_id)
                 VALUES (?,?,?,?,?,?,?,?,?,NULL,?,?,?,?)""", (
                str(row.get("product_id", "")).strip(), str(row.get("brand_name", "")).strip(),
                row.get("manufacturer") or None, row.get("dosage_form") or None, None, None,
                pack_size, row.get("pack_unit") or None, price,
                int(str(row.get("is_discontinued", "false")).lower() in {"true", "1", "yes"}),
                json.dumps(normalized_ingredients, ensure_ascii=False),
                row.get("packaging_raw") or None, source_id,
            ))


def _float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
