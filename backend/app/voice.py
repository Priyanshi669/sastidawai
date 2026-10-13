import re
import wave
from io import BytesIO

from .explainability import explanation_text
from .schemas import VoiceExistingResult, VoiceIntent, VoiceIntentRequest, VoiceIntentResponse
from .voice_provider_errors import VoiceInputError


_UNSAFE_REQUEST = re.compile(
    r"\b(should i|can i|may i|do i need to)\s+(stop|start|take|change|switch|increase|decrease|continue)\b"
    r"|\b(stop taking|start taking|change my dose|how much should i take|what dose)\b"
    r"|दवा\s*(बंद|शुरू)\s*(करूं|करूँ|करु|करें|करना चाहिए)"
    r"|(?:दवा|गोली).{0,18}लेना चाहिए|खुराक.{0,18}(?:बताओ|कितनी|लेना चाहिए)|क्या यह दवा सुरक्षित है",
    re.IGNORECASE,
)


_INTENT_PHRASES = (
    (VoiceIntent.EXPLAIN_MISMATCH, ("why is this not a match", "why not a match", "explain mismatch", "why no match", "match kyun nahi", "match kyon nahi", "मेल क्यों नहीं", "मिलान क्यों नहीं")),
    (VoiceIntent.GET_SAVINGS, ("how much can i save", "how much will i save", "savings", "saving kitna", "kitna bachega", "kitni bachat", "कितनी बचत", "कितना बचाऊं")),
    (VoiceIntent.GET_COMPOSITION, ("what is the salt", "what are the salts", "composition", "active ingredient", "salt kya hai", "is mein kya hai", "इसमें क्या है", "सॉल्ट क्या है", "संघटन")),
    (VoiceIntent.FIND_KENDRA, ("find jan aushadhi", "find kendra", "nearby kendra", "kendra near me", "jan aushadhi near", "पास में केंद्र", "नजदीकी केंद्र")),
    (VoiceIntent.SCAN_MEDICINE, ("scan medicine", "scan this medicine", "scan dawa", "दवा स्कैन", "दवाई स्कैन")),
    (VoiceIntent.CHECK_MATCH, ("check match", "is this a match", "are these equivalent", "same medicine", "match hai", "क्या ये एक जैसी", "क्या यह मेल खाती")),
    (VoiceIntent.READ_RESULT, ("read result", "read the result", "tell me the result", "result batao", "परिणाम पढ़ो", "नतीजा बताओ")),
)


def detect_intent(text: str) -> VoiceIntent:
    normalized = " ".join(text.casefold().split())
    if _UNSAFE_REQUEST.search(normalized):
        return VoiceIntent.UNKNOWN
    for intent, phrases in _INTENT_PHRASES:
        if any(phrase in normalized for phrase in phrases):
            return intent
    return VoiceIntent.UNKNOWN


def validate_wav_duration(audio: bytes, max_seconds: int) -> None:
    try:
        with wave.open(BytesIO(audio), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            if frame_rate <= 0 or wav_file.getnframes() / frame_rate > max_seconds:
                raise VoiceInputError("voice_audio_duration_exceeded", 413)
            if wav_file.getnchannels() not in {1, 2}:
                raise VoiceInputError("voice_audio_invalid", 415)
    except VoiceInputError:
        raise
    except (wave.Error, EOFError, OSError, ZeroDivisionError):
        raise VoiceInputError("voice_audio_invalid", 415) from None


def _no_result(language: str) -> str:
    return "Please scan or select a medicine first." if not language.startswith("hi") else "कृपया पहले दवा स्कैन करें या चुनें।"


def response_for_intent(intent: VoiceIntent, language: str, result: VoiceExistingResult | None) -> str:
    hindi = language.startswith("hi")
    if intent == VoiceIntent.UNKNOWN:
        return (
            "I can't help with diagnosis, dosing, or starting, stopping, or changing medicine. "
            "I can read catalogue results, explain a match result, or help search. Confirm with your doctor or pharmacist."
            if not hindi else
            "मैं निदान, खुराक या दवा शुरू, बंद या बदलने की सलाह नहीं दे सकता। मैं कैटलॉग परिणाम पढ़ सकता हूँ या मिलान समझा सकता हूँ। अपने डॉक्टर या फार्मासिस्ट से पुष्टि करें।"
        )
    if intent == VoiceIntent.SCAN_MEDICINE:
        return "The scan endpoint is available, but image extraction is not configured yet." if not hindi else "स्कैन सुविधा उपलब्ध है, लेकिन दवा की तस्वीर से जानकारी निकालने की व्यवस्था अभी नहीं है।"
    if intent == VoiceIntent.FIND_KENDRA:
        if result and result.kendra_status == "available" and result.kendra_names:
            return ("Kendra results from the current search: " if not hindi else "मौजूदा खोज के केंद्र: ") + ", ".join(result.kendra_names)
        return "No verified Kendra locations are available in the current backend." if not hindi else "मौजूदा बैकएंड में सत्यापित केंद्रों की जानकारी उपलब्ध नहीं है।"
    if intent == VoiceIntent.GET_COMPOSITION:
        if not result or not result.composition:
            return _no_result(language)
        return ("Catalogue composition: " if not hindi else "कैटलॉग में दर्ज संघटन: ") + ", ".join(result.composition)
    if intent == VoiceIntent.GET_SAVINGS:
        if not result or result.savings_status != "available" or result.monthly_saving_inr is None:
            return "A verified monthly savings estimate is not available." if not hindi else "सत्यापित मासिक बचत का अनुमान उपलब्ध नहीं है।"
        amount = f"{result.monthly_saving_inr:g}"
        return f"The existing savings estimate is {amount} rupees per month. Confirm with your doctor or pharmacist." if not hindi else f"मौजूदा बचत अनुमान {amount} रुपये प्रति माह है। अपने डॉक्टर या फार्मासिस्ट से पुष्टि करें।"
    if intent == VoiceIntent.EXPLAIN_MISMATCH:
        if not result or result.tier is None:
            return _no_result(language)
        return explanation_text(result.tier, result.reason_codes, language)
    if intent == VoiceIntent.CHECK_MATCH:
        if not result or result.tier is None:
            return _no_result(language)
        if result.tier == "EXACT":
            return "The current deterministic result is EXACT. Confirm with your doctor or pharmacist." if not hindi else "मौजूदा निर्धारित परिणाम EXACT है। अपने डॉक्टर या फार्मासिस्ट से पुष्टि करें।"
        if result.tier == "CLOSE":
            return "The current result is CLOSE. It is a candidate, not a verified equivalent." if not hindi else "मौजूदा परिणाम CLOSE है। यह केवल संभावित विकल्प है, सत्यापित समकक्ष नहीं।"
        return "The current deterministic result is NONE; equivalence was not verified." if not hindi else "मौजूदा निर्धारित परिणाम NONE है; समकक्षता सत्यापित नहीं हुई।"
    if intent == VoiceIntent.READ_RESULT:
        if not result or result.tier is None:
            return _no_result(language)
        return response_for_intent(VoiceIntent.CHECK_MATCH, language, result)
    return _no_result(language)


def intent_response(request: VoiceIntentRequest) -> VoiceIntentResponse:
    intent = detect_intent(request.text)
    return VoiceIntentResponse(
        intent=intent,
        language=request.language,
        confidence=None,
        response_text=response_for_intent(intent, request.language, request.existing_result),
    )
