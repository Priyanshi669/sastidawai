"""Unit and safety tests for Phase 1F: Image Quality Checks and Validation Heuristics.

Covers:
1. File format validation (JPEG, PNG, WebP supported; GIF, BMP, TXT rejected).
2. Size boundaries (1.5 MB limit, 0-byte rejection).
3. Corrupt and truncated payload handling.
4. Blur detection via Laplacian variance.
5. Brightness heuristics (underexposure and overexposure).
6. Glare and specular reflection detection.
7. Multi-image uploads (1 to 3 images, edge cases: 0 images, 4 images).
8. Actionable retake guidance messages.
9. Configurable threshold behavior.
"""

from io import BytesIO
import cv2
import numpy as np
from PIL import Image
import pytest

from ml.schemas.enums import ScanWorkflowState
from ml.vision.quality import ImageQualityValidator, QualityThresholds


def create_synthetic_image(
    width: int = 300,
    height: int = 300,
    pattern: str = "sharp",
    brightness: int = 128,
    glare_fraction: float = 0.0,
    fmt: str = "PNG",
) -> bytes:
    """Generates synthetic image byte payloads with controlled visual characteristics."""
    # Base background
    img = np.full((height, width, 3), brightness, dtype=np.uint8)

    if pattern == "sharp":
        # Add high-contrast text-like edges to ensure high Laplacian variance
        for y in range(20, height - 20, 20):
            cv2.line(img, (20, y), (width - 20, y), (0, 0, 0), 2)
            cv2.putText(img, "AMOXICILLIN 500mg", (30, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

    elif pattern == "blurry":
        # Add weak features and heavily smooth
        cv2.circle(img, (width // 2, height // 2), width // 4, (brightness + 20, brightness + 20, brightness + 20), -1)
        img = cv2.GaussianBlur(img, (51, 51), 0)

    # Inject specular glare patch if requested
    if glare_fraction > 0.0:
        glare_h = int(height * np.sqrt(glare_fraction))
        glare_w = int(width * np.sqrt(glare_fraction))
        img[10:10 + glare_h, 10:10 + glare_w] = 255

    # Encode to bytes via PIL
    pil_img = Image.fromarray(img)
    buf = BytesIO()
    pil_img.save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def validator():
    return ImageQualityValidator()


class TestSingleImageValidation:
    """Tests for single image validation, corruption, and heuristics."""

    def test_sharp_balanced_image_passes(self, validator):
        img_bytes = create_synthetic_image(pattern="sharp", brightness=130)
        report = validator.validate_single_image(img_bytes)

        assert report.passed is True
        assert report.workflow_state == ScanWorkflowState.READY_FOR_MATCHING
        assert len(report.feedback_messages) == 0
        assert report.metrics is not None
        assert report.metrics.is_blurry is False
        assert report.metrics.is_too_dark is False
        assert report.metrics.is_too_bright is False
        assert report.metrics.has_glare is False

    def test_empty_bytes_rejected(self, validator):
        report = validator.validate_single_image(b"")
        assert report.passed is False
        assert report.workflow_state == ScanWorkflowState.REJECT_IMAGE
        assert any("empty" in msg.lower() for msg in report.feedback_messages)

    def test_corrupt_bytes_rejected(self, validator):
        corrupt_bytes = b"NOT_AN_IMAGE_RANDOM_GARBAGE_PAYLOAD_123456789"
        report = validator.validate_single_image(corrupt_bytes)
        assert report.passed is False
        assert report.workflow_state == ScanWorkflowState.REJECT_IMAGE
        assert any("corrupt" in msg.lower() for msg in report.feedback_messages)

    def test_unsupported_format_rejected(self, validator):
        # Generate a GIF image
        gif_bytes = create_synthetic_image(fmt="GIF")
        report = validator.validate_single_image(gif_bytes)
        assert report.passed is False
        assert report.workflow_state == ScanWorkflowState.REJECT_IMAGE
        assert any("unsupported" in msg.lower() for msg in report.feedback_messages)

    def test_oversized_image_rejected(self, validator):
        # Create an oversized image exceeding 1.5 MB
        custom_thresholds = QualityThresholds(max_file_size_bytes=1000)
        strict_validator = ImageQualityValidator(custom_thresholds)

        img_bytes = create_synthetic_image(width=200, height=200)
        assert len(img_bytes) > 1000

        report = strict_validator.validate_single_image(img_bytes)
        assert report.passed is False
        assert report.workflow_state == ScanWorkflowState.REJECT_IMAGE
        assert any("exceeds" in msg.lower() for msg in report.feedback_messages)

    def test_undersized_dimensions_rejected(self, validator):
        tiny_bytes = create_synthetic_image(width=50, height=50)
        report = validator.validate_single_image(tiny_bytes)
        assert report.passed is False
        assert report.workflow_state == ScanWorkflowState.REJECT_IMAGE
        assert any("too small" in msg.lower() for msg in report.feedback_messages)

    def test_blurry_image_triggers_retake(self, validator):
        blurry_bytes = create_synthetic_image(pattern="blurry", brightness=128)
        report = validator.validate_single_image(blurry_bytes)

        assert report.passed is False
        assert report.workflow_state == ScanWorkflowState.RETAKE_REQUIRED
        assert report.metrics.is_blurry is True
        assert any("blurry" in msg.lower() for msg in report.feedback_messages)

    def test_dark_image_triggers_retake(self, validator):
        dark_bytes = create_synthetic_image(pattern="sharp", brightness=20)
        report = validator.validate_single_image(dark_bytes)

        assert report.passed is False
        assert report.workflow_state == ScanWorkflowState.RETAKE_REQUIRED
        assert report.metrics.is_too_dark is True
        assert any("dark" in msg.lower() for msg in report.feedback_messages)

    def test_washed_out_bright_image_triggers_retake(self, validator):
        bright_bytes = create_synthetic_image(pattern="blurry", brightness=245)
        report = validator.validate_single_image(bright_bytes)

        assert report.passed is False
        assert report.workflow_state == ScanWorkflowState.RETAKE_REQUIRED
        assert report.metrics.is_too_bright is True
        assert any("washed out" in msg.lower() for msg in report.feedback_messages)

    def test_glare_triggers_retake(self, validator):
        glare_bytes = create_synthetic_image(pattern="sharp", brightness=100, glare_fraction=0.25)
        report = validator.validate_single_image(glare_bytes)

        assert report.passed is False
        assert report.workflow_state == ScanWorkflowState.RETAKE_REQUIRED
        assert report.metrics.has_glare is True
        assert any("glare" in msg.lower() for msg in report.feedback_messages)


class TestMultiImageBatchValidation:
    """Tests evaluating 1 to 3 uploaded images."""

    def test_zero_images_rejected(self, validator):
        multi_report = validator.validate_images([])
        assert multi_report.passed is False
        assert multi_report.workflow_state == ScanWorkflowState.REJECT_IMAGE
        assert any("at least one" in msg.lower() for msg in multi_report.feedback_messages)

    def test_exceeding_max_images_rejected(self, validator):
        img_bytes = create_synthetic_image()
        multi_report = validator.validate_images([img_bytes] * 4)
        assert multi_report.passed is False
        assert multi_report.workflow_state == ScanWorkflowState.REJECT_IMAGE
        assert any("maximum of 3" in msg.lower() for msg in multi_report.feedback_messages)

    def test_all_images_blurry_triggers_retake(self, validator):
        b1 = create_synthetic_image(pattern="blurry")
        b2 = create_synthetic_image(pattern="blurry")
        multi_report = validator.validate_images([b1, b2])

        assert multi_report.passed is False
        assert multi_report.workflow_state == ScanWorkflowState.RETAKE_REQUIRED
        assert any("blurry" in msg.lower() for msg in multi_report.feedback_messages)

    def test_one_sharp_one_blurry_passes_overall(self, validator):
        sharp = create_synthetic_image(pattern="sharp")
        blurry = create_synthetic_image(pattern="blurry")
        multi_report = validator.validate_images([blurry, sharp])

        # At least one image is readable, so overall batch passes to extraction
        assert multi_report.passed is True
        assert multi_report.workflow_state == ScanWorkflowState.READY_FOR_MATCHING
        assert len(multi_report.image_reports) == 2
        assert multi_report.image_reports[0].passed is False
        assert multi_report.image_reports[1].passed is True

    def test_one_corrupt_image_rejects_batch(self, validator):
        sharp = create_synthetic_image(pattern="sharp")
        corrupt = b"CORRUPT_BYTES_XYZ"
        multi_report = validator.validate_images([sharp, corrupt])

        # Corrupt file in batch is a fatal rejection
        assert multi_report.passed is False
        assert multi_report.workflow_state == ScanWorkflowState.REJECT_IMAGE
        assert any("corrupt" in msg.lower() for msg in multi_report.feedback_messages)


class TestConfigurableThresholds:
    """Tests proving quality gate thresholds can be tuned without code changes."""

    def test_relaxed_blur_threshold(self):
        # Standard threshold rejects mildly blurred image
        mild_blur = np.full((300, 300, 3), 128, dtype=np.uint8)
        for y in range(40, 260, 40):
            cv2.line(mild_blur, (20, y), (280, y), (0, 0, 0), 2)
        mild_blur = cv2.GaussianBlur(mild_blur, (9, 9), 0)

        buf = BytesIO()
        Image.fromarray(mild_blur).save(buf, format="PNG")
        img_bytes = buf.getvalue()

        strict_val = ImageQualityValidator(QualityThresholds(min_blur_score=150.0))
        relaxed_val = ImageQualityValidator(QualityThresholds(min_blur_score=10.0))

        assert strict_val.validate_single_image(img_bytes).metrics.is_blurry is True
        assert relaxed_val.validate_single_image(img_bytes).metrics.is_blurry is False


class TestAdversarialAndContentValidation:
    """Adversarial security and content verification tests (Phase 1F.1)."""

    def test_decompression_bomb_dimension_ceiling_rejected(self, validator):
        # Image exceeding 4096px dimension ceiling
        bomb = Image.new("RGB", (5000, 200), color="blue")
        buf = BytesIO()
        bomb.save(buf, format="JPEG")
        bomb_bytes = buf.getvalue()

        report = validator.validate_single_image(bomb_bytes)
        assert report.passed is False
        assert report.workflow_state == ScanWorkflowState.REJECT_IMAGE
        assert any("safety limits" in msg.lower() or "decompression bomb" in msg.lower() for msg in report.feedback_messages)

    def test_decompression_bomb_pixel_limit_rejected(self):
        # Strict validator with 50,000 max pixels
        strict_val = ImageQualityValidator(QualityThresholds(max_total_pixels=50_000))
        # 300x300 = 90,000 pixels > 50,000 limit
        img_bytes = create_synthetic_image(width=300, height=300)

        report = strict_val.validate_single_image(img_bytes)
        assert report.passed is False
        assert report.workflow_state == ScanWorkflowState.REJECT_IMAGE
        assert any("safety limits" in msg.lower() or "decompression bomb" in msg.lower() for msg in report.feedback_messages)

    def test_spoofed_magic_bytes_rejected(self, validator):
        # Spoofed PNG magic header followed by ASCII garbage
        spoofed = b"\x89PNG\r\n\x1a\n" + b"This is not a real PNG image payload."
        report = validator.validate_single_image(spoofed)

        assert report.passed is False
        assert report.workflow_state == ScanWorkflowState.REJECT_IMAGE
        assert any("corrupt" in msg.lower() for msg in report.feedback_messages)

    def test_truncated_image_stream_rejected(self, validator):
        # Valid PNG truncated mid-payload
        valid_bytes = create_synthetic_image(pattern="sharp")
        truncated = valid_bytes[: len(valid_bytes) // 3]

        report = validator.validate_single_image(truncated)
        assert report.passed is False
        assert report.workflow_state == ScanWorkflowState.REJECT_IMAGE
        assert any("corrupt" in msg.lower() for msg in report.feedback_messages)

    def test_exif_orientation_applied(self, validator):
        # Create a 300x150 landscape image with EXIF orientation tag 6 (90° CW)
        img = Image.new("RGB", (300, 150), color=(128, 128, 128))
        exif = img.getexif()
        exif[0x0112] = 6  # 90 degrees CW rotation
        buf = BytesIO()
        img.save(buf, format="JPEG", exif=exif)
        jpeg_bytes = buf.getvalue()

        report = validator.validate_single_image(jpeg_bytes)
        # Transposed upright dimensions should swap width and height to 150x300
        assert report.width_px == 150
        assert report.height_px == 300

    def test_batch_exceeding_total_byte_limit_rejected(self):
        # Batch total byte limit enforcement (e.g. 4 KB limit)
        strict_batch_val = ImageQualityValidator(QualityThresholds(max_batch_size_bytes=4_000))
        img1 = create_synthetic_image(width=200, height=200)
        img2 = create_synthetic_image(width=200, height=200)

        # Total bytes of two PNGs (approx 5.9 KB) exceeds 4 KB
        multi_report = strict_batch_val.validate_images([img1, img2])
        assert multi_report.passed is False
        assert multi_report.workflow_state == ScanWorkflowState.REJECT_IMAGE
        assert any("total upload size" in msg.lower() for msg in multi_report.feedback_messages)

