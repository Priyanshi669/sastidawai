import os
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "backend/.env")


def configured_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    path = Path(value) if value else default
    return path if path.is_absolute() else ROOT / path


DATABASE_PATH = configured_path("DATABASE_PATH", ROOT / "backend/data/sasti_dawai.sqlite3")
CATALOGUE_CSV = configured_path("CATALOGUE_CSV", ROOT / "data/indian_pharmaceutical_products_clean.csv")
ALLOWED_ORIGINS = [item.strip() for item in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if item.strip()]
MAX_SCAN_BYTES = int(os.getenv("MAX_SCAN_BYTES", "10485760"))
SCAN_RATE_LIMIT = int(os.getenv("SCAN_RATE_LIMIT", "20"))
SCAN_RATE_WINDOW_SECONDS = int(os.getenv("SCAN_RATE_WINDOW_SECONDS", "60"))
VOICE_PROVIDER = os.getenv("VOICE_PROVIDER", "sarvam").strip().lower()
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "").strip()
SARVAM_STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v4").strip()
SARVAM_TTS_MODEL = os.getenv("SARVAM_TTS_MODEL", "bulbul:v4-flash").strip()
SARVAM_STT_MODE = os.getenv("SARVAM_STT_MODE", "codemix").strip()
VOICE_TIMEOUT_SECONDS = float(os.getenv("VOICE_TIMEOUT_SECONDS", "5"))
VOICE_MAX_AUDIO_SECONDS = int(os.getenv("VOICE_MAX_AUDIO_SECONDS", "15"))
VOICE_MAX_AUDIO_BYTES = int(os.getenv("VOICE_MAX_AUDIO_BYTES", "10485760"))
API_VERSION = "1.0.0"
