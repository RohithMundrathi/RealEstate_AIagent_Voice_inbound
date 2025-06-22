import time
import redis
import json
import platform
import contextlib
import threading
import logging
import uuid
import threading
from typing import Optional, Dict
from flask import Blueprint, request, Response, jsonify, make_response
from functools import wraps
from datetime import datetime
import signal
import sys
from contextlib import contextmanager
from app.utils.exceptions import SessionError, TranscriptionError, SlotFillingError
from app.core.services import SlotFillingService, CloudRunOptimizedService
from app.utils.sms_utils import send_sms
from app.core.models import UserSession
from app.config import Config

logger = logging.getLogger(__name__)

voice_agent = Blueprint("voice_agent", __name__)

config = Config()
GCS_BUCKET = "realestateinbound"
DLQ_KEY = "recording_failures_dlq"

# Redis connection with retry logic and health monitoring
class RedisManager:
    def __init__(self, config: Config):
        self.config = config
        self._pool = None
        self._redis = None
        self._initialize_connection()
    
    def _initialize_connection(self):
        """Initialize Redis connection with retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._pool = redis.ConnectionPool.from_url(
                    self.config.REDIS_URL,
                    max_connections=self.config.REDIS_MAX_CONNECTIONS,
                    retry_on_timeout=True,
                    socket_keepalive=True,
                    socket_keepalive_options={},
                    health_check_interval=30
                )
                self._redis = redis.Redis(
                    connection_pool=self._pool,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    decode_responses=False
                )
                # Test connection
                self._redis.ping()
                logger.info("Redis connection established successfully")
                break
            except Exception as e:
                logger.error(f"Redis connection attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    raise ConnectionError(f"Failed to connect to Redis after {max_retries} attempts")
                time.sleep(2 ** attempt)  # Exponential backoff
    
    @property
    def redis(self):
        """Get Redis client with health check"""
        try:
            self._redis.ping()
            return self._redis
        except Exception as e:
            logger.warning(f"Redis connection lost, reinitializing: {e}")
            self._initialize_connection()
            return self._redis
    
    def is_healthy(self) -> bool:
        """Check Redis health"""
        try:
            self._redis.ping()
            return True
        except Exception:
            return False

redis_manager = RedisManager(config)

# Audio URL templates
AUDIO_BASE_URL = f"https://storage.googleapis.com/{GCS_BUCKET}"
WELCOME_AUDIO = f"{AUDIO_BASE_URL}/WelcomeRealestateInbound.wav"
ERROR_AUDIO = f"{AUDIO_BASE_URL}/error_audio.wav"

# Decorator for error handling and monitoring
def handle_errors(error_response_func=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            start_time = time.time()
            try:
                result = f(*args, **kwargs)
                duration = time.time() - start_time
                logger.info(f"{f.__name__} completed in {duration:.3f}s")
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"{f.__name__} failed after {duration:.3f}s: {e}", exc_info=True)
                if error_response_func:
                    return error_response_func()
                raise
        return decorated_function
    return decorator

# Request timeout context manager
@contextlib.contextmanager
def request_timeout(seconds):
    if platform.system() == "Windows":
        # On Windows, signal.SIGALRM is not available, so we simulate
        timer = threading.Timer(seconds, lambda: (_ for _ in ()).throw(TimeoutError(f"Request timeout after {seconds} seconds")))
        timer.start()
        try:
            yield
        finally:
            timer.cancel()
    else:
        # On Linux/Unix, use SIGALRM
        import signal
        def timeout_handler(signum, frame):
            raise TimeoutError(f"Request timeout after {seconds} seconds")
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)


class SessionManager:
    """Production-ready session management with comprehensive error handling"""
    
    @staticmethod
    def get_session(session_id: str) -> Optional[UserSession]:
        """Get session data with validation and error handling"""
        if not session_id or len(session_id) > 100:  # Validate session ID
            raise SessionError("Invalid session ID")
        
        try:
            val = redis_manager.redis.get(f"session:{session_id}")
            if not val:
                return None
            
            session_data = UserSession.model_validate(json.loads(val))
            
            # Validate session hasn't expired
            if time.time() - session_data.last_interaction_time > config.SESSION_TIMEOUT:
                SessionManager.delete_session(session_id)
                return None
            
            # Check for too many interactions (potential abuse)
            if session_data.interaction_count > config.MAX_INTERACTIONS:
                logger.warning(f"Session {session_id} exceeded max interactions")
                SessionManager.delete_session(session_id)
                return None
                
            return session_data
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in session {session_id}: {e}")
            SessionManager.delete_session(session_id)
            return None
        except Exception as e:
            logger.error(f"Error retrieving session {session_id}: {e}")
            return None

    @staticmethod
    def save_session(session_id: str, data: UserSession) -> bool:
        """Save session with validation and error handling"""
        if not session_id or not data:
            return False
        
        try:
            # Validate data before saving
            if not hasattr(data, 'session_id') or data.session_id != session_id:
                raise SessionError("Session ID mismatch")
            
            redis_manager.redis.set(
                f"session:{session_id}",
                json.dumps(data.model_dump()),
                ex=config.SESSION_TIMEOUT
            )
            return True
        except Exception as e:
            logger.error(f"Error saving session {session_id}: {e}")
            return False
        
    @staticmethod
    def token_bucket(redis_client, user_key: str, limit: int, refill_interval: int) -> bool:
        """
        Advanced Redis token bucket implementation
        - limit: allowed requests in interval
        - refill_interval: window size (seconds)
        """
        now = int(time.time())
        redis_key = f"ratelimit:{user_key}"

        pipe = redis_client.pipeline()

        # Add timestamp to sorted set
        pipe.zadd(redis_key, {str(now): now})

        # Remove expired timestamps outside interval
        pipe.zremrangebyscore(redis_key, 0, now - refill_interval)

        # Count remaining tokens in window
        pipe.zcard(redis_key)

        # Set expiry for housekeeping
        pipe.expire(redis_key, refill_interval * 2)

        # Execute atomically
        _, _, count, _ = pipe.execute()

        # Allow if within limit
        if count > limit:
            return False
        return True

    @staticmethod
    def delete_session(session_id: str) -> bool:
        """Delete session with error handling"""
        try:
            redis_manager.redis.delete(f"session:{session_id}")
            logger.info(f"Session {session_id} deleted")
            return True
        except Exception as e:
            logger.error(f"Error deleting session {session_id}: {e}")
            return False

    @staticmethod
    def update_interaction(redis_key: str, session_data: UserSession) -> UserSession:
        """Safe atomic interaction update with Redis transaction"""
        # redis_key = f"session:{session_data.session_id}"

        with redis_manager.redis.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(redis_key)
                    raw_session = pipe.get(redis_key)
                    if not raw_session:
                        raise SessionError("Session expired")

                    current_data = json.loads(raw_session)
                    current_data["interaction_count"] += 1
                    current_data["last_interaction_time"] = time.time()

                    if current_data["interaction_count"] > config.MAX_INTERACTIONS:
                        pipe.unwatch()
                        SessionManager.delete_session(session_data.session_id)
                        raise SessionError("Maximum interactions exceeded")

                    pipe.multi()
                    pipe.set(redis_key, json.dumps(current_data), ex=config.SESSION_TIMEOUT)
                    pipe.execute()

                    # Also update local session_data object to keep it consistent in memory
                    session_data.interaction_count = current_data["interaction_count"]
                    session_data.last_interaction_time = current_data["last_interaction_time"]

                    return session_data

                except redis.WatchError:
                    logger.warning("Redis watch conflict. Retrying atomic update...")
                    time.sleep(0.1)


class ExomlGenerator:
    """Production Exoml generation with validation for Exotel Dynamic Webhook Control"""
    
    @staticmethod
    def _validate_url(url: str) -> bool:
        """Validate audio URL"""
        return url and (url.startswith('https://') or url.startswith('http://')) and len(url) < 500

    @staticmethod
    def create_play_record_response(audio_url: str, record_action_url: str, 
                                  recording_callback_url: str, max_length: int) -> dict:
        """Generate validated Exoml for play + record"""
        if not all([
            ExomlGenerator._validate_url(audio_url),
            ExomlGenerator._validate_url(record_action_url),
            ExomlGenerator._validate_url(recording_callback_url),
            1 <= max_length <= 3600  # Exotel supports up to 3600 seconds
        ]):
            raise ValueError("Invalid Exoml parameters")
        
        return {
            "Exoml": [
                {
                    "Play": {
                        "url": audio_url
                    }
                },
                {
                    "Record": {
                        "max_length": max_length,
                        "finish_on_key": "#",
                        "play_beep": True,
                        "timeout": 5,
                        "action": record_action_url,
                        "status_callback": recording_callback_url
                    }
                }
            ]
        }

    @staticmethod
    def create_play_hangup_response(audio_url: str) -> dict:
        """Generate validated Exoml for play + hangup"""
        if not ExomlGenerator._validate_url(audio_url):
            raise ValueError("Invalid audio URL")
        
        return {
            "Exoml": [
                {
                    "Play": {
                        "url": audio_url
                    }
                },
                {
                    "Hangup": {}
                }
            ]
        }

    @staticmethod
    def create_say_hangup_response(text: str, voice: str = "woman", language: str = "en") -> dict:
        """Generate Exoml for say + hangup"""
        return {
            "Exoml": [
                {
                    "Say": {
                        "text": text,
                        "voice": voice,
                        "language": language
                    }
                },
                {
                    "Hangup": {}
                }
            ]
        }

    @staticmethod
    def create_error_response() -> dict:
        """Generate error Exoml response"""
        return ExomlGenerator.create_say_hangup_response(
            "Sorry, we encountered an error. Please try again later."
        )

class AudioUrlBuilder:
    """Production audio URL management with caching and validation"""
    
    _url_cache = {}
    
    @staticmethod
    def get_slot_audio_url(slot_id, lang_code: str) -> str:
        """Get cached slot-specific audio URL"""
        # Validate inputs
        if not lang_code or len(lang_code) > 10:
            lang_code = "en"
        
        actual_id = slot_id.value if hasattr(slot_id, "value") else str(slot_id)
        cache_key = f"{actual_id}_{lang_code}"
        
        if cache_key not in AudioUrlBuilder._url_cache:
            url = f"{AUDIO_BASE_URL}/{actual_id}_{lang_code}.wav"
            AudioUrlBuilder._url_cache[cache_key] = url
        
        return AudioUrlBuilder._url_cache[cache_key]

    @staticmethod
    def get_confirmation_audio_url(lang_code: str) -> str:
        """Get cached confirmation audio URL"""
        if not lang_code or len(lang_code) > 10:
            lang_code = "en"
        
        cache_key = f"confirmation_{lang_code}"
        
        if cache_key not in AudioUrlBuilder._url_cache:
            url = f"{AUDIO_BASE_URL}/confirmation_{lang_code}.wav"
            AudioUrlBuilder._url_cache[cache_key] = url
        
        return AudioUrlBuilder._url_cache[cache_key]

def post_call_cleanup_async(slots_filled: Dict, virtual_number: str, user_mobile: str, lang_code: str):
    """Production async post-call cleanup with comprehensive error handling"""
    try:
        # Validate inputs
        if not slots_filled or not virtual_number or not user_mobile:
            logger.error("Invalid cleanup parameters")
            return

        if not slots_filled.get("rent_or_buy"):
            logger.info("User did not respond to rent/buy prompt. SMS will NOT be sent.")
            return

        # Process with timeout
        with request_timeout(30):
            summary_text = SlotFillingService.lead_info_text(slots_filled)
            custom_message = (
                f"Below is the Tenant requirements:\n"
                f"tenant mobile number: {user_mobile}\n"
                f"{summary_text}"
            )
            
            logger.info(f"Cleanup completed for {user_mobile}")
            
            # SMS sending (implement when ready)
            # try:
            #     sid, personal_number = send_sms(virtual_number, custom_message)
            #     logger.info(f"SMS sent: {sid}")
            # except Exception as e:
            #     logger.error(f"SMS failed: {e}")
            
    except TimeoutError:
        logger.error("Post-call cleanup timeout")
    except Exception as e:
        logger.error(f"Post-call cleanup error: {e}", exc_info=True)

# Health check with comprehensive monitoring
@voice_agent.route("/health")
@handle_errors()
def health_check():
    """Comprehensive health check"""
    health_status = {
        "status": "ok",
        "timestamp": time.time(),
        "version": "2.0-production-exotel",
        "checks": {}
    }
    
    # Redis health
    health_status["checks"]["redis"] = {
        "status": "ok" if redis_manager.is_healthy() else "error",
        "response_time": None
    }
    
    # Test Redis response time
    try:
        start = time.time()
        redis_manager.redis.ping()
        health_status["checks"]["redis"]["response_time"] = round((time.time() - start) * 1000, 2)
    except Exception as e:
        health_status["checks"]["redis"]["error"] = str(e)
        health_status["status"] = "degraded"
    
    return jsonify(health_status), 200 if health_status["status"] == "ok" else 503

@voice_agent.route("/")
def home():
    """Service information endpoint"""
    return jsonify({
        "service": "Multilingual AI Real Estate Voice Agent - Exotel",
        "version": "2.0-production-exotel",
        "status": "ready",
        "features": ["multi-language", "slot-filling", "redis-sessions", "error-recovery", "exotel-integration"]
    })

@voice_agent.route("/answer", methods=["POST", "GET"])
@handle_errors(lambda: jsonify(ExomlGenerator.create_error_response()))
def answer():
    """Handle incoming call from Exotel"""
    with request_timeout(config.REQUEST_TIMEOUT):
        # Validate Exotel request parameters
        user_mobile = request.values.get("From", "").strip()
        virtual_number = request.values.get("To", "").strip()
        call_sid = request.values.get("CallSid", "").strip()
        
        # Exotel specific parameters
        exotel_call_id = request.values.get("CallId", "").strip()
        exotel_app_id = request.values.get("AppId", "").strip()
        
        logger.info(f"Incoming call - From: {user_mobile}, To: {virtual_number}, CallSid: {call_sid}, ExotelCallId: {exotel_call_id}")

        # Rate limiting using token bucket
        limit = 5                 # Max requests
        refill_interval = 300     # 5 minute window

        try:
            allowed = SessionManager.token_bucket(redis_manager.redis, user_mobile, limit, refill_interval)
            if not allowed:
                logger.warning(f"Rate limit exceeded for {user_mobile}")
                return jsonify(ExomlGenerator.create_say_hangup_response(
                    "You have made too many calls recently. Please try again later."
                ))
        except Exception as e:
            logger.error(f"Rate limiting error: {e}")
            return jsonify(ExomlGenerator.create_error_response()), 429

        # Create session
        session_id = str(uuid.uuid4())
        session_data = UserSession(
            session_id=session_id,
            user_mobile=user_mobile,
            virtual_number=virtual_number,
            interaction_count=0,
            last_interaction_time=time.time(),
            slots_filled={},
            language='en',
            end_of_conversation=False,
        )

        if not SessionManager.save_session(session_id, session_data):
            raise SessionError("Failed to create session")

        # Build URLs with validation
        base_url = request.url_root.rstrip('/')
        if not base_url.startswith('https://'):
            logger.warning("Non-HTTPS base URL detected")
        
        record_action_url = f"{base_url}/process-recording?session_id={session_id}"
        recording_status_callback_url = f"{base_url}/recording-status?session_id={session_id}"
        
        logger.info(f"URLs - Audio: {WELCOME_AUDIO}, Action: {record_action_url}, Callback: {recording_status_callback_url}")

        # Generate Exoml response
        exoml_response = ExomlGenerator.create_play_record_response(
            WELCOME_AUDIO, record_action_url, recording_status_callback_url, config.MAX_RECORD_LENGTH
        )

        logger.info(f"New session: {session_id} ({user_mobile} -> {virtual_number})")
        return jsonify(exoml_response)
    
@voice_agent.route("/process-recording", methods=["POST", "GET"])
@handle_errors(lambda: jsonify(ExomlGenerator.create_error_response()))
def process_recording():
    with request_timeout(config.REQUEST_TIMEOUT):
        # Exotel parameters
        user_mobile = request.values.get("From", "").strip()
        virtual_number = request.values.get("To", "").strip()
        call_sid = request.values.get("CallSid", "").strip()
        exotel_call_id = request.values.get("CallId", "").strip()
        exotel_app_id = request.values.get("AppId", "").strip()

        logger.info(f"Incoming call - From: {user_mobile}, To: {virtual_number}, CallSid: {call_sid}, ExotelCallId: {exotel_call_id}, Exotelappid: {exotel_app_id}")

        # Recording parameters
        recording_url = (
            request.values.get("RecordingUrl", "").strip() or
            request.values.get("recording_url", "").strip() or
            request.values.get("RecordUrl", "").strip()
        )
        recording_duration = request.values.get("RecordingDuration", "0")
        recording_status = request.values.get("RecordingStatus", "")

        # DLQ handling if recording missing
        # if not recording_url or not recording_url.startswith('https://'):
        #     logger.warning(f"Recording failure for call {exotel_call_id}")
        #     dlq_payload = {
        #         "call_id": exotel_call_id,
        #         "user_mobile": user_mobile,
        #         "virtual_number": virtual_number,
        #         "timestamp": datetime.utcnow().isoformat() + "Z",
        #         "error": "Invalid or missing recording URL",
        #         "recording_url": recording_url
        #     }
        #     redis_manager.redis.lpush(DLQ_KEY, json.dumps(dlq_payload))
        #     return jsonify(ExomlGenerator.create_say_hangup_response(
        #         "Sorry, we could not process your response. Please try again."
        #     ))

        logger.info(f"Processing recording: {recording_url}")

        # Create session if not exists (first time)
        session_key = f"exotel:session:{exotel_call_id}"

        raw_session = redis_manager.redis.get(session_key)
        if raw_session:
            session_data = UserSession.model_validate(json.loads(raw_session))
        else:
            logger.info(f"Creating new session in else block")
            session_id = str(uuid.uuid4())
            session_data = UserSession(
                session_id=session_id,
                user_mobile=user_mobile,
                virtual_number=virtual_number,
                interaction_count=0,
                last_interaction_time=time.time(),
                slots_filled={},
                language='en',
                end_of_conversation=False,
            )
            redis_manager.redis.set(session_key, json.dumps(session_data.model_dump()), ex=config.SESSION_TIMEOUT)
            logger.info(f"Session created for call_id: {exotel_call_id}")
            return make_response('', 200)

        # # Update interaction count safely
        # try:
        #     session_data = SessionManager.update_interaction(session_key, session_data)
        # except SessionError as e:
        #     logger.warning(f"Session limit exceeded: {e}")
        #     redis_manager.redis.delete(session_key)
        #     return jsonify(ExomlGenerator.create_say_hangup_response(
        #         "Session limit exceeded. Please try again later."
        #     ))


        # # Transcription
        # try:
        #     transcription_result = CloudRunOptimizedService.transcribe_audio(recording_url, 12)
        #     if not transcription_result or not hasattr(transcription_result, 'text'):
        #         raise TranscriptionError("Invalid transcription result")

        #     session_data.language = getattr(transcription_result, "language", "en")
        #     logger.info(f"Transcript: {transcription_result.text[:100]}")
        # except Exception as e:
        #     logger.error(f"Transcription failed: {e}")
        #     return jsonify(ExomlGenerator.create_say_hangup_response(
        #         "Sorry, transcription failed."
        #     ))

        # # Slot Filling
        # try:
        #     filled_slots = SlotFillingService.extract_slots_with_llm(
        #         transcription_result.text,
        #         session_data.slots_filled,
        #         session_data.language
        #     )
        #     session_data.slots_filled.update(filled_slots)
        # except Exception as e:
        #     logger.error(f"Slot filling failed: {e}")
        #     return jsonify(ExomlGenerator.create_say_hangup_response(
        #         "Sorry, we encountered an error processing your response."
        #     ))

        # # Determine next slot
        # next_slot_id = SlotFillingService.next_missing_slot(session_data.slots_filled)
        # logger.info(f"Next slot: {next_slot_id}")

        # base_url = request.url_root.rstrip('/')
        # recording_callback_url = f"{base_url}/process-recording"

        # # Conversation logic
        # if next_slot_id:
        #     audio_url = AudioUrlBuilder.get_slot_audio_url(next_slot_id, session_data.language)
        #     exoml_response = ExomlGenerator.create_play_record_response(
        #         audio_url, recording_callback_url, None, config.MAX_RECORD_LENGTH
        #     )
        #     # Save updated session state
        #     redis_manager.redis.set(session_key, json.dumps(session_data.model_dump()), ex=config.SESSION_TIMEOUT)

        # else:
        #     audio_url = AudioUrlBuilder.get_confirmation_audio_url(session_data.language)
        #     exoml_response = ExomlGenerator.create_play_hangup_response(audio_url)
        #     logger.info(f"Call completed for session: {session_data.session_id}")
        #     redis_manager.redis.delete(session_key)

        # return jsonify(exoml_response)

    
@voice_agent.route("/dlq", methods=["GET"])
def dlq_inspect():
    """Inspect dead letter queue for failed recordings"""
    try:
        dlq_items = redis_manager.redis.lrange(DLQ_KEY, 0, 50)
        parsed = [json.loads(item) for item in dlq_items]
        return jsonify({
            "total_items": len(parsed),
            "items": parsed
        }), 200
    except Exception as e:
        logger.error(f"DLQ inspect failed: {e}")
        return jsonify({"error": "internal error"}), 500

@voice_agent.route("/recording-status", methods=["POST"])
@handle_errors()
def recording_status():
    """Handle recording status callbacks from Exotel"""
    try:
        # Exotel recording status parameters
        recording_url = (
            request.values.get("RecordingUrl", "").strip() or
            request.values.get("recording_url", "").strip()
        )
        session_id = request.values.get("session_id")
        recording_status = request.values.get("RecordingStatus", "")
        recording_duration = request.values.get("RecordingDuration", "0")
        call_sid = request.values.get("CallSid", "")
        
        logger.info(f"Recording status callback - Session: {session_id}, Status: {recording_status}, Duration: {recording_duration}s, URL: {recording_url}")

        if recording_status == "failed" or not recording_url:
            logger.warning(f"Recording failed for session {session_id}")
            # Could implement retry logic here if needed
            return jsonify({"status": "received", "action": "none"})

        # Log successful recording
        if recording_status == "completed":
            logger.info(f"Recording completed successfully for session {session_id}")

        return jsonify({"status": "received"})
        
    except Exception as e:
        logger.error(f"Recording status error: {e}")
        return jsonify({"error": "internal error"}), 500

# Graceful shutdown handler
def shutdown_handler(signum, frame):
    logger.info("Shutting down gracefully...")
    # Close Redis connections
    if redis_manager._redis:
        redis_manager._redis.close()
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)