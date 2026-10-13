"""Image validation and quality checks using OpenCV heuristics.

Evaluates 1 to 3 medicine pack images for:
1. Supported formats (JPEG, PNG, WebP) and size limits (at most 1.5 MB per image).
2. Corrupt, empty, or truncated byte payloads.
3. Blur detection via Variance of the Laplacian.
4. Lighting conditions (under-exposure and over-exposure).
5. Saturated glare reflections on blister foil/packaging.
6. Actionable retake guidance with configurable thresholds.

Safety Boundary:
Image quality passing is NEVER proof of medicine identity or equivalence.
It solely gates progression from perception into extraction.
"""

from io import BytesIO
from typing import List, Optional, Set, Tuple
import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from ml.schemas.enums import ScanWorkflowState
from ml.schemas.quality import (
    ImageQualityCheck,
    ImageQualityReport,
    MultiImageQualityReport,
    SingleImageQualityReport,
)


class QualityThresholds(BaseModel):
    """Configurable thresholds for image ingestion and quality gates."""
    max_file_size_bytes: int = Field(default=1_572_864, description="Maximum single image size (1.5 MB).")
    max_batch_size_bytes: int = Field(default=4_718_592, description="Maximum total batch size (4.5 MB).")
    allowed_formats: Set[str] = Field(default={"JPEG", "JPG", "PNG", "WEBP"}, description="Allowed formats.")
    min_images: int = Field(default=1, ge=1)
    max_images: int = Field(default=3, le=3)
    min_dimension_px: int = Field(default=100, description="Minimum width and height in pixels.")
    max_dimension_px: int = Field(default=4096, description="Maximum width or height in pixels.")
    max_total_pixels: int = Field(default=16_000_000, description="Maximum decoded pixel count (16 MP).")
    min_blur_score: float = Field(default=100.0, description="Minimum Laplacian variance for sharpness.")
    min_brightness: float = Field(default=40.0, description="Minimum mean grayscale intensity (0-255).")
    max_brightness: float = Field(default=235.0, description="Maximum mean grayscale intensity (0-255).")
    max_glare_ratio: float = Field(default=0.15, description="Maximum allowable fraction of saturated pixels.")


class ImageQualityValidator:
    """Validator evaluating image byte payloads against quality thresholds."""

    def __init__(self, thresholds: Optional[QualityThresholds] = None):
        self.thresholds = thresholds or QualityThresholds()

    def validate_single_image(
        self,
        image_bytes: bytes,
        index: int = 0,
    ) -> SingleImageQualityReport:
        """Validates format, size, corruption, and visual quality of a single image payload."""
        file_size = len(image_bytes)

        # 1. Empty payload check
        if file_size == 0:
            return SingleImageQualityReport(
                image_index=index,
                passed=False,
                workflow_state=ScanWorkflowState.REJECT_IMAGE,
                file_size_bytes=0,
                feedback_messages=["Uploaded image file is empty (0 bytes)."],
            )

        # 2. File size limit check
        if file_size > self.thresholds.max_file_size_bytes:
            size_mb = round(file_size / (1024 * 1024), 2)
            limit_mb = round(self.thresholds.max_file_size_bytes / (1024 * 1024), 2)
            return SingleImageQualityReport(
                image_index=index,
                passed=False,
                workflow_state=ScanWorkflowState.REJECT_IMAGE,
                file_size_bytes=file_size,
                feedback_messages=[
                    f"Image size ({size_mb} MB) exceeds maximum allowed limit of {limit_mb} MB. "
                    "Please compress or capture a standard resolution photo."
                ],
            )

        # 3. Format, corruption, decompression bomb, and content validation via PIL
        img_format: Optional[str] = None
        width: Optional[int] = None
        height: Optional[int] = None

        # Guard against decompression bombs at PIL level while preserving global state
        original_max_pixels = Image.MAX_IMAGE_PIXELS
        try:
            Image.MAX_IMAGE_PIXELS = self.thresholds.max_total_pixels
            with Image.open(BytesIO(image_bytes)) as pil_img:
                img_format = (pil_img.format or "").upper()

                # Check allowed formats
                if img_format not in self.thresholds.allowed_formats:
                    return SingleImageQualityReport(
                        image_index=index,
                        passed=False,
                        workflow_state=ScanWorkflowState.REJECT_IMAGE,
                        format=img_format,
                        file_size_bytes=file_size,
                        feedback_messages=[
                            f"Unsupported image format: '{img_format}'. Supported formats are JPEG, PNG, and WebP."
                        ],
                    )

                raw_w, raw_h = pil_img.size

                # Mitigate decompression bombs (dimension ceiling & pixel count guard)
                if (
                    raw_w > self.thresholds.max_dimension_px
                    or raw_h > self.thresholds.max_dimension_px
                    or (raw_w * raw_h) > self.thresholds.max_total_pixels
                ):
                    return SingleImageQualityReport(
                        image_index=index,
                        passed=False,
                        workflow_state=ScanWorkflowState.REJECT_IMAGE,
                        format=img_format,
                        file_size_bytes=file_size,
                        width_px=raw_w,
                        height_px=raw_h,
                        feedback_messages=[
                            f"Image dimensions ({raw_w}x{raw_h}, {raw_w * raw_h} px) exceed safety limits "
                            f"(max {self.thresholds.max_dimension_px}px or {self.thresholds.max_total_pixels} pixels). "
                            "Image rejected to mitigate decompression bombs."
                        ],
                    )

                # Check minimum dimensions
                if raw_w < self.thresholds.min_dimension_px or raw_h < self.thresholds.min_dimension_px:
                    return SingleImageQualityReport(
                        image_index=index,
                        passed=False,
                        workflow_state=ScanWorkflowState.REJECT_IMAGE,
                        format=img_format,
                        file_size_bytes=file_size,
                        width_px=raw_w,
                        height_px=raw_h,
                        feedback_messages=[
                            f"Image dimensions ({raw_w}x{raw_h} px) are too small to read packaging text. "
                            f"Minimum dimension is {self.thresholds.min_dimension_px} px."
                        ],
                    )

                # Correct EXIF orientation so rotated camera photos are oriented upright
                oriented_img = ImageOps.exif_transpose(pil_img)
                if oriented_img is None:
                    oriented_img = pil_img

                width, height = oriented_img.size

                # Force full raster decompression to detect truncated/corrupted stream
                rgb_img = oriented_img.convert("RGB")
                img_np = np.array(rgb_img)

        except (Image.DecompressionBombError, UnidentifiedImageError, OSError, SyntaxError, Exception) as exc:
            err_msg = (
                "Decompression bomb detected. Image dimensions exceed safe processing limit."
                if isinstance(exc, Image.DecompressionBombError)
                else "File is corrupt, damaged, or not a valid image format."
            )
            return SingleImageQualityReport(
                image_index=index,
                passed=False,
                workflow_state=ScanWorkflowState.REJECT_IMAGE,
                file_size_bytes=file_size,
                feedback_messages=[err_msg],
            )
        finally:
            Image.MAX_IMAGE_PIXELS = original_max_pixels

        # 4. Convert decoded raster to grayscale for heuristic measurements
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)

        # 5. Heuristic Calculations
        # A. Blur score via Laplacian variance
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        is_blurry = blur_score < self.thresholds.min_blur_score

        # B. Brightness score via mean grayscale intensity
        brightness_score = float(np.mean(gray))
        is_too_dark = brightness_score < self.thresholds.min_brightness
        is_too_bright = brightness_score > self.thresholds.max_brightness

        # C. Glare ratio (fraction of saturated pixels > 250)
        glare_pixels = int(np.sum(gray >= 250))
        glare_ratio = float(glare_pixels / float(gray.size))
        has_glare = glare_ratio > self.thresholds.max_glare_ratio

        metrics = ImageQualityCheck(
            blur_score=round(blur_score, 2),
            is_blurry=is_blurry,
            brightness_score=round(brightness_score, 2),
            is_too_dark=is_too_dark,
            is_too_bright=is_too_bright,
            glare_ratio=round(glare_ratio, 4),
            has_glare=has_glare,
        )

        # 6. Actionable Retake Guidance
        feedback: List[str] = []
        if is_blurry:
            feedback.append("Image is blurry. Please hold camera steady and refocus on the packaging text.")
        if is_too_dark:
            feedback.append("Lighting is too dark. Move to a well-lit area or use camera flash.")
        if is_too_bright:
            feedback.append("Image is washed out. Move away from harsh overhead glare or reflection.")
        if has_glare:
            feedback.append("Severe glare detected on blister foil. Tilt packaging slightly to avoid light reflection.")

        passed = not (is_blurry or is_too_dark or is_too_bright or has_glare)
        workflow_state = ScanWorkflowState.READY_FOR_MATCHING if passed else ScanWorkflowState.RETAKE_REQUIRED

        return SingleImageQualityReport(
            image_index=index,
            passed=passed,
            workflow_state=workflow_state,
            format=img_format,
            file_size_bytes=file_size,
            width_px=width,
            height_px=height,
            metrics=metrics,
            feedback_messages=feedback,
        )

    def validate_images(self, images: List[bytes]) -> MultiImageQualityReport:
        """Validates a batch of 1 to 3 images and generates an aggregate quality report."""
        n = len(images)

        # Enforce image count boundaries
        if n < self.thresholds.min_images:
            return MultiImageQualityReport(
                total_images=0,
                passed=False,
                workflow_state=ScanWorkflowState.REJECT_IMAGE,
                feedback_messages=["At least one medicine pack image is required."],
                image_reports=[],
            )

        if n > self.thresholds.max_images:
            return MultiImageQualityReport(
                total_images=n,
                passed=False,
                workflow_state=ScanWorkflowState.REJECT_IMAGE,
                feedback_messages=[
                    f"Maximum of {self.thresholds.max_images} images allowed per scan (received {n}). "
                    "Please capture 1 to 3 clear photos of the front and back of the pack."
                ],
                image_reports=[],
            )

        # Enforce total batch byte limit
        total_batch_bytes = sum(len(b) for b in images)
        if total_batch_bytes > self.thresholds.max_batch_size_bytes:
            batch_mb = round(total_batch_bytes / (1024 * 1024), 2)
            limit_mb = round(self.thresholds.max_batch_size_bytes / (1024 * 1024), 2)
            return MultiImageQualityReport(
                total_images=n,
                passed=False,
                workflow_state=ScanWorkflowState.REJECT_IMAGE,
                feedback_messages=[
                    f"Total upload size ({batch_mb} MB) exceeds maximum allowed batch limit of {limit_mb} MB. "
                    "Please compress or submit fewer/smaller images."
                ],
                image_reports=[],
            )

        reports: List[SingleImageQualityReport] = []
        for idx, img_bytes in enumerate(images):
            reports.append(self.validate_single_image(img_bytes, index=idx))

        # Check for any fatal rejection states (e.g. corrupt or unsupported formats)
        fatal_reports = [r for r in reports if r.workflow_state == ScanWorkflowState.REJECT_IMAGE]
        if fatal_reports:
            consolidated_feedback = []
            for r in fatal_reports:
                for msg in r.feedback_messages:
                    if msg not in consolidated_feedback:
                        consolidated_feedback.append(f"Image {r.image_index + 1}: {msg}")
            return MultiImageQualityReport(
                total_images=n,
                passed=False,
                workflow_state=ScanWorkflowState.REJECT_IMAGE,
                feedback_messages=consolidated_feedback,
                image_reports=reports,
            )

        # If all images failed quality heuristics (e.g. all blurry or dark), trigger RETAKE_REQUIRED
        passing_reports = [r for r in reports if r.passed]
        if not passing_reports:
            consolidated_feedback = []
            for r in reports:
                for msg in r.feedback_messages:
                    if msg not in consolidated_feedback:
                        consolidated_feedback.append(msg)
            return MultiImageQualityReport(
                total_images=n,
                passed=False,
                workflow_state=ScanWorkflowState.RETAKE_REQUIRED,
                feedback_messages=consolidated_feedback,
                image_reports=reports,
            )

        # At least one image passed quality checks cleanly
        return MultiImageQualityReport(
            total_images=n,
            passed=True,
            workflow_state=ScanWorkflowState.READY_FOR_MATCHING,
            feedback_messages=[],
            image_reports=reports,
        )
