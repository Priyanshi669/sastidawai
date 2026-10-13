"""Resolver package for normalization, canonicalization, and candidate resolution."""

from ml.resolver.normalize import (
    NormalizedIngredient,
    NormalizedStrength,
    NormalizedComposition,
    normalize_salt_name,
    normalize_strength,
    normalize_dosage_form,
    normalize_release_type,
    normalize_route,
    normalize_composition_items,
    parse_composition_string,
    are_strengths_equivalent,
    are_compositions_equivalent,
)
from ml.resolver.candidates import (
    CandidateRecord,
    CandidateResolver,
    ResolverResult,
    ResolverStatus,
    product_record_to_canonical,
)

__all__ = [
    "NormalizedIngredient",
    "NormalizedStrength",
    "NormalizedComposition",
    "normalize_salt_name",
    "normalize_strength",
    "normalize_dosage_form",
    "normalize_release_type",
    "normalize_route",
    "normalize_composition_items",
    "parse_composition_string",
    "are_strengths_equivalent",
    "are_compositions_equivalent",
    "CandidateRecord",
    "CandidateResolver",
    "ResolverResult",
    "ResolverStatus",
    "product_record_to_canonical",
]

