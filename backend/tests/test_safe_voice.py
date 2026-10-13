import base64
import csv
import io
import wave

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import db, main
from backend.app.explainability import explanation_text, make_decision_trace
from backend.app.ml.voice_provider import SarvamVoiceProvider, VoiceProviderError
from backend.app.schemas import Ingredient, MatchRequest, VoiceExistingResult, VoiceIntent, VoiceIntentRequest
from backend.app.services import compare_product
from backend.app.voice import detect_intent, intent_response


def _wav(seconds=1):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 16000 * seconds)
    return output.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    source = tmp_path / "catalogue.csv"
    with source.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=[
            "product_id", "brand_name", "manufacturer", "dosage_form", "pack_size", "pack_unit",
            "price_inr", "is_discontinued", "active_ingredients", "packaging_raw",
        ])
        writer.writeheader()
        writer.writerow({
            "product_id": "test-1", "brand_name": "Paracetamol 650", "manufacturer": "Fixture", "dosage_form": "tablet",
            "pack_size": "10", "pack_unit": "strip", "price_inr": "20", "is_discontinued": "false",
            "active_ingredients": "[{'name': 'Paracetamol', 'strength': '650mg'}]", "packaging_raw": "strip of 10 tablets",
        })
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "test.sqlite3")
    monkeypatch.setattr(db, "CATALOGUE_CSV", source)
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_missing_sarvam_key_fails_closed():
    provider = SarvamVoiceProvider(api_key="")
    with pytest.raises(VoiceProviderError) as error:
        await provider.speech_to_text(_wav(), "en-IN")
    assert error.value.code == "voice_provider_not_configured"


@pytest.mark.asyncio
async def test_sarvam_stt_success_and_language_confidence():
    def handler(request):
        assert request.url.path == "/speech-to-text"
        assert request.headers["api-subscription-key"] == "test-secret"
        return httpx.Response(200, json={"transcript": "ye medicine ka salt kya hai", "language_code": "hi-IN", "language_probability": 0.91})

    provider = SarvamVoiceProvider(api_key="test-secret", transport=httpx.MockTransport(handler))
    result = await provider.speech_to_text(_wav(), "hi-IN")
    assert result.transcript == "ye medicine ka salt kya hai"
    assert result.language_code == "hi-IN"
    assert result.language_probability == 0.91


@pytest.mark.asyncio
async def test_sarvam_rejects_invalid_stt_response():
    provider = SarvamVoiceProvider(api_key="test-secret", transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"language_code": "hi-IN"})))
    with pytest.raises(VoiceProviderError) as error:
        await provider.speech_to_text(_wav(), "hi-IN")
    assert error.value.code == "voice_provider_invalid_response"


@pytest.mark.asyncio
async def test_sarvam_stt_provider_failure_is_safe():
    provider = SarvamVoiceProvider(api_key="test-secret", transport=httpx.MockTransport(lambda _: httpx.Response(503, text="secret-bearing provider body")))
    with pytest.raises(VoiceProviderError) as error:
        await provider.speech_to_text(_wav(), "hi-IN")
    assert error.value.code == "voice_provider_rejected_audio"
    assert "secret-bearing" not in str(error.value)


@pytest.mark.asyncio
async def test_sarvam_tts_success_and_failure():
    audio = base64.b64encode(b"wav-audio").decode("ascii")
    provider = SarvamVoiceProvider(api_key="test-secret", transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"audios": [audio]})))
    assert await provider.text_to_speech("Verified result", "en-IN") == b"wav-audio"

    failed = SarvamVoiceProvider(api_key="", transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    with pytest.raises(VoiceProviderError) as error:
        await failed.text_to_speech("Verified result", "en-IN")
    assert error.value.code == "voice_provider_not_configured"


def test_language_capabilities_are_model_specific():
    provider = SarvamVoiceProvider(api_key="")
    languages = provider.supported_languages()
    assert "hi-IN" in languages["stt"] and "hi-IN" in languages["tts"]
    assert "as-IN" in languages["stt"] and "as-IN" not in languages["tts"]
    assert SarvamVoiceProvider(stt_model="unknown", tts_model="unknown").supported_languages() == {"stt": [], "tts": []}


def test_intent_maps_supported_english_hindi_and_code_mix():
    assert detect_intent("Why is this not a match?") == VoiceIntent.EXPLAIN_MISMATCH
    assert detect_intent("ye medicine ka salt kya hai") == VoiceIntent.GET_COMPOSITION
    assert detect_intent("दवा की कितनी बचत") == VoiceIntent.GET_SAVINGS
    assert detect_intent("random question about health") == VoiceIntent.UNKNOWN


def test_medical_advice_is_unsupported():
    response = intent_response(VoiceIntentRequest(text="Should I stop taking this medicine?"))
    assert response.intent == VoiceIntent.UNKNOWN
    assert "doctor or pharmacist" in response.response_text


def test_voice_reads_existing_match_and_does_not_recalculate():
    payload = VoiceIntentRequest(text="Why is this not a match?", existing_result=VoiceExistingResult(tier="NONE", reason_codes=["release_type"]))
    response = intent_response(payload)
    assert response.intent == VoiceIntent.EXPLAIN_MISMATCH
    assert "release type" in response.response_text.lower()
    assert response.confidence is None


def test_voice_does_not_invent_savings_or_kendra():
    saving = intent_response(VoiceIntentRequest(text="How much can I save?", existing_result=VoiceExistingResult(savings_status="unavailable")))
    kendra = intent_response(VoiceIntentRequest(text="Find Jan Aushadhi near me", existing_result=VoiceExistingResult(kendra_status="unavailable")))
    assert "not available" in saving.response_text
    assert "No verified Kendra" in kendra.response_text


def test_voice_reports_only_current_match_tier():
    response = intent_response(VoiceIntentRequest(text="Is this a match?", existing_result=VoiceExistingResult(tier="NONE")))
    assert response.intent == VoiceIntent.CHECK_MATCH
    assert "NONE" in response.response_text
    assert "EXACT" not in response.response_text


def test_explainability_is_template_based_and_does_not_change_tier():
    request = MatchRequest(ingredients=[Ingredient(name="Paracetamol", strength="650mg")], dosage_form="tablet", release_type="IR", route="oral")
    product = {"ingredients": [{"name": "Paracetamol", "strength": "650mg"}], "dosage_form": "tablet", "release_type": "MR", "route": "oral"}
    tier, _ = compare_product(request, {**product, "brand_name": "Paracetamol"})
    trace = make_decision_trace(request, product, tier)
    assert tier == "CLOSE"
    assert "release_type" in trace.reason_codes
    assert explanation_text("NONE", ["release_type"], "hi-IN")


def test_explainability_has_generic_fallback():
    from backend.app.explainability import generic_explanation
    assert generic_explanation()["reason_codes"] == ["unknown"]


def test_existing_match_tiers_are_not_replaced():
    request = MatchRequest(ingredients=[Ingredient(name="Paracetamol", strength="650mg")], dosage_form="tablet", release_type="IR", route="oral")
    exact_product = {"ingredients": [{"name": "Paracetamol", "strength": "650mg"}], "dosage_form": "tablet", "release_type": "IR", "route": "oral", "brand_name": "Paracetamol"}
    close_product = {**exact_product, "release_type": "MR"}
    none_product = {**exact_product, "brand_name": "Unrelated", "ingredients": [{"name": "ZZZ", "strength": "1mg"}]}
    assert compare_product(request, exact_product)[0] == "EXACT"
    assert compare_product(request, close_product)[0] == "CLOSE"
    assert compare_product(request, none_product)[0] == "NONE"


def test_match_api_adds_trace_without_removing_existing_fields(client):
    response = client.post("/v1/match", json={
        "ingredients": [{"name": "Paracetamol", "strength": "650mg"}],
        "dosage_form": "tablet", "release_type": "IR", "route": "oral",
    })
    assert response.status_code == 200
    item = response.json()["matches"][0]
    assert {"tier", "product", "reasons", "explainability"} <= set(item)
    assert item["tier"] != "EXACT"
    assert item["explainability"]["type"] == "decision_trace"


def test_voice_api_unconfigured_falls_back_to_text(client, monkeypatch):
    monkeypatch.setattr(main, "get_voice_provider", lambda: SarvamVoiceProvider(api_key=""))
    response = client.post("/voice/speak", json={"text": "What is the salt?", "language": "en-IN"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "text_fallback"
    assert body["audio_base64"] is None
    assert body["error_code"] == "voice_provider_not_configured"


def test_voice_language_route_and_intent_route(client):
    languages = client.get("/voice/languages").json()
    assert "hi-IN" in languages["common_languages"]
    response = client.post("/voice/intent", json={"text": "How much can I save?", "existing_result": {"savings_status": "unavailable"}})
    assert response.status_code == 200
    assert response.json()["intent"] == "GET_SAVINGS"


def test_voice_transcribe_api_validates_wav_and_calls_provider(client, monkeypatch):
    handler = lambda _: httpx.Response(200, json={"transcript": "ye medicine ka salt kya hai", "language_code": "hi-IN", "language_probability": 0.88})
    provider = SarvamVoiceProvider(api_key="test-secret", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(main, "get_voice_provider", lambda: provider)
    response = client.post("/voice/transcribe", files={"audio": ("speech.wav", _wav(), "audio/wav")}, data={"language_code": "hi-IN"})
    assert response.status_code == 200
    assert response.json()["intent"] == "GET_COMPOSITION"
    assert response.json()["language_confidence"] == 0.88
    assert response.json()["confidence"] is None


def test_voice_transcribe_rejects_audio_over_duration(client):
    response = client.post("/voice/transcribe", files={"audio": ("speech.wav", _wav(16), "audio/wav")}, data={"language_code": "en-IN"})
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "voice_audio_duration_exceeded"
