from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from ..config import (
    SARVAM_API_KEY,
    SARVAM_STT_MODE,
    SARVAM_STT_MODEL,
    SARVAM_TTS_MODEL,
    VOICE_PROVIDER,
    VOICE_TIMEOUT_SECONDS,
)


SARVAM_BASE_URL = "https://api.sarvam.ai"
SARVAM_STT_LANGUAGES = [
    "as-IN", "bn-IN", "brx-IN", "doi-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN",
    "kok-IN", "ks-IN", "mai-IN", "ml-IN", "mni-IN", "mr-IN", "ne-IN", "od-IN",
    "pa-IN", "sa-IN", "sat-IN", "sd-IN", "ta-IN", "te-IN", "ur-IN",
]
SARVAM_TTS_LANGUAGES = ["bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN"]


class VoiceProviderError(Exception):
    def __init__(self, code: str, status_code: int = 502):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class ProviderTranscription(BaseModel):
    model_config = ConfigDict(extra="ignore")

    transcript: str
    language_code: str | None = None
    language_probability: float | None = None

    @field_validator("transcript")
    @classmethod
    def transcript_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty transcript")
        return value.strip()


class VoiceProvider(Protocol):
    @property
    def configured(self) -> bool: ...

    def supported_languages(self) -> dict[str, list[str]]: ...

    async def speech_to_text(self, audio: bytes, language: str) -> ProviderTranscription: ...

    async def text_to_speech(self, text: str, language: str) -> bytes: ...


class SarvamVoiceProvider:
    """Sarvam REST adapter. Provider credentials and wire formats stay inside this class."""

    def __init__(
        self,
        api_key: str | None = SARVAM_API_KEY,
        stt_model: str = SARVAM_STT_MODEL,
        tts_model: str = SARVAM_TTS_MODEL,
        stt_mode: str = SARVAM_STT_MODE,
        timeout_seconds: float = VOICE_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._api_key = api_key or ""
        self.stt_model = stt_model
        self.tts_model = tts_model
        self.stt_mode = stt_mode
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    @property
    def configured(self) -> bool:
        return VOICE_PROVIDER == "sarvam" and bool(self._api_key)

    def supported_languages(self) -> dict[str, list[str]]:
        stt = SARVAM_STT_LANGUAGES if self.stt_model in {"saaras:v3", "saaras:v4"} else []
        tts = SARVAM_TTS_LANGUAGES if self.tts_model in {"bulbul:v3", "bulbul:v4-flash"} else []
        return {"stt": list(stt), "tts": list(tts)}

    def _ensure_configured(self) -> None:
        if VOICE_PROVIDER != "sarvam":
            raise VoiceProviderError("voice_provider_not_supported", 503)
        if not self._api_key:
            raise VoiceProviderError("voice_provider_not_configured", 503)

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=SARVAM_BASE_URL,
            timeout=httpx.Timeout(self.timeout_seconds),
            transport=self._transport,
            headers={"api-subscription-key": self._api_key},
        )

    async def speech_to_text(self, audio: bytes, language: str) -> ProviderTranscription:
        self._ensure_configured()
        if self.stt_model not in {"saaras:v3", "saaras:v4"}:
            raise VoiceProviderError("voice_stt_model_unsupported", 503)
        if language != "unknown" and language not in self.supported_languages()["stt"]:
            raise VoiceProviderError("voice_language_unsupported", 422)
        try:
            async with await self._client() as client:
                response = await client.post(
                    "/speech-to-text",
                    data={"model": self.stt_model, "language_code": language, "mode": self.stt_mode},
                    files={"file": ("speech.wav", audio, "audio/wav")},
                )
            if response.is_error:
                raise VoiceProviderError("voice_provider_rejected_audio", 502)
            try:
                return ProviderTranscription.model_validate(response.json())
            except (ValueError, ValidationError):
                raise VoiceProviderError("voice_provider_invalid_response", 502) from None
        except httpx.TimeoutException:
            raise VoiceProviderError("voice_provider_timeout", 504) from None
        except httpx.RequestError:
            raise VoiceProviderError("voice_provider_unavailable", 503) from None

    async def text_to_speech(self, text: str, language: str) -> bytes:
        self._ensure_configured()
        if self.tts_model not in {"bulbul:v3", "bulbul:v4-flash"}:
            raise VoiceProviderError("voice_tts_model_unsupported", 503)
        if language not in self.supported_languages()["tts"]:
            raise VoiceProviderError("voice_language_unsupported", 422)
        try:
            async with await self._client() as client:
                response = await client.post(
                    "/text-to-speech",
                    json={"model": self.tts_model, "text": text, "language_code": language, "output_audio_codec": "wav"},
                )
            if response.is_error:
                raise VoiceProviderError("voice_provider_rejected_text", 502)
            try:
                payload = response.json()
                audio = payload["audios"][0]
                import base64
                return base64.b64decode(audio, validate=True)
            except (ValueError, KeyError, IndexError, TypeError):
                raise VoiceProviderError("voice_provider_invalid_response", 502) from None
        except httpx.TimeoutException:
            raise VoiceProviderError("voice_provider_timeout", 504) from None
        except httpx.RequestError:
            raise VoiceProviderError("voice_provider_unavailable", 503) from None


def get_voice_provider() -> VoiceProvider:
    if VOICE_PROVIDER == "sarvam":
        return SarvamVoiceProvider()
    return SarvamVoiceProvider(api_key="", stt_model="", tts_model="")
