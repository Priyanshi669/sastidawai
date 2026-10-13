"""FastAPI application factory, global middleware, and RFC 7807 error handlers."""

import logging
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ml.app.api.routes_scan import router as scan_router
from ml.pipeline.orchestrator import (
    DatabaseUnavailableError,
    VisionProviderError,
    VisionProviderTimeoutError,
)
from ml.schemas.api import ProblemDetails
from ml.schemas.matcher import MANDATORY_DISCLAIMER
from ml.vision.quality import ImageValidationError

logger = logging.getLogger("sastidawai.app")


def create_app() -> FastAPI:
    """Factory creating configured FastAPI application with safety gates and RFC 7807 error handling."""
    app = FastAPI(
        title="Sasti Dawai ML Perception & Matching API",
        version="1.0.0",
        description=(
            "AI medicine packaging extraction, multi-modal OCR cross-verification, "
            "and deterministic generic medicine equivalence matching. "
            "Strictly enforces clinical safety boundaries and mandatory medical disclaimers."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # 1. CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 2. RFC 7807 Error Handlers
    @app.exception_handler(ImageValidationError)
    async def image_validation_error_handler(request: Request, exc: ImageValidationError):
        problem = ProblemDetails(
            type="https://sastidawai.org/errors/invalid-image",
            title="Image Validation Error",
            status=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
            code="INVALID_IMAGE",
            instance=request.url.path,
            disclaimer=MANDATORY_DISCLAIMER,
        )
        return JSONResponse(
            status_code=problem.status,
            content=problem.model_dump(),
            media_type="application/problem+json",
        )

    @app.exception_handler(VisionProviderTimeoutError)
    async def vision_timeout_error_handler(request: Request, exc: VisionProviderTimeoutError):
        problem = ProblemDetails(
            type="https://sastidawai.org/errors/vision-timeout",
            title="Vision Provider Timeout",
            status=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc),
            code="VISION_TIMEOUT",
            instance=request.url.path,
            disclaimer=MANDATORY_DISCLAIMER,
        )
        return JSONResponse(
            status_code=problem.status,
            content=problem.model_dump(),
            media_type="application/problem+json",
        )

    @app.exception_handler(VisionProviderError)
    async def vision_provider_error_handler(request: Request, exc: VisionProviderError):
        problem = ProblemDetails(
            type="https://sastidawai.org/errors/vision-unavailable",
            title="Vision Provider Error",
            status=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
            code="VISION_UNAVAILABLE",
            instance=request.url.path,
            disclaimer=MANDATORY_DISCLAIMER,
        )
        return JSONResponse(
            status_code=problem.status,
            content=problem.model_dump(),
            media_type="application/problem+json",
        )

    @app.exception_handler(DatabaseUnavailableError)
    async def database_unavailable_error_handler(request: Request, exc: DatabaseUnavailableError):
        problem = ProblemDetails(
            type="https://sastidawai.org/errors/database-unavailable",
            title="Catalogue Service Unavailable",
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The generic catalogue database is currently unreachable; equivalence cannot be verified.",
            code="DATABASE_UNAVAILABLE",
            instance=request.url.path,
            disclaimer=MANDATORY_DISCLAIMER,
        )
        return JSONResponse(
            status_code=problem.status,
            content=problem.model_dump(),
            media_type="application/problem+json",
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        code_map = {
            400: "BAD_REQUEST",
            404: "NOT_FOUND",
            422: "UNPROCESSABLE_ENTITY",
            500: "INTERNAL_SERVER_ERROR",
        }
        code = code_map.get(exc.status_code, f"HTTP_{exc.status_code}")
        problem = ProblemDetails(
            type=f"https://sastidawai.org/errors/{code.lower().replace('_', '-')}",
            title=exc.detail if isinstance(exc.detail, str) else "HTTP Error",
            status=exc.status_code,
            detail=str(exc.detail),
            code=code,
            instance=request.url.path,
            disclaimer=MANDATORY_DISCLAIMER,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=problem.model_dump(),
            media_type="application/problem+json",
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled server exception during request %s: %s", request.url.path, str(exc))
        problem = ProblemDetails(
            type="https://sastidawai.org/errors/internal-server-error",
            title="Internal Server Error",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal server error occurred while processing the request.",
            code="INTERNAL_SERVER_ERROR",
            instance=request.url.path,
            disclaimer=MANDATORY_DISCLAIMER,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=problem.model_dump(),
            media_type="application/problem+json",
        )

    # 3. Routes
    @app.get("/health", tags=["health"], summary="Service liveness and version")
    async def health_check() -> Dict[str, Any]:
        return {
            "status": "ok",
            "version": "1.0.0",
            "service": "sastidawai-ml",
        }

    app.include_router(scan_router)

    return app


# Default ASGI application instance
app = create_app()
