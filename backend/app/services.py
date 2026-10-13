import json
import re
from difflib import SequenceMatcher

from .db import connect


def product_payload(row):
    return {
        "product_id": row["id"], "brand_name": row["brand_name"],
        "manufacturer": row["manufacturer"], "dosage_form": row["dosage_form"],
        "release_type": row["release_type"], "route": row["route"],
        "pack_size": row["pack_size"], "pack_unit": row["pack_unit"],
        "price_inr": row["price_inr"], "price_date": row["price_date"],
        "price_status": "undated" if row["price_inr"] is not None and not row["price_date"] else "dated",
        "discontinued": bool(row["discontinued"]),
        "ingredients": json.loads(row["ingredients_json"]),
        "source_id": row["source_id"],
    }


def search_products(query: str, limit: int = 20, offset: int = 0):
    terms = [term.strip() for term in query.split() if term.strip()]
    if not terms:
        return [], 0
    where = " AND ".join("(brand_name LIKE ? OR manufacturer LIKE ? OR raw_composition LIKE ?)" for _ in terms)
    args = [pattern for term in terms for pattern in (f"%{term}%", f"%{term}%", f"%{term}%")]
    with connect() as db:
        total = db.execute(f"SELECT COUNT(*) FROM products WHERE {where}", args).fetchone()[0]
        rows = db.execute(f"SELECT * FROM products WHERE {where} ORDER BY discontinued, brand_name LIMIT ? OFFSET ?",
                          [*args, limit, offset]).fetchall()
    return [product_payload(row) for row in rows], total


def canonical_strength(value: str):
    text = re.sub(r"\s+", "", value.lower()).replace("μ", "u").replace("µ", "u")
    # Preserve denominator and unit. Convert mass units to mcg only when the denominator matches.
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(mcg|ug|mg|g)(?:/(\d+(?:\.\d+)?)(ml|tablet|tab|capsule|cap|dose))?", text)
    if not match:
        return None
    amount, unit, denominator, denominator_unit = match.groups()
    factor = {"g": 1_000_000, "mg": 1_000, "mcg": 1, "ug": 1}[unit]
    den_unit = {"tab": "tablet", "cap": "capsule"}.get(denominator_unit, denominator_unit)
    return (float(amount) * factor, den_unit, float(denominator) if denominator else 1.0)


def _form(value):
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _canonical_ingredients(items):
    values = [(item["name"].casefold().strip(), canonical_strength(item["strength"])) for item in items]
    if not values or any(strength is None for _, strength in values):
        return None
    return sorted(values, key=repr)


def equivalent_products(first, second):
    return bool(_canonical_ingredients(first["ingredients"])) and \
        _canonical_ingredients(first["ingredients"]) == _canonical_ingredients(second["ingredients"]) and \
        bool(first["dosage_form"] and second["dosage_form"] and _form(first["dosage_form"]) == _form(second["dosage_form"])) and \
        bool(first["release_type"] and second["release_type"] and first["release_type"].casefold() not in {"unknown", ""} and first["release_type"].casefold() == second["release_type"].casefold()) and \
        bool(first["route"] and second["route"] and first["route"].casefold() not in {"unknown", ""} and first["route"].casefold() == second["route"].casefold())


def compare_product(request, product):
    expected = sorted(((i.name.casefold().strip(), canonical_strength(i.strength)) for i in request.ingredients), key=repr)
    actual = sorted(((i["name"].casefold().strip(), canonical_strength(i["strength"])) for i in product["ingredients"]), key=repr)
    exact = bool(expected and actual) and all(x[1] is not None for x in expected + actual)
    exact = exact and expected == actual
    exact = exact and _form(request.dosage_form) == _form(product["dosage_form"] or "")
    exact = exact and bool(product["release_type"] and product["route"])
    exact = exact and request.release_type.casefold() != "unknown" and request.route.casefold() != "unknown"
    exact = exact and request.release_type.casefold() == (product["release_type"] or "").casefold()
    exact = exact and request.route.casefold() == (product["route"] or "").casefold()
    if exact:
        return "EXACT", ["All recorded ingredient, strength, dosage form, release type, and route fields match."]
    ratio = SequenceMatcher(None, " ".join(i.name for i in request.ingredients).lower(), product["brand_name"].lower()).ratio()
    if exact or ratio >= 0.45:
        return "CLOSE", ["Candidate similarity is not proof of therapeutic equivalence."]
    return "NONE", ["Required canonical fields do not match or are unavailable."]


def find_match(request):
    with connect() as db:
        rows = db.execute("SELECT * FROM products WHERE discontinued = 0 ORDER BY brand_name LIMIT 5000").fetchall()
    ranked = []
    for row in rows:
        product = product_payload(row)
        tier, reasons = compare_product(request, product)
        if tier != "NONE":
            ranked.append((tier, product, reasons))
    ranked.sort(key=lambda item: (item[0] != "CLOSE", item[1]["brand_name"].casefold()))
    return [{"tier": tier, "product": product, "reasons": reasons} for tier, product, reasons in ranked[:20]]


def savings(product_id: str, alternative_id: str, units_per_day: float | None):
    with connect() as db:
        rows = db.execute("SELECT * FROM products WHERE id IN (?,?)", (product_id, alternative_id)).fetchall()
    by_id = {row["id"]: product_payload(row) for row in rows}
    if product_id not in by_id or alternative_id not in by_id:
        return {"status": "unavailable", "reason": "product_not_found"}
    original, alternative = by_id[product_id], by_id[alternative_id]
    if not equivalent_products(original, alternative):
        return {"status": "unavailable", "reason": "equivalence_not_verified"}
    if original["price_date"] is None or alternative["price_date"] is None:
        return {"status": "unavailable", "reason": "price_date_missing", "prices": [original, alternative]}
    if original["price_inr"] is None or alternative["price_inr"] is None:
        return {"status": "unavailable", "reason": "price_missing"}
    if original["pack_unit"] != alternative["pack_unit"] or original["pack_unit"] not in {"tablet", "capsule", "ml", "dose"}:
        return {"status": "unavailable", "reason": "pack_unit_not_comparable"}
    if not original["pack_size"] or not alternative["pack_size"]:
        return {"status": "unavailable", "reason": "pack_size_missing"}
    unit_a = original["price_inr"] / original["pack_size"]
    unit_b = alternative["price_inr"] / alternative["pack_size"]
    response = {"status": "available", "unit_price_original_inr": round(unit_a, 2),
                "unit_price_alternative_inr": round(unit_b, 2), "saving_per_unit_inr": round(unit_a-unit_b, 2),
                "price_date": original["price_date"], "source_id": original["source_id"],
                "disclaimer": "Prices are source-dependent. Confirm any medicine change with your doctor or pharmacist."}
    if units_per_day:
        response["monthly_saving_inr"] = round((unit_a-unit_b) * units_per_day * 30, 2)
        response["yearly_saving_inr"] = round((unit_a-unit_b) * units_per_day * 360, 2)
    return response
