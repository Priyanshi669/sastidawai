"""Image quality check schemas and feedback structures."""

from typing import List, Optional
from pydantic import BaseModel, Field

from ml.schemas.enums import ScanWorkflowState


class ImageQualityCheck(BaseModel):
    """Detailed heuristic measurements for a captured medicine pack image."""
    blur_score: float = Field(
        ...,
        description="Variance of the Laplacian; higher values indicate sharper edges."
    )
    is_blurry: bool = Field(
        ...,
        description="True if blur_score falls below the calibrated sharpness threshold."
    )
    brightness_score: float = Field(
        ...,
        description="Mean pixel intensity across grayscale image (range 0 to 255)."
    )
    is_too_dark: bool = Field(
        ...,
        description="True if brightness_score is below minimum readable lighting threshold."
    )
    is_too_bright: bool = Field(
        ...,
        description="True if overall image is washed out or overexposed."
    )
    glare_ratio: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Estimated fraction of image area occupied by saturated specular reflections."
    )
    has_glare: bool = Field(
        ...,
        description="True if glare_ratio exceeds readable threshold for blister foil."
    )


class ImageQualityReport(BaseModel):
    """Overall image quality assessment and user guidance."""
    passed: bool = Field(
        ...,
        description="True if all critical heuristics pass; False if image requires retake."
    )
    workflow_state: ScanWorkflowState = Field(
        ...,
        description="Workflow state: READY_FOR_MATCHING if passed, RETAKE_REQUIRED if failed."
    )
    feedback_messages: List[str] = Field(
        default_factory=list,
        description="Actionable user tips: e.g. 'Hold steady', 'Move closer', 'Avoid reflection'."
    )
    metrics: ImageQualityCheck = Field(
        ...,
        description="Individual heuristic measurements."
    )


class SingleImageQualityReport(BaseModel):
    """Quality report for a single image within a multi-image upload."""
    image_index: int = Field(default=0, ge=0)
    passed: bool
    workflow_state: ScanWorkflowState
    format: Optional[str] = None
    file_size_bytes: int = Field(ge=0)
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    metrics: Optional[ImageQualityCheck] = None
    feedback_messages: List[str] = Field(default_factory=list)


class MultiImageQualityReport(BaseModel):
    """Comprehensive validation report for 1 to 3 uploaded medicine pack images."""
    total_images: int = Field(ge=0, description="Total images submitted in the request.")
    passed: bool
    workflow_state: ScanWorkflowState
    feedback_messages: List[str] = Field(default_factory=list)
    image_reports: List[SingleImageQualityReport] = Field(default_factory=list)

