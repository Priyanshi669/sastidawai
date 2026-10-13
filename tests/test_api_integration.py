"""End-to-End API integration, safety gate, and concurrency tests for POST /v1/scan."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from typing import List, Optional
import cv2
from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest

from ml.app.dependencies import get_scan_orchestrator
from ml.app.main import create_app
from ml.pipeline.orchestrator import (
    DatabaseUnavailableError,
    ScanOrchestrator,
    VisionProviderError,
    VisionProviderTimeoutError,
)
from ml.resolver.candidates import CandidateResolver
from ml.schemas.api import ProblemDetails, ScanResponse
from ml.schemas.enums import (
    DosageForm,
    MatchTier,
    ReleaseType,
    ScanWorkflowState,
)
from ml.schemas.extraction import (
    PrintedCompositionItem,
    RawMedicineExtraction,
)
from ml.schemas.matcher import MANDATORY_DISCLAIMER
from ml.vision.extractor import MockPreset, MockVisionExtractor
from ml.vision.ocr import MockOCREngine, MockOCRPreset


def create_synthetic_image(
    width: int = 300,
    height: int = 300,
    pattern: str = "sharp",
    brightness: int = 128,
    fmt: str = "PNG",
) -> bytes:
    """Generates synthetic image payloads for API multipart testing."""
    img = np.full((height, width, 3), brightness, dtype=np.uint8)

    if pattern == "sharp":
        for y in range(20, height - 20, 20):
            cv2.line(img, (20, y), (width - 20, y), (0, 0, 0), 2)
            cv2.putText(
                img,
                "AUGMENTIN 625 DUO 500mg",
                (20, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                (255, 255, 255),
                1,
            )
    elif pattern == "blurry":
        cv2.circle(img, (width // 2, height // 2), width // 4, (brightness + 10, brightness + 10, brightness + 10), -1)
        img = cv2.GaussianBlur(img, (51, 51), 0)

    pil_img = Image.fromarray(img)
    buf = BytesIO()
    pil_img.save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def sharp_image_bytes():
    return create_synthetic_image(pattern="sharp", fmt="PNG")


@pytest.fixture
def blurry_image_bytes():
    return create_synthetic_image(pattern="blurry", fmt="PNG")


# ============================================================================
# 1. API Happy Paths & Response Contract
# ============================================================================

class TestApiScanHappyPaths:
    """Verifies standard successful scanning workflows and contract compliance."""

    def test_health_check_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "1.0.0"

    def test_scan_single_image_glycomet_exact_match(self, app, client, sharp_image_bytes):
        # Configure orchestrator with Glycomet 500 PR mock preset
        mock_vis = MockVisionExtractor(default_preset=MockPreset.GLYCOMET_500_PR)
        mock_ocr = MockOCREngine(default_preset=MockOCRPreset.GLYCOMET_500_PR)
        orchestrator = ScanOrchestrator(
            vision_extractor=mock_vis,
            ocr_engine=mock_ocr,
        )
        app.dependency_overrides[get_scan_orchestrator] = lambda: orchestrator

        response = client.post(
            "/v1/scan",
            files=[("files", ("glycomet.png", sharp_image_bytes, "image/png"))],
            data={"lang": "en", "request_id": "req_glyc_001"},
            headers={"X-Request-ID": "corr_glyc_001"},
        )

        assert response.status_code == 200
        data = response.json()

        # Contract verification
        assert data["scan_id"] == "corr_glyc_001"
        assert response.headers["X-Request-ID"] == "corr_glyc_001"
        assert data["status"] == ScanWorkflowState.READY_FOR_MATCHING.value
        assert data["next_action"] == "ready_to_match"
        assert data["disclaimer"] == MANDATORY_DISCLAIMER
        assert data["extraction"] is not None
        assert data["extraction"]["brand_name"] == "Glycomet 500 PR"

        # Field confidence status classifications
        assert data["field_status"]["brand_name"] == "high"
        assert data["field_status"]["strength"] == "high"

        # Match result verification: deterministic EXACT match against Jan Aushadhi catalogue
        assert data["match_result"] is not None
        assert data["match_result"]["tier"] == MatchTier.EXACT.value
        assert len(data["match_result"]["matched_alternatives"]) > 0
        first_alt = data["match_result"]["matched_alternatives"][0]
        assert "Metformin" in first_alt["generic_name"]

    def test_scan_single_image_augmentin_ineligible_blocked(self, app, client, sharp_image_bytes):
        # Augmentin 625 Duo: perception succeeds, but candidate in catalogue has unverified release (ineligible)
        mock_vis = MockVisionExtractor(default_preset=MockPreset.AUGMENTIN_625_DUO)
        mock_ocr = MockOCREngine(default_preset=MockOCRPreset.AUGMENTIN_625_DUO)
        orchestrator = ScanOrchestrator(
            vision_extractor=mock_vis,
            ocr_engine=mock_ocr,
        )
        app.dependency_overrides[get_scan_orchestrator] = lambda: orchestrator

        response = client.post(
            "/v1/scan",
            files=[("files", ("augmentin.png", sharp_image_bytes, "image/png"))],
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == ScanWorkflowState.READY_FOR_MATCHING.value
        # Candidates resolved in catalogue
        assert len(data["candidate_products"]) > 0
        # Ineligible candidate strictly blocks EXACT matching
        assert data["match_result"]["tier"] == MatchTier.NONE.value
        assert len(data["match_result"]["matched_alternatives"]) == 0

    def test_scan_multi_image_concordant(self, app, client, sharp_image_bytes):
        mock_vis = MockVisionExtractor(default_preset=MockPreset.GLYCOMET_500_PR)
        mock_ocr = MockOCREngine(default_preset=MockOCRPreset.GLYCOMET_500_PR)
        orchestrator = ScanOrchestrator(
            vision_extractor=mock_vis,
            ocr_engine=mock_ocr,
        )
        app.dependency_overrides[get_scan_orchestrator] = lambda: orchestrator

        response = client.post(
            "/v1/scan",
            files=[
                ("files", ("front.png", sharp_image_bytes, "image/png")),
                ("files", ("back.png", sharp_image_bytes, "image/png")),
            ],
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == ScanWorkflowState.READY_FOR_MATCHING.value
        assert data["match_result"]["tier"] == MatchTier.EXACT.value


# ============================================================================
# 2. Input Validation, Edge Cases & Business Abstentions
# ============================================================================

class TestApiImageValidationAndErrorHandling:
    """Verifies edge case handling for invalid requests and visual defects."""

    def test_zero_images_rejected(self, client):
        response = client.post("/v1/scan", files=[])
        assert response.status_code == 422 or response.status_code == 400

    def test_exceeds_max_images_rejected(self, client, sharp_image_bytes):
        # 4 images uploaded (exceeds limit of 3)
        files = [("files", (f"img_{i}.png", sharp_image_bytes, "image/png")) for i in range(4)]
        response = client.post("/v1/scan", files=files)
        assert response.status_code == 400
        data = response.json()
        assert "Maximum 3 images" in data["detail"]
        assert data["code"] == "BAD_REQUEST"

    def test_unsupported_mime_type_rejected(self, client):
        response = client.post(
            "/v1/scan",
            files=[("files", ("doc.pdf", b"%PDF-1.4 mock pdf data", "application/pdf"))],
        )
        assert response.status_code == 400
        data = response.json()
        assert "unsupported MIME type" in data["detail"]

    def test_corrupt_bytes_rejected(self, client):
        response = client.post(
            "/v1/scan",
            files=[("files", ("corrupt.png", b"not-a-valid-image-bytes", "image/png"))],
        )
        assert response.status_code == 400
        data = response.json()
        assert data["code"] in ("INVALID_IMAGE", "BAD_REQUEST")

    def test_empty_file_rejected(self, client):
        response = client.post(
            "/v1/scan",
            files=[("files", ("empty.png", b"", "image/png"))],
        )
        assert response.status_code == 400
        data = response.json()
        assert "empty (0 bytes)" in data["detail"]

    def test_blurry_image_triggers_retake_required(self, app, client, blurry_image_bytes):
        # Business-level abstention: HTTP 200 with RETAKE_REQUIRED
        response = client.post(
            "/v1/scan",
            files=[("files", ("blurry.png", blurry_image_bytes, "image/png"))],
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == ScanWorkflowState.RETAKE_REQUIRED.value
        assert data["next_action"] == "retake"
        assert data["quality_report"]["passed"] is False
        assert data["quality_report"]["workflow_state"] == ScanWorkflowState.RETAKE_REQUIRED.value
        assert data["extraction"] is None
        assert data["match_result"] is None

    def test_non_medicine_image_rejected(self, app, client, sharp_image_bytes):
        mock_vis = MockVisionExtractor(default_preset=MockPreset.NON_MEDICINE)
        mock_ocr = MockOCREngine(default_preset=MockOCRPreset.NON_MEDICINE)
        orchestrator = ScanOrchestrator(
            vision_extractor=mock_vis,
            ocr_engine=mock_ocr,
        )
        app.dependency_overrides[get_scan_orchestrator] = lambda: orchestrator

        response = client.post(
            "/v1/scan",
            files=[("files", ("soap.png", sharp_image_bytes, "image/png"))],
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == ScanWorkflowState.REJECT_IMAGE.value
        assert data["next_action"] == "retake"
        assert data["match_result"] is None


# ============================================================================
# 3. Multi-Modal Evidence & Conflict Safety Gates
# ============================================================================

class TestApiMultiModalEvidenceAndConflictSafety:
    """Verifies that evidence discrepancies block EXACT matching."""

    def test_vision_ocr_strength_conflict_blocks_exact(self, app, client, sharp_image_bytes):
        # Vision read 500mg, but OCR detected 1000mg
        mock_vis = MockVisionExtractor(default_preset=MockPreset.GLYCOMET_500_PR)
        mock_ocr = MockOCREngine(default_preset=MockOCRPreset.GLYCOMET_1000_PR_CONFLICT)
        orchestrator = ScanOrchestrator(
            vision_extractor=mock_vis,
            ocr_engine=mock_ocr,
        )
        app.dependency_overrides[get_scan_orchestrator] = lambda: orchestrator

        response = client.post(
            "/v1/scan",
            files=[("files", ("glycomet.png", sharp_image_bytes, "image/png"))],
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == ScanWorkflowState.NEEDS_USER_CONFIRMATION.value
        assert data["next_action"] == "confirm_fields"

        # Match tier must be demoted to NONE, savings strictly blocked
        assert data["match_result"]["tier"] == MatchTier.NONE.value
        assert len(data["match_result"]["matched_alternatives"]) == 0
        assert data["field_status"]["strength"] == "unreadable"

    def test_vision_ocr_ingredient_conflict_blocks_exact(self, app, client, sharp_image_bytes):
        # Vision read combination, OCR detected single ingredient
        mock_vis = MockVisionExtractor(default_preset=MockPreset.AUGMENTIN_625_DUO)
        mock_ocr = MockOCREngine(default_preset=MockOCRPreset.AMOXI_ALONE_CONFLICT)
        orchestrator = ScanOrchestrator(
            vision_extractor=mock_vis,
            ocr_engine=mock_ocr,
        )
        app.dependency_overrides[get_scan_orchestrator] = lambda: orchestrator

        response = client.post(
            "/v1/scan",
            files=[("files", ("augmentin.png", sharp_image_bytes, "image/png"))],
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == ScanWorkflowState.NEEDS_USER_CONFIRMATION.value
        assert data["match_result"]["tier"] == MatchTier.NONE.value

    def test_ocr_unavailable_with_complete_vision_evidence(self, app, client, sharp_image_bytes):
        # Vision is complete, OCR is unavailable
        mock_vis = MockVisionExtractor(default_preset=MockPreset.GLYCOMET_500_PR)
        mock_ocr = MockOCREngine()
        mock_ocr.set_failure_mode("OCR engine offline")
        orchestrator = ScanOrchestrator(
            vision_extractor=mock_vis,
            ocr_engine=mock_ocr,
        )
        app.dependency_overrides[get_scan_orchestrator] = lambda: orchestrator

        response = client.post(
            "/v1/scan",
            files=[("files", ("glycomet.png", sharp_image_bytes, "image/png"))],
        )

        assert response.status_code == 200
        data = response.json()
        # Safe bypass permitted with warning
        assert data["status"] == ScanWorkflowState.READY_FOR_MATCHING.value
        assert any("unavailable" in w.lower() for w in data["warnings"])
        assert data["match_result"]["tier"] == MatchTier.EXACT.value

    def test_ocr_unavailable_with_incomplete_vision_evidence(self, app, client, sharp_image_bytes):
        # Vision has unreadable strength, OCR fails
        mock_vis = MockVisionExtractor(default_preset=MockPreset.UNREADABLE_STRENGTH)
        mock_ocr = MockOCREngine()
        mock_ocr.set_failure_mode("OCR engine offline")
        orchestrator = ScanOrchestrator(
            vision_extractor=mock_vis,
            ocr_engine=mock_ocr,
        )
        app.dependency_overrides[get_scan_orchestrator] = lambda: orchestrator

        response = client.post(
            "/v1/scan",
            files=[("files", ("incomplete.png", sharp_image_bytes, "image/png"))],
        )

        assert response.status_code == 200
        data = response.json()
        # Fails closed
        assert data["status"] == ScanWorkflowState.EXTRACTION_INCOMPLETE.value
        assert data["match_result"]["tier"] == MatchTier.NONE.value


# ============================================================================
# 4. Provider Failures & Transport Resilience
# ============================================================================

class TestApiFailureAndTimeoutResilience:
    """Verifies recovery behavior during external provider or database outages."""

    def test_vision_provider_timeout_handled(self, app, client, sharp_image_bytes):
        # Configure extractor with sleep to induce timeout
        class SleepyVisionExtractor(MockVisionExtractor):
            async def extract_async(self, images, request_id=None):
                await asyncio.sleep(0.2)
                return super().extract(images, request_id=request_id)

        mock_vis = SleepyVisionExtractor()
        orchestrator = ScanOrchestrator(
            vision_extractor=mock_vis,
            timeout_seconds=0.01,
        )
        app.dependency_overrides[get_scan_orchestrator] = lambda: orchestrator

        response = client.post(
            "/v1/scan",
            files=[("files", ("img.png", sharp_image_bytes, "image/png"))],
        )

        assert response.status_code == 504
        data = response.json()
        assert data["code"] == "VISION_TIMEOUT"
        assert data["disclaimer"] == MANDATORY_DISCLAIMER

    def test_vision_provider_malformed_or_error_handled(self, app, client, sharp_image_bytes):
        mock_vis = MockVisionExtractor()
        mock_vis.set_error_mode("VLM internal 500 error from upstream provider.")
        orchestrator = ScanOrchestrator(
            vision_extractor=mock_vis,
        )
        app.dependency_overrides[get_scan_orchestrator] = lambda: orchestrator

        response = client.post(
            "/v1/scan",
            files=[("files", ("img.png", sharp_image_bytes, "image/png"))],
        )

        assert response.status_code == 502
        data = response.json()
        assert data["code"] == "VISION_UNAVAILABLE"

    def test_database_failure_fails_safe_without_fabricated_results(self, app, client, sharp_image_bytes):
        # Configure resolver with an unreachable/broken SQLite database URL
        broken_resolver = CandidateResolver(db_url="sqlite:///./nonexistent_dir/broken.db")
        orchestrator = ScanOrchestrator(
            resolver=broken_resolver,
        )
        app.dependency_overrides[get_scan_orchestrator] = lambda: orchestrator

        response = client.post(
            "/v1/scan",
            files=[("files", ("img.png", sharp_image_bytes, "image/png"))],
        )

        # Fails safely with 503 Service Unavailable without returning fabricated savings
        assert response.status_code == 503
        data = response.json()
        assert data["code"] == "DATABASE_UNAVAILABLE"


# ============================================================================
# 5. Safety Invariants & Concurrency Isolation
# ============================================================================

class TestApiSafetyInvariantsAndDecoupling:
    """Rigorous verification of release blocker invariants."""

    def test_close_and_none_never_contain_savings(self, app, client, sharp_image_bytes):
        # Configure an unknown medicine that has no exact equivalent
        custom_extraction = RawMedicineExtraction(
            is_medicine_pack=True,
            brand_name="NovelExperimentalMed 100",
            printed_composition=[
                PrintedCompositionItem(salt_text="RareMolecule", strength_value=100.0, strength_unit="mg")
            ],
            dosage_form=DosageForm.TABLET,
            release_type=ReleaseType.IR,
        )
        mock_vis = MockVisionExtractor()
        mock_vis.queue_response(custom_extraction)
        orchestrator = ScanOrchestrator(vision_extractor=mock_vis)
        app.dependency_overrides[get_scan_orchestrator] = lambda: orchestrator

        response = client.post(
            "/v1/scan",
            files=[("files", ("rare.png", sharp_image_bytes, "image/png"))],
        )

        assert response.status_code == 200
        data = response.json()
        match_res = data["match_result"]
        assert match_res["tier"] == MatchTier.NONE.value
        # Invariant: Non-EXACT tier must never have savings
        for alt in match_res["matched_alternatives"]:
            assert alt["savings"] is None

    def test_no_raw_images_or_secrets_in_responses(self, app, client, sharp_image_bytes):
        mock_vis = MockVisionExtractor(default_preset=MockPreset.AUGMENTIN_625_DUO)
        orchestrator = ScanOrchestrator(vision_extractor=mock_vis)
        app.dependency_overrides[get_scan_orchestrator] = lambda: orchestrator

        response = client.post(
            "/v1/scan",
            files=[("files", ("test.png", sharp_image_bytes, "image/png"))],
        )
        text_resp = response.text
        # Assert raw image data byte marker is not echoed
        assert "PNG" not in text_resp[:50]
        assert "password" not in text_resp.lower()
        assert "api_key" not in text_resp.lower()

    def test_request_isolation_and_no_data_leakage_concurrent(self, app, client, sharp_image_bytes):
        """Proves that parallel requests with different correlation IDs and presets do not leak state."""
        presets = [
            (MockPreset.AUGMENTIN_625_DUO, "req_conc_001", "Augmentin 625 Duo"),
            (MockPreset.GLYCOMET_500_PR, "req_conc_002", "Glycomet 500 PR"),
            (MockPreset.AUGMENTIN_625_DUO, "req_conc_003", "Augmentin 625 Duo"),
            (MockPreset.GLYCOMET_500_PR, "req_conc_004", "Glycomet 500 PR"),
        ]

        def send_request(preset, req_id, expected_brand):
            # Create isolated test client per thread
            thread_app = create_app()
            mock_v = MockVisionExtractor(default_preset=preset)
            mock_o = MockOCREngine(
                default_preset=MockOCRPreset.AUGMENTIN_625_DUO if "Augmentin" in expected_brand else MockOCRPreset.GLYCOMET_500_PR
            )
            orch = ScanOrchestrator(vision_extractor=mock_v, ocr_engine=mock_o)
            thread_app.dependency_overrides[get_scan_orchestrator] = lambda: orch

            th_client = TestClient(thread_app)
            res = th_client.post(
                "/v1/scan",
                files=[("files", ("img.png", sharp_image_bytes, "image/png"))],
                headers={"X-Request-ID": req_id},
            )
            return res.json(), req_id, expected_brand

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(send_request, p, r, b) for p, r, b in presets]
            results = [f.result() for f in futures]

        for data, expected_req_id, expected_brand in results:
            assert data["scan_id"] == expected_req_id
            assert data["extraction"]["brand_name"] == expected_brand
