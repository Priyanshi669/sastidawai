"""Pipeline orchestration layer connecting image quality, extraction, OCR, resolver, and matcher."""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
import uuid

from ml.resolver.candidates import CandidateResolver, ResolverResult
from ml.safety.gates import (
    EvidenceCrossVerificationResult,
    cross_verify_vision_and_ocr,
)
from ml.schemas.api import ScanResponse
from ml.schemas.enums import MatchTier, ScanWorkflowState
from ml.schemas.extraction import RawMedicineExtraction
from ml.schemas.matcher import MANDATORY_DISCLAIMER, MatchResult
from ml.schemas.ocr import OCRResult
from ml.schemas.quality import ImageQualityReport, MultiImageQualityReport
from ml.vision.extractor import BaseVisionExtractor, MockVisionExtractor
from ml.vision.ocr import BaseOCREngine, MockOCREngine, TesseractOCREngine
from ml.vision.quality import (
    ImageQualityValidator,
    ImageValidationError,
    QualityThresholds,
)

logger = logging.getLogger("sastidawai.pipeline")


class ScanPipelineError(Exception):
    """Base exception for pipeline processing failures."""
    pass


class VisionProviderError(ScanPipelineError):
    """Raised when the vision extraction provider encounters an unrecoverable failure."""
    pass


class VisionProviderTimeoutError(ScanPipelineError):
    """Raised when the vision provider exceeds the configured processing timeout."""
    pass


class DatabaseUnavailableError(ScanPipelineError):
    """Raised when the catalogue database cannot be accessed."""
    pass


class ScanOrchestrator:
    """Orchestrates end-to-end medicine package scanning and candidate equivalence matching.
    
    Processing Order:
    1. Validate request, image count (1-3), byte caps, and image quality.
    2. Safely reject corrupt, unsupported, or non-medicine images.
    3. Run vision extractor via provider-independent interface.
    4. Validate output schema without fabricating missing values.
    5. Reconcile evidence across multi-image captures.
    6. Execute local OCR when engine is available.
    7. Cross-verify vision and OCR evidence via safety gates.
    8. Convert verified fields to canonical representations.
    9. Retrieve generic catalogue candidates via candidate resolver.
    10. Execute deterministic 5-dimension matcher.
    11. Enforce price provenance and comparable-pack constraints.
    12. Return structured ScanResponse contract.
    """

    def __init__(
        self,
        vision_extractor: Optional[BaseVisionExtractor] = None,
        ocr_engine: Optional[BaseOCREngine] = None,
        resolver: Optional[CandidateResolver] = None,
        model_version: str = "mock-vision-v1",
        max_image_count: int = 3,
        max_image_bytes: int = 10 * 1024 * 1024,
        max_batch_bytes: int = 25 * 1024 * 1024,
        timeout_seconds: float = 15.0,
        concurrency_limit: int = 10,
    ):
        self.vision_extractor = vision_extractor or MockVisionExtractor()
        if ocr_engine is not None:
            self.ocr_engine = ocr_engine
        else:
            tesseract = TesseractOCREngine()
            self.ocr_engine = tesseract if tesseract.is_available() else MockOCREngine()

        self.resolver = resolver or CandidateResolver()
        self.model_version = model_version
        self.max_image_count = max_image_count
        self.max_image_bytes = max_image_bytes
        self.max_batch_bytes = max_batch_bytes
        self.timeout_seconds = timeout_seconds
        self._concurrency_semaphore = asyncio.Semaphore(concurrency_limit)
        self.quality_thresholds = QualityThresholds(
            max_images=max_image_count,
            max_file_size_bytes=max_image_bytes,
            max_batch_size_bytes=max_batch_bytes,
        )
        self.validator = ImageQualityValidator(self.quality_thresholds)

    @staticmethod
    def _compute_field_status(extraction: RawMedicineExtraction) -> Dict[str, str]:
        """Classifies confidence per critical dimension: 'high', 'medium', 'low', 'unreadable'."""
        status_map = {}
        conf = extraction.field_confidence
        field_confs = [
            ("brand_name", conf.brand_name, extraction.brand_name is not None),
            ("composition", conf.composition, len(extraction.printed_composition) > 0),
            ("strength", conf.strength, any(item.strength_value is not None for item in extraction.printed_composition)),
            ("dosage_form", conf.dosage_form, extraction.dosage_form.value != "unknown"),
            ("release_type", conf.release_type, extraction.release_type.value != "unknown"),
        ]

        for fname, cval, is_present in field_confs:
            if not is_present or cval <= 0.0:
                status_map[fname] = "unreadable"
            elif cval >= 0.85:
                status_map[fname] = "high"
            elif cval >= 0.60:
                status_map[fname] = "medium"
            else:
                status_map[fname] = "low"

        return status_map

    @staticmethod
    def _determine_next_action(workflow_state: ScanWorkflowState) -> str:
        """Determines the appropriate next client action based on workflow state."""
        if workflow_state == ScanWorkflowState.READY_FOR_MATCHING:
            return "ready_to_match"
        elif workflow_state == ScanWorkflowState.NEEDS_USER_CONFIRMATION:
            return "confirm_fields"
        elif workflow_state == ScanWorkflowState.EXTRACTION_INCOMPLETE:
            return "confirm_or_retake"
        elif workflow_state in (ScanWorkflowState.RETAKE_REQUIRED, ScanWorkflowState.REJECT_IMAGE):
            return "retake"
        return "manual_search"

    async def process_scan(
        self,
        images: List[bytes],
        scan_id: Optional[str] = None,
        lang: str = "en",
        units_per_month: float = 60.0,
    ) -> ScanResponse:
        """Executes the full scan pipeline asynchronously with concurrency and timeout controls."""
        start_time = time.perf_counter()
        active_scan_id = scan_id or f"scan_{uuid.uuid4().hex[:12]}"
        all_warnings: List[str] = []

        async with self._concurrency_semaphore:
            # Step 1 & 2: Evaluate quality and security limits using ImageQualityValidator
            quality_report = self.validator.validate_images(images)

            # Check if image rejected (empty, corrupt, unsupported format, size limit)
            if quality_report.workflow_state == ScanWorkflowState.REJECT_IMAGE:
                err_msg = "; ".join(quality_report.feedback_messages)
                raise ImageValidationError(err_msg)

            # Check if image requires retake (blurry, dark, glare)
            if not quality_report.passed or quality_report.workflow_state == ScanWorkflowState.RETAKE_REQUIRED:
                latency = int((time.perf_counter() - start_time) * 1000)
                return ScanResponse(
                    scan_id=active_scan_id,
                    status=ScanWorkflowState.RETAKE_REQUIRED,
                    extraction=None,
                    quality_report=quality_report,
                    field_status={},
                    candidate_products=[],
                    warnings=quality_report.feedback_messages,
                    next_action="retake",
                    model_version=self.model_version,
                    latency_ms=latency,
                    match_result=None,
                    disclaimer=MANDATORY_DISCLAIMER,
                )

            # Step 4: Execute Vision Extractor via interface
            try:
                import inspect
                if inspect.iscoroutinefunction(self.vision_extractor.extract_async):
                    raw_extraction = await asyncio.wait_for(
                        self.vision_extractor.extract_async(images),
                        timeout=self.timeout_seconds,
                    )
                else:
                    raw_extraction = await asyncio.wait_for(
                        asyncio.to_thread(self.vision_extractor.extract, images),
                        timeout=self.timeout_seconds,
                    )
            except asyncio.TimeoutError:
                logger.error("Vision provider exceeded timeout threshold of %.1fs", self.timeout_seconds)
                raise VisionProviderTimeoutError(
                    f"Vision provider timed out after {self.timeout_seconds}s."
                )
            except Exception as exc:
                logger.error("Vision provider execution failed: %s", str(exc))
                raise VisionProviderError(f"Vision provider execution failed: {str(exc)}")

            # Step 5: Check medicine pack status
            if not raw_extraction.is_medicine_pack:
                latency = int((time.perf_counter() - start_time) * 1000)
                return ScanResponse(
                    scan_id=active_scan_id,
                    status=ScanWorkflowState.REJECT_IMAGE,
                    extraction=raw_extraction,
                    quality_report=quality_report,
                    field_status={},
                    candidate_products=[],
                    warnings=["Image does not appear to contain a medicine package or strip."],
                    next_action="retake",
                    model_version=self.model_version,
                    latency_ms=latency,
                    match_result=None,
                    disclaimer=MANDATORY_DISCLAIMER,
                )

            # Step 6: Execute OCR Engine (when available)
            if self.ocr_engine.is_available():
                try:
                    ocr_res = await asyncio.wait_for(
                        asyncio.to_thread(self.ocr_engine.extract_text, images[0]),
                        timeout=self.timeout_seconds,
                    )
                except Exception as exc:
                    ocr_res = OCRResult(
                        engine_name="ocr_engine",
                        is_successful=False,
                        error_message=f"OCR execution failed: {str(exc)}",
                    )
            else:
                ocr_res = OCRResult(
                    engine_name="ocr_engine",
                    is_successful=False,
                    error_message="Local OCR engine is not installed or available.",
                )

            # Step 7: Cross-verify Vision and OCR evidence using safety gates
            verification_result = cross_verify_vision_and_ocr(raw_extraction, ocr_res)
            reconciled_extraction = verification_result.reconciled_extraction
            all_warnings.extend(verification_result.warnings)

            # Step 8: Compute field confidence classifications
            field_status = self._compute_field_status(reconciled_extraction)

            # Step 9 & 10: Retrieve Catalogue Candidates & Execute Deterministic Matcher
            match_result: Optional[MatchResult] = None
            candidate_products: List[Dict[str, Any]] = []

            try:
                workflow_state, resolver_result, match_result = await asyncio.to_thread(
                    self.resolver.resolve_and_match_extraction,
                    reconciled_extraction,
                    units_per_month=units_per_month,
                )

                if resolver_result and resolver_result.candidates:
                    candidate_products = [
                        {
                            "product_id": c.product_id,
                            "name": c.canonical_name,
                            "retrieval_method": c.retrieval_method,
                            "score": c.lexical_score,
                            "evidence": c.evidence,
                            "requires_confirmation": c.requires_confirmation,
                        }
                        for c in resolver_result.candidates
                    ]

                if match_result and match_result.warnings:
                    all_warnings.extend(match_result.warnings)

            except Exception as exc:
                logger.error("Catalogue database resolution failed: %s", str(exc))
                raise DatabaseUnavailableError(f"Catalogue resolution failed: {str(exc)}")

            # Step 11: Deduplicate warnings preserving order
            unique_warnings = list(dict.fromkeys(all_warnings))

            # Step 12: Determine next action and build ScanResponse
            next_act = self._determine_next_action(workflow_state)
            latency = int((time.perf_counter() - start_time) * 1000)

            return ScanResponse(
                scan_id=active_scan_id,
                status=workflow_state,
                extraction=reconciled_extraction,
                quality_report=quality_report,
                field_status=field_status,
                candidate_products=candidate_products,
                warnings=unique_warnings,
                next_action=next_act,
                model_version=self.model_version,
                latency_ms=latency,
                match_result=match_result,
                disclaimer=MANDATORY_DISCLAIMER,
            )
