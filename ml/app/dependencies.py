"""Dependency injection and factory providers for the FastAPI application."""

from functools import lru_cache
import os
from typing import Optional

from ml.pipeline.orchestrator import ScanOrchestrator
from ml.resolver.candidates import CandidateResolver
from ml.vision.extractor import BaseVisionExtractor, MockVisionExtractor
from ml.vision.ocr import BaseOCREngine, MockOCREngine, TesseractOCREngine


class AppSettings:
    """Runtime application settings loaded from environment."""

    def __init__(self):
        self.app_env = os.getenv("APP_ENV", "development")
        self.model_version = os.getenv("MODEL_VERSION", "mock-vision-v1")
        self.db_url = os.getenv("DATABASE_URL", "sqlite:///./data/catalogue.db")
        self.request_timeout_seconds = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "15.0"))
        self.max_image_count = int(os.getenv("MAX_IMAGE_COUNT", "3"))
        self.max_image_bytes = int(os.getenv("MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
        self.max_batch_bytes = int(os.getenv("MAX_BATCH_BYTES", str(25 * 1024 * 1024)))
        self.max_concurrency = int(os.getenv("MAX_CONCURRENCY", "10"))


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Returns singleton application settings."""
    return AppSettings()


# Global reusable resolver instance to prevent rebuilding generic pool on each request
_cached_resolver: Optional[CandidateResolver] = None


def get_candidate_resolver() -> CandidateResolver:
    """Returns a shared CandidateResolver connected to the local catalogue SQLite database."""
    global _cached_resolver
    if _cached_resolver is None:
        settings = get_settings()
        _cached_resolver = CandidateResolver(db_url=settings.db_url)
    return _cached_resolver


def get_scan_orchestrator() -> ScanOrchestrator:
    """FastAPI dependency yielding a configured ScanOrchestrator."""
    settings = get_settings()
    resolver = get_candidate_resolver()

    # Determine default OCR engine
    tesseract = TesseractOCREngine()
    ocr_engine: BaseOCREngine = tesseract if tesseract.is_available() else MockOCREngine()

    return ScanOrchestrator(
        vision_extractor=MockVisionExtractor(),
        ocr_engine=ocr_engine,
        resolver=resolver,
        model_version=settings.model_version,
        max_image_count=settings.max_image_count,
        max_image_bytes=settings.max_image_bytes,
        max_batch_bytes=settings.max_batch_bytes,
        timeout_seconds=settings.request_timeout_seconds,
        concurrency_limit=settings.max_concurrency,
    )
