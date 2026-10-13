"""Schema definitions for Optical Character Recognition (OCR) outputs and provenance."""

from typing import List, Optional
from pydantic import BaseModel, Field


class OCRTextLine(BaseModel):
    """A single recognized line of text with bounding box and confidence."""
    line_number: int = Field(ge=0, description="0-indexed line sequence.")
    text: str = Field(..., min_length=1, description="Recognized text content.")
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score for this line (normalized to 0.0-1.0)."
    )
    bounding_box: Optional[List[int]] = Field(
        default=None,
        description="Coordinates [x, y, w, h] of the detected text bounding box in pixels."
    )


class OCRResult(BaseModel):
    """Normalized structured result from an OCR extraction engine."""
    engine_name: str = Field(..., description="Identifier of the OCR engine (e.g. 'tesseract', 'mock_ocr').")
    is_successful: bool = Field(..., description="True if text extraction succeeded without fatal error.")
    raw_text: str = Field(default="", description="Aggregated raw plaintext output from OCR.")
    lines: List[OCRTextLine] = Field(default_factory=list, description="Parsed individual text lines.")
    mean_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Mean confidence across recognized text lines. Never treated as proof of identity."
    )
    error_message: Optional[str] = Field(default=None, description="Error reason if is_successful is False.")
    latency_ms: Optional[int] = Field(default=None, ge=0, description="Execution duration in milliseconds.")
