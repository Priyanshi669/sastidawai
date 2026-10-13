"""Vision processing module: quality validation, heuristics, and provider-independent extraction."""

from ml.vision.extractor import (
    BaseVisionExtractor,
    MockPreset,
    MockVisionExtractor,
)
from ml.vision.ocr import (
    BaseOCREngine,
    MockOCREngine,
    MockOCRPreset,
    TesseractOCREngine,
)
from ml.vision.quality import (
    ImageQualityValidator,
    QualityThresholds,
)
from ml.vision.reconciliation import (
    can_authorize_exact_matching,
    determine_workflow_state,
    extraction_to_canonical,
    reconcile_extractions,
)

__all__ = [
    "BaseVisionExtractor",
    "MockVisionExtractor",
    "MockPreset",
    "BaseOCREngine",
    "TesseractOCREngine",
    "MockOCREngine",
    "MockOCRPreset",
    "ImageQualityValidator",
    "QualityThresholds",
    "reconcile_extractions",
    "determine_workflow_state",
    "can_authorize_exact_matching",
    "extraction_to_canonical",
]
