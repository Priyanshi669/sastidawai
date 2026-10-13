import base64
import logging
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import (
    ALLOWED_ORIGINS, API_VERSION, MAX_SCAN_BYTES, SCAN_RATE_LIMIT,
    SCAN_RATE_WINDOW_SECONDS, SARVAM_STT_MODEL, SARVAM_TTS_MODEL,
    VOICE_MAX_AUDIO_BYTES, VOICE_MAX_AUDIO_SECONDS, VOICE_PROVIDER,
)
from .db import connect, initialize, seed_catalogue
from .explainability import generic_explanation, make_decision_trace
from .ml.voice_provider import VoiceProviderError, get_voice_provider
from .schemas import (
    BasketRequest, DataSourceList, FeedbackRequest, MatchRequest, SavingsRequest,
    VoiceIntentRequest, VoiceIntentResponse, VoiceLanguagesResponse,
    VoiceSpeakRequest, VoiceSpeakResponse, VoiceTranscriptionResponse,
)
from .services import find_match, savings, search_products
from .voice import detect_intent, intent_response, validate_wav_duration
from .voice_provider_errors import VoiceInputError


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize()
    seed_catalogue()
    yield


app = FastAPI(title="Sasti Dawai API", version=API_VERSION,
              description="Catalogue search and medicine comparison API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=False,
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Request-ID"])
_scan_requests = defaultdict(deque)
logger = logging.getLogger("sasti_dawai.voice")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:100]
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        response = JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "The request could not be completed."}})
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = str(int((time.perf_counter() - started) * 1000))
    return response


def now():
    return datetime.now(timezone.utc).isoformat()


@app.get("/health", tags=["status"])
def health():
    return {"status": "ok"}


@app.get("/ready", tags=["status"])
def ready():
    try:
        with connect() as db:
            db.execute("SELECT 1").fetchone()
            count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        return {"status": "ready", "catalogue_products": count}
    except Exception:
        raise HTTPException(503, detail={"code": "database_unavailable", "message": "Required storage is unavailable."})


@app.post("/v1/scan", tags=["scan"])
async def scan(request: Request, image: UploadFile = File(...)):
    started = time.perf_counter()
    client = request.client.host if request.client else "unknown"
    stamp = time.monotonic()
    history = _scan_requests[client]
    while history and stamp - history[0] > SCAN_RATE_WINDOW_SECONDS:
        history.popleft()
    if len(history) >= SCAN_RATE_LIMIT:
        raise HTTPException(429, detail={"code": "rate_limited", "message": "Please try again later."})
    history.append(stamp)
    if image.content_type not in {"image/jpeg", "image/png", "image/webp", "image/heic"}:
        raise HTTPException(415, detail={"code": "unsupported_image", "message": "Upload a JPEG, PNG, WebP, or HEIC image."})
    content = await image.read(MAX_SCAN_BYTES + 1)
    if not content or len(content) > MAX_SCAN_BYTES:
        raise HTTPException(413, detail={"code": "invalid_image_size", "message": "Image is empty or exceeds the configured size limit."})
    scan_id = str(uuid.uuid4())
    # No extraction provider is configured. Discard image bytes and persist metadata only.
    with connect() as db:
        db.execute("INSERT INTO scans VALUES (?,?,?,?,?,?)", (scan_id, "unresolved", None, 0, "unconfigured", now()))
    return {"scan_id": scan_id, "status": "unresolved", "extraction": None, "field_status": {},
            "candidate_products": [], "explainability": None,
            "warnings": ["Image extraction is not configured; no medicine details were inferred."],
            "next_action": "manual_search", "model_version": None,
            "latency_ms": int((time.perf_counter() - started) * 1000)}


@app.post("/v1/scan/{scan_id}/confirm", tags=["scan"])
def confirm_scan(scan_id: str, fields: dict):
    with connect() as db:
        scan_row = db.execute("SELECT status FROM scans WHERE id=?", (scan_id,)).fetchone()
    if not scan_row:
        raise HTTPException(404, detail={"code": "scan_not_found", "message": "Scan was not found."})
    raise HTTPException(409, detail={"code": "scan_unresolved", "message": "This scan has no extracted fields to confirm. Use manual search."})


@app.post("/v1/match", tags=["catalogue"])
def match_products(payload: MatchRequest, request: Request):
    matches = find_match(payload)
    for result in matches:
        try:
            result["explainability"] = make_decision_trace(payload, result["product"], result["tier"]).model_dump()
        except Exception:
            logger.warning("explainability.generated", extra={"request_id": request.state.request_id, "outcome": "fallback"})
            result["explainability"] = generic_explanation()
    return {"matches": matches, "note": "A candidate result is not a declaration of therapeutic equivalence."}


def _voice_error(exc: VoiceProviderError | VoiceInputError):
    message = "The voice request could not be completed."
    if exc.code == "voice_provider_not_configured":
        message = "Voice service is not configured. You can continue with text or manual search."
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": message})


@app.post("/voice/transcribe", response_model=VoiceTranscriptionResponse, tags=["voice"])
async def voice_transcribe(
    request: Request,
    audio: UploadFile = File(...),
    language_code: str = Form(default="unknown"),
):
    provider = get_voice_provider()
    started = time.perf_counter()
    logger.info("voice.stt.started", extra={"request_id": request.state.request_id, "provider": VOICE_PROVIDER, "model": SARVAM_STT_MODEL})
    try:
        if audio.content_type not in {"audio/wav", "audio/x-wav", "audio/wave"}:
            raise VoiceInputError("voice_audio_format_unsupported", 415)
        content = await audio.read(VOICE_MAX_AUDIO_BYTES + 1)
        if not content or len(content) > VOICE_MAX_AUDIO_BYTES:
            raise VoiceInputError("voice_audio_size_invalid", 413)
        validate_wav_duration(content, VOICE_MAX_AUDIO_SECONDS)
        languages = provider.supported_languages()["stt"]
        if language_code != "unknown" and language_code not in languages:
            raise VoiceInputError("voice_language_unsupported", 422)
        result = await provider.speech_to_text(content, language_code)
        language = result.language_code or (language_code if language_code != "unknown" else None)
        intent = detect_intent(result.transcript)
        logger.info("voice.stt.completed", extra={
            "request_id": request.state.request_id, "provider": VOICE_PROVIDER, "model": SARVAM_STT_MODEL,
            "language": language, "intent": intent.value, "latency_ms": int((time.perf_counter() - started) * 1000),
        })
        return VoiceTranscriptionResponse(
            text=result.transcript[:1000], language=language, confidence=None,
            language_confidence=result.language_probability, intent=intent,
        )
    except (VoiceProviderError, VoiceInputError) as exc:
        logger.warning("voice.stt.failed", extra={"request_id": request.state.request_id, "provider": VOICE_PROVIDER, "error_code": exc.code,
                                                  "latency_ms": int((time.perf_counter() - started) * 1000)})
        raise _voice_error(exc) from None


@app.post("/voice/intent", response_model=VoiceIntentResponse, tags=["voice"])
def voice_intent(payload: VoiceIntentRequest, request: Request):
    response = intent_response(payload)
    logger.info("voice.intent.detected", extra={"request_id": request.state.request_id, "provider": "local", "language": response.language,
                                                  "intent": response.intent.value})
    return response


@app.post("/voice/speak", response_model=VoiceSpeakResponse, tags=["voice"])
async def voice_speak(payload: VoiceSpeakRequest, request: Request):
    reply = intent_response(payload)
    provider = get_voice_provider()
    started = time.perf_counter()
    logger.info("voice.tts.started", extra={"request_id": request.state.request_id, "provider": VOICE_PROVIDER, "model": SARVAM_TTS_MODEL,
                                              "language": payload.language, "intent": reply.intent.value})
    try:
        audio = await provider.text_to_speech(reply.response_text, payload.language)
        logger.info("voice.tts.completed", extra={"request_id": request.state.request_id, "provider": VOICE_PROVIDER, "model": SARVAM_TTS_MODEL,
                                                   "language": payload.language, "intent": reply.intent.value,
                                                   "latency_ms": int((time.perf_counter() - started) * 1000)})
        return VoiceSpeakResponse(text=reply.response_text, language=payload.language, status="spoken",
                                  audio_base64=base64.b64encode(audio).decode("ascii"), content_type="audio/wav")
    except VoiceProviderError as exc:
        logger.warning("voice.tts.failed", extra={"request_id": request.state.request_id, "provider": VOICE_PROVIDER, "error_code": exc.code,
                                                  "language": payload.language, "intent": reply.intent.value,
                                                  "latency_ms": int((time.perf_counter() - started) * 1000)})
        return VoiceSpeakResponse(text=reply.response_text, language=payload.language, status="text_fallback", error_code=exc.code)


@app.get("/voice/languages", response_model=VoiceLanguagesResponse, tags=["voice"])
def voice_languages():
    provider = get_voice_provider()
    supported = provider.supported_languages()
    stt_languages = supported["stt"]
    tts_languages = supported["tts"]
    return VoiceLanguagesResponse(
        provider=VOICE_PROVIDER, configured=provider.configured, stt_model=SARVAM_STT_MODEL,
        tts_model=SARVAM_TTS_MODEL, stt_languages=stt_languages, tts_languages=tts_languages,
        common_languages=[language for language in stt_languages if language in tts_languages],
    )


@app.get("/v1/search", tags=["catalogue"])
def search(q: str = Query(min_length=1, max_length=200), limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    items, total = search_products(q, limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.post("/v1/savings/estimate", tags=["savings"])
def estimate_savings(payload: SavingsRequest):
    return savings(payload.product_id, payload.alternative_product_id, payload.units_per_day)


@app.post("/v1/basket/summary", tags=["savings"])
def basket_summary(payload: BasketRequest):
    estimates = [savings(item.product_id, item.alternative_product_id, item.units_per_day) for item in payload.items]
    available = [item for item in estimates if item["status"] == "available"]
    return {"estimates": estimates, "total_monthly_saving_inr": round(sum(x.get("monthly_saving_inr", 0) for x in available), 2),
            "status": "complete" if len(available) == len(estimates) else "partial"}


@app.get("/v1/kendras/nearby", tags=["kendras"])
def nearby_kendras(pin_code: str | None = Query(None, pattern=r"^\d{6}$"), city: str | None = Query(None, max_length=100),
                   latitude: float | None = Query(None, ge=-90, le=90), longitude: float | None = Query(None, ge=-180, le=180),
                   limit: int = Query(20, ge=1, le=100)):
    if (latitude is None) != (longitude is None):
        raise HTTPException(422, detail={"code": "coordinates_incomplete", "message": "Provide both latitude and longitude."})
    return {"items": [], "total": 0, "status": "unavailable", "reason": "kendra_dataset_not_configured",
            "query": {"pin_code": pin_code, "city": city, "latitude": latitude, "longitude": longitude}, "limit": limit,
            "message": "No verified Kendra location dataset is configured."}


@app.post("/v1/feedback", tags=["feedback"])
def submit_feedback(payload: FeedbackRequest):
    with connect() as db:
        exists = db.execute("SELECT 1 FROM scans WHERE id=?", (payload.scan_id,)).fetchone()
        if not exists:
            raise HTTPException(404, detail={"code": "scan_not_found", "message": "Scan was not found."})
        cursor = db.execute("INSERT INTO feedback(scan_id,field_name,corrected_value,status,created_at) VALUES (?,?,?,'pending',?)",
                            (payload.scan_id, payload.field_name, payload.corrected_value, now()))
    return {"feedback_id": cursor.lastrowid, "status": "pending_review"}


@app.get("/v1/meta/data-sources", tags=["metadata"], response_model=DataSourceList)
def data_sources():
    with connect() as db:
        rows = db.execute("SELECT name,retrieved_at AS last_updated,imported_at,row_count,sha256,licence_notes,etl_version FROM data_sources ORDER BY id").fetchall()
    return {"items": [dict(row) for row in rows]}


@app.exception_handler(404)
async def not_found(_request: Request, _exc):
    return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "Resource was not found."}})


