"""Unit and reliability tests for Phase 1G: Provider-independent OCR adapter.

Covers:
1. BaseOCREngine interface contract.
2. TesseractOCREngine graceful unavailability detection and structured error responses.
3. MockOCREngine presets (Augmentin, Glycomet, conflicts, unreadable, malformed).
4. Custom queued OCR results and batch extraction.
5. Simulated OCR timeout and failure handling.
6. Input boundary validation (empty payload rejection).
"""

import pytest

from ml.schemas.ocr import OCRResult, OCRTextLine
from ml.vision.ocr import (
    BaseOCREngine,
    MockOCREngine,
    MockOCRPreset,
    TesseractOCREngine,
)


@pytest.fixture
def dummy_image_bytes():
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 50


class TestTesseractEngineSafety:
    """Verifies Tesseract adapter behavior when running without system binaries."""

    def test_tesseract_graceful_unavailability_reporting(self, dummy_image_bytes):
        # Configure non-existent binary path
        engine = TesseractOCREngine(tesseract_cmd="non_existent_tesseract_binary_xyz")
        assert engine.is_available() is False

        # Must NOT crash; returns structured failure result
        res = engine.extract_text(dummy_image_bytes)
        assert isinstance(res, OCRResult)
        assert res.engine_name == "tesseract"
        assert res.is_successful is False
        assert "not installed" in res.error_message.lower() or "not found" in res.error_message.lower()
        assert res.lines == []


class TestMockOCREnginePresets:
    """Verifies standard domain fixtures of the offline mock OCR engine."""

    def test_augmentin_preset_output(self, dummy_image_bytes):
        engine = MockOCREngine(MockOCRPreset.AUGMENTIN_625_DUO)
        res = engine.extract_text(dummy_image_bytes)

        assert res.is_successful is True
        assert res.engine_name == "mock_ocr"
        assert "Augmentin 625 Duo" in res.raw_text
        assert "Amoxycillin" in res.raw_text
        assert "Potassium Clavulanate" in res.raw_text
        assert len(res.lines) >= 5
        assert res.mean_confidence > 0.85

    def test_glycomet_preset_output(self, dummy_image_bytes):
        engine = MockOCREngine(MockOCRPreset.GLYCOMET_500_PR)
        res = engine.extract_text(dummy_image_bytes)

        assert res.is_successful is True
        assert "Glycomet 500 PR" in res.raw_text
        assert "Metformin Hydrochloride" in res.raw_text
        assert "500 mg" in res.raw_text

    def test_glycomet_1000_conflict_preset(self, dummy_image_bytes):
        engine = MockOCREngine(MockOCRPreset.GLYCOMET_1000_PR_CONFLICT)
        res = engine.extract_text(dummy_image_bytes)

        assert res.is_successful is True
        assert "1000 mg" in res.raw_text

    def test_blurry_unreadable_preset(self, dummy_image_bytes):
        engine = MockOCREngine(MockOCRPreset.BLURRY_UNREADABLE)
        res = engine.extract_text(dummy_image_bytes)

        assert res.is_successful is True
        assert res.mean_confidence < 0.30

    def test_malformed_engine_crash_preset(self, dummy_image_bytes):
        engine = MockOCREngine(MockOCRPreset.MALFORMED_OUTPUT)
        res = engine.extract_text(dummy_image_bytes)

        assert res.is_successful is False
        assert "crashed" in res.error_message.lower()


class TestMockOCRExecutionControls:
    """Verifies queueing, simulated timeouts, and batch extraction."""

    def test_empty_bytes_rejected(self):
        engine = MockOCREngine()
        with pytest.raises(ValueError, match="at least 1 byte"):
            engine.extract_text(b"")

    def test_custom_queued_result(self, dummy_image_bytes):
        engine = MockOCREngine()
        custom = OCRResult(
            engine_name="custom_test",
            is_successful=True,
            raw_text="PARACETAMOL 650 MG",
            lines=[OCRTextLine(line_number=0, text="PARACETAMOL 650 MG", confidence=0.99)],
            mean_confidence=0.99,
        )
        engine.queue_result(custom)
        res = engine.extract_text(dummy_image_bytes)

        assert res.engine_name == "custom_test"
        assert res.raw_text == "PARACETAMOL 650 MG"

    def test_simulated_failure_mode(self, dummy_image_bytes):
        engine = MockOCREngine()
        engine.set_failure_mode("Simulated OCR worker timeout (5000ms exceeded).")

        res = engine.extract_text(dummy_image_bytes)
        assert res.is_successful is False
        assert "timeout" in res.error_message.lower()

        # Cleared mode resumes normal preset
        engine.clear_failure_mode()
        res_resumed = engine.extract_text(dummy_image_bytes)
        assert res_resumed.is_successful is True

    def test_batch_extraction_interface(self, dummy_image_bytes):
        engine = MockOCREngine(MockOCRPreset.AUGMENTIN_625_DUO)
        results = engine.extract_text_batch([dummy_image_bytes, dummy_image_bytes])

        assert len(results) == 2
        assert all(r.is_successful for r in results)
        assert engine.call_count == 2
