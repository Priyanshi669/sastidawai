"""Safety package containing deterministic matching, boundary invariants, and safety gates."""

from ml.safety.gates import (
    CrossVerificationConflict,
    EvidenceCrossVerificationResult,
    cross_verify_vision_and_ocr,
    parse_dimensions_from_ocr,
)
from ml.safety.matcher import (
    DeterministicMatcher,
    evaluate_deterministic_match,
    evaluate_single_pair,
)

__all__ = [
    "DeterministicMatcher",
    "evaluate_deterministic_match",
    "evaluate_single_pair",
    "CrossVerificationConflict",
    "EvidenceCrossVerificationResult",
    "cross_verify_vision_and_ocr",
    "parse_dimensions_from_ocr",
]
