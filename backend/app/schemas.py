from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Ingredient(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    strength: str = Field(min_length=1, max_length=100)


class MatchRequest(BaseModel):
    ingredients: list[Ingredient] = Field(min_length=1, max_length=20)
    dosage_form: str = Field(min_length=1, max_length=80)
    release_type: str = Field(min_length=1, max_length=40)
    route: str = Field(min_length=1, max_length=80)


class FeedbackRequest(BaseModel):
    scan_id: str = Field(min_length=1, max_length=80)
    field_name: str = Field(min_length=1, max_length=80)
    corrected_value: str = Field(min_length=1, max_length=500)


class SavingsRequest(BaseModel):
    product_id: str
    alternative_product_id: str
    units_per_day: float | None = Field(default=None, gt=0, le=100)


class BasketItem(BaseModel):
    product_id: str
    alternative_product_id: str
    units_per_day: float | None = Field(default=None, gt=0, le=100)


class BasketRequest(BaseModel):
    items: list[BasketItem] = Field(min_length=1, max_length=100)


class DataSource(BaseModel):
    name: str
    last_updated: str | None
    imported_at: str
    row_count: int
    sha256: str
    licence_notes: str
    etl_version: str


class DataSourceList(BaseModel):
    items: list[DataSource]


class VoiceIntent(str, Enum):
    SCAN_MEDICINE = "SCAN_MEDICINE"
    GET_COMPOSITION = "GET_COMPOSITION"
    CHECK_MATCH = "CHECK_MATCH"
    EXPLAIN_MISMATCH = "EXPLAIN_MISMATCH"
    GET_SAVINGS = "GET_SAVINGS"
    FIND_KENDRA = "FIND_KENDRA"
    READ_RESULT = "READ_RESULT"
    UNKNOWN = "UNKNOWN"


class VoiceExistingResult(BaseModel):
    model_config = {"extra": "forbid"}

    tier: Literal["EXACT", "CLOSE", "NONE"] | None = None
    reason_codes: list[str] = Field(default_factory=list, max_length=10)
    composition: list[str] = Field(default_factory=list, max_length=20)
    savings_status: Literal["available", "unavailable"] | None = None
    monthly_saving_inr: float | None = None
    kendra_status: Literal["available", "unavailable"] | None = None
    kendra_names: list[str] = Field(default_factory=list, max_length=20)


class VoiceIntentRequest(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}

    text: str = Field(min_length=1, max_length=1000)
    language: str = Field(default="en-IN", min_length=2, max_length=20)
    existing_result: VoiceExistingResult | None = None


class VoiceIntentResponse(BaseModel):
    intent: VoiceIntent
    language: str | None
    confidence: float | None = Field(default=None, ge=0, le=1)
    response_text: str


class VoiceTranscriptionResponse(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    language: str | None
    confidence: float | None = Field(default=None, ge=0, le=1)
    language_confidence: float | None = Field(default=None, ge=0, le=1)
    intent: VoiceIntent


class VoiceSpeakRequest(VoiceIntentRequest):
    pass


class VoiceSpeakResponse(BaseModel):
    text: str
    language: str
    status: Literal["spoken", "text_fallback"]
    audio_base64: str | None = None
    content_type: str | None = None
    error_code: str | None = None


class VoiceLanguagesResponse(BaseModel):
    provider: str
    configured: bool
    stt_model: str
    tts_model: str
    stt_languages: list[str]
    tts_languages: list[str]
    common_languages: list[str]


class ExtractionIngredient(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=200)
    strength: str | None = Field(default=None, max_length=100)


class ExtractionEvidence(BaseModel):
    """Untrusted ML/OCR evidence. It intentionally has no match tier or equivalence flag."""

    model_config = {"extra": "forbid"}

    is_medicine_pack: bool | None = None
    brand_name: str | None = Field(default=None, max_length=200)
    manufacturer: str | None = Field(default=None, max_length=200)
    ingredients: list[ExtractionIngredient] = Field(default_factory=list, max_length=20)
    dosage_form: str | None = Field(default=None, max_length=80)
    release_type: str | None = Field(default=None, max_length=40)
    route: str | None = Field(default=None, max_length=80)
    field_confidence: dict[str, float] = Field(default_factory=dict)


class ExplainabilityCheck(BaseModel):
    attribute: Literal["active_ingredient", "strength", "dosage_form", "release_type", "route"]
    status: Literal["MATCH", "MISMATCH", "UNKNOWN"]


class ExplainabilityResult(BaseModel):
    type: Literal["decision_trace"] = "decision_trace"
    summary: str
    checks: list[ExplainabilityCheck]
    reason_codes: list[str]


Tier = Literal["EXACT", "CLOSE", "NONE"]
