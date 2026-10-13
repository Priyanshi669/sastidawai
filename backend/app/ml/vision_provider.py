from typing import Protocol

from ..schemas import ExtractionEvidence


class VisionProvider(Protocol):
    """Optional extraction adapter; returns evidence only, never a medicine decision."""

    async def extract(self, image: bytes, content_type: str) -> ExtractionEvidence: ...


class VisionProviderUnavailable(Exception):
    """Raised by a configured adapter when extraction cannot be completed safely."""
