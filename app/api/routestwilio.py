import os
import time
import logging
import uuid
import threading
from flask import Response
from flask import Blueprint, request, url_for, Response, jsonify, send_file, after_this_request, abort
from app.core.services import TranscriptionService, SynthesisService, SlotFillingService
from app.core.models import UserSession
import tempfile
from app.utils.sms_utils import send_sms
from werkzeug.exceptions import NotFound

logger = logging.getLogger(__name__)

voice_agent = Blueprint("voice_agent", __name__)

# === In-memory session store ===
_sessions = {}

def post_call_cleanup(slots_filled, virtual_number, user_mobile, lang_code):
    if slots_filled.get("rent_or_buy"):
        summary_text = SlotFillingService.lead_info_text(slots_filled, lang_code)
        custom_message = (
            f"Below is the Tenant requirements:\n"
            f"tenant mobile number: {user_mobile}\n"
            f"{summary_text}"
        )
        print(custom_message)
        try:
            sid, personal_number = send_sms(virtual_number, custom_message)
            logger.info(f"Confirmation SMS sent from {virtual_number} to {personal_number}, SID: {sid}")
        except Exception as e:
            logger.error(f"Error sending SMS from {virtual_number} to {user_mobile}: {e}")
    else:
        logger.info("User did not respond to rent/buy prompt. SMS will NOT be sent.")

def get_session_data(session_id):
    return _sessions.get(session_id)

def save_session_data(session_id, data):
    _sessions[session_id] = data
    print(f"Upadted session{_sessions}")

def cleanup_session(session_id):
    if session_id in _sessions:
        del _sessions[session_id]
# ===== ADDITIONAL HELPER FUNCTIONS (if needed) =====

# def get_session_data_thread_safe(session_id):
#     """Thread-safe version of get_session_data if using database."""
#     # If you're using a database, you might need special handling here
#     # For in-memory storage, the regular function should work fine
#     return get_session_data(session_id)


# def save_session_data_thread_safe(session_id, session_data):
#     """Thread-safe version of save_session_data if using database."""
#     # If you're using a database, you might need special handling here
#     # For in-memory storage, the regular function should work fine
#     return save_session_data(session_id, session_data)

@voice_agent.route("/health")
def health_check():
    return jsonify({"status": "ok"}), 200

@voice_agent.route("/")
def home():
    return "Multilingual AI Real Estate Slot-filling Voice Agent - In-Memory Sessions"

@voice_agent.route("/answer", methods=["GET", "POST"])
def answer():  
    try:
        session_id = str(uuid.uuid4())
        logger.info("Twilio Request Data: %s", request.form)
        logger.info("From: %s", request.form.get('From'))
        logger.info("To: %s", request.form.get('To'))
        user_mobile = request.values.get("From")
        virtual_number = request.values.get("To")
        logger.info(f"Usernumber: {user_mobile}, Virtual: {virtual_number}")    

        session_data = UserSession(session_id=session_id, user_mobile=user_mobile, virtual_number=virtual_number)
        # session_data = UserSession(session_id=session_id)
        save_session_data(session_id, session_data)
        
        try:
            audio_path = SynthesisService.synthesize_speech(
                "Welcome! Please tell us about your rental or purchase requirement after the beep.",
                "en"
            )
        except Exception as tts_err:
            logger.error(f"TTS failed in welcome: {tts_err}")
            # fallback to a static wav file or a minimal message
            audio_path = "/path/to/static_welcome.wav"

        if not audio_path or not os.path.isfile(audio_path):
            logger.error("Welcome audio file is missing or path invalid.")

        audio_url = request.url_root.rstrip("/") + url_for(
            "voice_agent.serve_audio",
            filename=os.path.basename(audio_path)
        )
        record_action_url = f"{request.url_root.rstrip('/')}/stt-first?session_id={session_id}"
        recording_status_callback_url = f"{request.url_root.rstrip('/')}/recording-status?session_id={session_id}"

        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Play>{audio_url}</Play>
            <Record maxLength="15" action="{record_action_url}" recordingStatusCallback="{recording_status_callback_url}" playBeep="true" />
        </Response>"""

        logger.info(f"New call session started: {session_id}")
        return Response(twiml, mimetype="application/xml")

    except Exception as e:
        logger.error(f"Error in answer endpoint: {e}", exc_info=True)

@voice_agent.route("/stt-first", methods=["GET", "POST"])
def stt_first():
    try:
        
        session_id = request.args.get("session_id") or request.form.get("session_id")
        session_data = get_session_data(session_id)
        recording_url = request.args.get("RecordingUrl") or request.form.get("RecordingUrl")
        if not session_data or session_data.end_of_conversation:
            logger.info(f"Session {session_id} is ended or does not exist. Returning 200.")
            return Response(status=200)
        if not recording_url:
            logger.info("No audio or empty recording detected; returning early.")
            return Response(status=200)
        
        session_data.interaction_count += 1
        session_data.last_interaction_time = time.time()
        
        # Save updated session data immediately
        save_session_data(session_id, session_data)

        result = TranscriptionService.transcribe_audio(recording_url)
        lang_code = result.language
        session_data.language = lang_code
        logger.info(f"user audio input: {result.text}")
        
        filled = SlotFillingService.extract_slots_with_llm(
            result.text,
            session_data.slots_filled,
            lang_code
        )
        session_data.slots_filled.update(filled)
        save_session_data(session_id, session_data)
        
        next_slot = SlotFillingService.next_missing_slot(session_data.slots_filled)
        if next_slot:
            next_prompt = SlotFillingService.get_prompt(next_slot, lang_code)
            logger.info(f"next slot to be filled: {next_prompt}")
            audio_path = SynthesisService.synthesize_speech(next_prompt, lang_code)
            audio_url = request.url_root.rstrip("/") + url_for(
                "voice_agent.serve_audio",
                filename=os.path.basename(audio_path)
            )
            # IMPORTANT: pass session_id as query again!
            record_action_url = f"{request.url_root.rstrip('/')}/stt-first?session_id={session_id}"
            recording_status_callback_url = f"{request.url_root.rstrip('/')}/recording-status?session_id={session_id}"
            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
            <Response>
                <Play>{audio_url}</Play>
                <Record maxLength="12" action="{record_action_url}" recordingStatusCallback="{recording_status_callback_url}" playBeep="true" />
            </Response>"""
        else:
            confirm_text = SlotFillingService.confirmation_text(
                session_data.slots_filled,
                lang_code
            )
            audio_path = SynthesisService.synthesize_speech(confirm_text, lang_code)
            audio_url = request.url_root.rstrip("/") + url_for(
                "voice_agent.serve_audio",
                filename=os.path.basename(audio_path)
            )
            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
            <Response>
                <Play>{audio_url}</Play>
                <Hangup/>
            </Response>"""
            logger.info(f"Call completed. Collected data: {session_data.slots_filled}")
            threading.Thread(
            target=post_call_cleanup,
            args=(session_data.slots_filled,session_data.virtual_number, 
                  session_data.user_mobile, session_data.language or "en"),
            daemon=True).start()
            session_data.end_of_conversation = True
            cleanup_session(session_id)
            
        return Response(twiml, mimetype="application/xml")
    except Exception as e:
        logger.error(f"Error in stt-first endpoint: {e}")
        error_audio_path = SynthesisService.synthesize_speech(
            "We're sorry, but we're experiencing technical difficulties. Please try again later.",
            "en"
        )
        error_audio_url = request.url_root.rstrip("/") + url_for(
            "voice_agent.serve_audio",
            filename=os.path.basename(error_audio_path)
        )
        error_twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Play>{error_audio_url}</Play>
            <Hangup/>
        </Response>"""
        session_data.end_of_conversation = True
        cleanup_session(session_id)
        return Response(error_twiml, mimetype="application/xml")

# @voice_agent.route("/stt-next", methods=["GET", "POST"])
# def stt_next():
#     try:
        
#         session_id = request.args.get("session_id") or request.form.get("session_id")
#         session_data = get_session_data(session_id)
#         recording_url = request.args.get("RecordingUrl") or request.form.get("RecordingUrl")
#         if not session_data or session_data.end_of_conversation:
#             logger.info(f"Session {session_id} is ended or does not exist. Returning 200.")
#             return Response(status=200)
#         if not recording_url:
#             logger.info("No audio or empty recording detected; returning early.")
#             return Response(status=200)
        
#         session_data.interaction_count += 1
#         session_data.last_interaction_time = time.time()
#         session_data.processing_complete = False
#         session_data.processing_error = None
        
#         # Save updated session data immediately
#         save_session_data(session_id, session_data)

#         if not recording_url:
#             raise ValueError("Missing recording URL")
        
#         lang_code = session_data.language
#         filled = session_data.slots_filled
        
#         result = TranscriptionService.transcribe_audio(recording_url)
#         logger.info(f"user audio input: {result.text}")
#         if not hasattr(session_data, "slot_retry_count"):
#             session_data.slot_retry_count = 0

#         # Check for silence or 'no spoken audio'
#         if (getattr(result, "error", None) and "no spoken audio" in result.error.lower()) \
#         or (not result.text or result.text.strip() == ""):

#             session_data.slot_retry_count += 1
#             save_session_data(session_id, session_data)  # Always save changes

#             if session_data.slot_retry_count > 2:
#                 twiml = """
#                 <Response>
#                     <Say>Sorry, we did not hear you. Please try again later. Goodbye!</Say>
#                     <Hangup/>
#                 </Response>
#                 """
#                 session_data.end_of_conversation = True
#                 cleanup_session(session_id)
#                 return Response(twiml, mimetype="application/xml")
#             else:
#                 twiml = """
#                 <Response>
#                     <Say>Sorry, we didn't catch that. Please repeat again?.</Say>
#                     <Record maxLength="12" action="/stt-next?session_id={session_id}" playBeep="true" />
#                 </Response>
#                 """
#                 return Response(twiml, mimetype="application/xml")

#         new_slots = SlotFillingService.extract_slots_with_llm(
#             result.text,
#             filled,
#             lang_code
#         )
#         filled.update(new_slots)
#         session_data.slots_filled = filled
#         save_session_data(session_id, session_data)
        
#         next_slot = SlotFillingService.next_missing_slot(filled)
#         if next_slot:
#             next_prompt = SlotFillingService.get_prompt(next_slot, lang_code)
#             logger.info(f"next slot to be filled: {next_prompt}")
#             audio_path = SynthesisService.synthesize_speech(next_prompt, lang_code)
#             audio_url = request.url_root.rstrip("/") + url_for(
#                 "voice_agent.serve_audio",
#                 filename=os.path.basename(audio_path)
#             )
#             # AGAIN: pass session_id in action query param
#             recording_status_callback_url = f"{request.url_root.rstrip('/')}/recording-status?session_id={session_id}"
#             record_action_url = f"{request.url_root.rstrip('/')}/stt-next?session_id={session_id}"
#             twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
#             <Response>
#                 <Play>{audio_url}</Play>
#                 <Record maxLength="12" action="{record_action_url}" recordingStatusCallback="{recording_status_callback_url}" playBeep="true" />
#             </Response>"""
#         else:
#             confirm_text = SlotFillingService.confirmation_text(
#                 session_data.slots_filled,
#                 lang_code
#             )
#             audio_path = SynthesisService.synthesize_speech(confirm_text, lang_code)
#             audio_url = request.url_root.rstrip("/") + url_for(
#                 "voice_agent.serve_audio",
#                 filename=os.path.basename(audio_path)
#             )
#             twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
#             <Response>
#             <Play>{audio_url}</Play>
#             <Pause length="2"/>
#             <Hangup/>
#             </Response>"""
#             logger.info(f"Sending confirmation TwiML: {twiml}")
#             logger.info(f"Call completed. Collected data: {session_data.slots_filled}")
#             session_data.end_of_conversation = True
#             threading.Thread(
#             target=post_call_cleanup,
#             args=(session_data.slots_filled,session_data.virtual_number, 
#                   session_data.user_mobile, session_data.language or "en"),
#             daemon=True).start()

#             cleanup_session(session_id)
#         return Response(twiml, mimetype="application/xml")
#     except Exception as e:
#         logger.error(f"Error in stt-next endpoint: {e}")
#         error_audio_path = SynthesisService.synthesize_speech(
#             "We're sorry, but we're experiencing technical difficulties. Please try again later.",
#             "en"
#         )
#         error_audio_url = request.url_root.rstrip("/") + url_for(
#             "voice_agent.serve_audio",
#             filename=os.path.basename(error_audio_path)
#         )
#         error_twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
#         <Response>
#             <Play>{error_audio_url}</Play>
#             <Hangup/>
#         </Response>"""
#         session_data.end_of_conversation = True
#         cleanup_session(session_id)
#         return Response(error_twiml, mimetype="application/xml")
                
@voice_agent.route("/recording-status", methods=["POST"])
def recording_status():
    try:
        session_id = request.args.get("session_id") or request.form.get("session_id")
        status = request.values.get("RecordingStatus")
        recording_url = request.form.get("RecordingUrl") or request.args.get("RecordingUrl")
        logger.info(f"Recording status callback for session {session_id}, status={status}, url={recording_url}")
        return "", 200
    except Exception as e:
        logger.error(f"Error in recording-status: {e}")
        return "", 500


@voice_agent.route("/audio/<filename>")
def serve_audio(filename):
    # Only allow base filename, stripping any path attempts
    filename = os.path.basename(filename)
    path = os.path.join(tempfile.gettempdir(), filename)
    
    if not os.path.isfile(path):
        # Return a proper 404 if file not found
        logger.error(f"Audio file not found: {path}")
        # return Response("<Response><Say>Audio file not found.</Say></Response>", mimetype="application/xml")
        abort(404, description="Audio file not found")

    # Optional: Clean up file after serving (recommended for temp files)
    @after_this_request
    def remove_file(response):
        try:
            logger.info(f"Removing audio file from {path} after send request to twilio audio file from TTS")
            os.remove(path)
        except Exception:
            pass  # Log this if needed
        return response

    return send_file(path, mimetype="audio/wav")

