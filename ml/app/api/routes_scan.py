"""API routes for medicine scanning and perception orchestration."""

import logging
from typing import List, Optional
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
    status,
)

from ml.app.dependencies import get_scan_orchestrator
from ml.pipeline.orchestrator import ScanOrchestrator
from ml.schemas.api import ProblemDetails, ScanResponse
from ml.vision.quality import ImageValidationError

logger = logging.getLogger("sastidawai.api.scan")

router = APIRouter(tags=["scan"])

SUPPORTED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/jpg",
    "application/octet-stream",  # Often sent by generic multipart clients
}


@router.post(
    "/v1/scan",
    response_model=ScanResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ProblemDetails, "description": "Invalid image count, format, or byte caps exceeded"},
        422: {"model": ProblemDetails, "description": "Unprocessable image content or malformed payload"},
        502: {"model": ProblemDetails, "description": "Vision provider failure"},
        503: {"model": ProblemDetails, "description": "Catalogue database unavailable"},
        504: {"model": ProblemDetails, "description": "Vision provider timeout"},
    },
    summary="Scan medicine packaging images and cross-verify with catalogue",
    description=(
        "Processes 1 to 3 images of a medicine strip/packaging. Evaluates image quality, "
        "extracts clinical attributes using vision perception, cross-verifies against OCR, "
        "and retrieves deterministic generic equivalents from the Jan Aushadhi catalogue. "
        "All responses contain the mandatory medical safety disclaimer."
    ),
)
async def scan_medicine(
    response: Response,
    files: List[UploadFile] = File(
        ...,
        description="1 to 3 medicine packaging images (JPEG, PNG, WEBP, max 10MB each)",
    ),
    lang: Optional[str] = Form(
        default="en",
        description="Optional language code (e.g. 'en', 'hi')",
    ),
    request_id: Optional[str] = Form(
        default=None,
        description="Optional client-generated request/correlation ID for idempotent retries",
    ),
    x_request_id: Optional[str] = Header(
        default=None,
        alias="X-Request-ID",
        description="Optional correlation ID header",
    ),
    orchestrator: ScanOrchestrator = Depends(get_scan_orchestrator),
) -> ScanResponse:
    """Accepts 1-3 images, executes full perception and safety pipeline, and returns ScanResponse."""
    # 1. Validate file count (1 to 3 images)
    if not files or len(files) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least 1 image file must be provided.",
        )
    if len(files) > orchestrator.max_image_count:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {orchestrator.max_image_count} images allowed per scan, received {len(files)}.",
        )

    # 2. Assign effective scan/correlation ID
    effective_scan_id = x_request_id or request_id or f"scan_{uuid.uuid4().hex[:12]}"

    # 3. Stream and validate bytes for each uploaded image
    images_bytes: List[bytes] = []
    total_bytes = 0

    for idx, upload_file in enumerate(files):
        # Validate claimed MIME type if provided
        content_type = (upload_file.content_type or "").lower().strip()
        if content_type and content_type not in SUPPORTED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"File '{upload_file.filename}' has unsupported MIME type '{content_type}'. "
                    "Supported formats: JPEG, PNG, WEBP."
                ),
            )

        # Read content with per-file byte limit check
        chunk = await upload_file.read(orchestrator.max_image_bytes + 1)
        if len(chunk) > orchestrator.max_image_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File '{upload_file.filename or f'image_{idx}'}' exceeds max size of {orchestrator.max_image_bytes} bytes.",
            )

        if len(chunk) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File '{upload_file.filename or f'image_{idx}'}' is empty (0 bytes).",
            )

        total_bytes += len(chunk)
        if total_bytes > orchestrator.max_batch_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Total upload batch exceeds max size of {orchestrator.max_batch_bytes} bytes.",
            )

        images_bytes.append(chunk)

    # 4. Execute end-to-end orchestration pipeline
    try:
        scan_result = await orchestrator.process_scan(
            images=images_bytes,
            scan_id=effective_scan_id,
            lang=lang or "en",
        )
    except ImageValidationError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )

    # 5. Populate correlation headers
    response.headers["X-Request-ID"] = scan_result.scan_id

    return scan_result
