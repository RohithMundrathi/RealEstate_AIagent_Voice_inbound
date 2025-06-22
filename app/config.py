import os
from dotenv import load_dotenv
import secrets

load_dotenv()

class Config:
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"
    TESTING = os.getenv("TESTING", "False").lower() == "true"
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENTTS_URL = os.getenv("OPENTTS_URL", "https://opentts-service-842014299446.us-central1.run.app/api/tts")
    WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small")
    MAX_RECORD_LENGTH = int(os.getenv("MAX_RECORD_LENGTH", "15"))
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
    TEMP_DIR = os.getenv("TEMP_DIR") or None
    MAX_INTERACTIONS = 16
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_BACKOFF = float(os.getenv("RETRY_BACKOFF", "1.5"))
    ASSEMBLYAI_API_KEY = os.environ.get("ASSEMBLYAI_API_KEY")
    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    REDIS_MAX_CONNECTIONS = int(os.environ.get("REDIS_MAX_CONNECTIONS", "20"))
    SESSION_TIMEOUT = int(os.environ.get("SESSION_TIMEOUT", "3600"))
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
    DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY")
