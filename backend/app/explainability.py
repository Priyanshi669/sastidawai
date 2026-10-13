from .schemas import ExplainabilityCheck, ExplainabilityResult
from .services import canonical_strength


REASON_CODES = {"active_ingredient", "strength", "dosage_form", "release_type", "route", "combination", "unknown"}
_EN = {
    "active_ingredient": "The active ingredient does not match.",
    "strength": "The strength is different, so these medicines cannot be treated as an exact match.",
    "dosage_form": "The dosage form is different.",
    "release_type": "The release type is different. Immediate-release and modified-release medicines are not treated as exact matches.",
    "route": "The route of administration is different.",
    "combination": "The active-ingredient combination is different.",
    "unknown": "The medicine could not be verified with sufficient evidence.",
}
_HI = {
    "active_ingredient": "सक्रिय घटक मेल नहीं खाता।",
    "strength": "दवा की शक्ति अलग है, इसलिए इसे सटीक मिलान नहीं माना जा सकता।",
    "dosage_form": "दवा का रूप अलग है।",
    "release_type": "रिलीज़ प्रकार अलग है। तत्काल और संशोधित रिलीज़ वाली दवाओं को सटीक मिलान नहीं माना जाता।",
    "route": "दवा लेने का मार्ग अलग है।",
    "combination": "सक्रिय घटकों का संयोजन अलग है।",
    "unknown": "पर्याप्त जानकारी से दवा की पुष्टि नहीं हो सकी।",
}


def _status(value, other, normalize=lambda item: item):
    if value is None or other is None or str(value).strip().casefold() in {"", "unknown"} or str(other).strip().casefold() in {"", "unknown"}:
        return "UNKNOWN"
    normalized_value = normalize(value)
    normalized_other = normalize(other)
    if normalized_value is None or normalized_other is None:
        return "UNKNOWN"
    return "MATCH" if normalized_value == normalized_other else "MISMATCH"


def _ingredient_statuses(request, product):
    requested = {item.name.casefold().strip(): item.strength for item in request.ingredients}
    candidate = {item["name"].casefold().strip(): item["strength"] for item in product["ingredients"]}
    names_status = "MATCH" if set(requested) == set(candidate) and requested else "MISMATCH" if requested and candidate else "UNKNOWN"
    common = set(requested) & set(candidate)
    strengths = [_status(requested[name], candidate[name], canonical_strength) for name in common]
    strength_status = "UNKNOWN" if not strengths else "MISMATCH" if "MISMATCH" in strengths else "UNKNOWN" if "UNKNOWN" in strengths else "MATCH"
    return names_status, strength_status


def make_decision_trace(request, product, tier: str) -> ExplainabilityResult:
    ingredient_status, strength_status = _ingredient_statuses(request, product)
    checks = [
        ExplainabilityCheck(attribute="active_ingredient", status=ingredient_status),
        ExplainabilityCheck(attribute="strength", status=strength_status),
        ExplainabilityCheck(attribute="dosage_form", status=_status(request.dosage_form, product.get("dosage_form"), lambda x: "".join(c for c in x.casefold() if c.isalnum()))),
        ExplainabilityCheck(attribute="release_type", status=_status(request.release_type, product.get("release_type"), str.casefold)),
        ExplainabilityCheck(attribute="route", status=_status(request.route, product.get("route"), str.casefold)),
    ]
    failures = [check.attribute for check in checks if check.status == "MISMATCH"]
    codes = []
    if "active_ingredient" in failures:
        codes.append("combination" if len(request.ingredients) > 1 or len(product.get("ingredients", [])) > 1 else "active_ingredient")
    codes.extend(attribute for attribute in ("strength", "dosage_form", "release_type", "route") if attribute in failures)
    if any(check.status == "UNKNOWN" for check in checks) and not codes:
        codes.append("unknown")
    if tier == "EXACT":
        summary = "All critical medicine attributes match in the deterministic matcher result."
        codes = []
    elif tier == "CLOSE":
        summary = "This is a candidate only; the available evidence does not verify an exact match."
        if not codes:
            codes = ["unknown"]
    else:
        summary = "The medicine could not be verified with sufficient evidence."
        if not codes:
            codes = ["unknown"]
    return ExplainabilityResult(summary=summary, checks=checks, reason_codes=codes)


def explanation_text(tier: str | None, reason_codes: list[str], language: str = "en-IN") -> str:
    if tier == "EXACT":
        return "All critical medicine attributes match in the deterministic result." if not language.startswith("hi") else "निर्धारित परिणाम में दवा के सभी महत्वपूर्ण गुण मेल खाते हैं।"
    messages = _HI if language.startswith("hi") else _EN
    codes = [code for code in reason_codes if code in REASON_CODES]
    if not codes:
        codes = ["unknown"]
    return " ".join(messages[code] for code in dict.fromkeys(codes))


def generic_explanation() -> dict:
    return {"type": "decision_trace", "summary": _EN["unknown"], "checks": [], "reason_codes": ["unknown"]}
