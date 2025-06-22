# import time
# import redis
# import json
# import os
# import logging
# import uuid
# import threading
# from flask import Response
# from flask import Blueprint, request, Response, jsonify
# from app.core.services import TranscriptionService, SlotFillingService
# from app.utils.sms_utils import send_sms
# from app.core.models import UserSession

# logger = logging.getLogger(__name__)

# voice_agent = Blueprint("voice_agent", __name__)

# REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
# rdb = redis.Redis.from_url(REDIS_URL)


# GCS_BUCKET = "realestateinbound"

# def post_call_cleanup(slots_filled, virtual_number, user_mobile, lang_code):
#     if slots_filled.get("rent_or_buy"):
#         summary_text = SlotFillingService.lead_info_text(slots_filled, lang_code)
#         custom_message = (
#             f"Below is the Tenant requirements:\n"
#             f"tenant mobile number: {user_mobile}\n"
#             f"{summary_text}"
#         )
#         print(custom_message)
#         logger.infor(f"Final message sending message: {custom_message}")
#     #     try:
#     #         sid, personal_number = send_sms(virtual_number, custom_message)
#     #         logger.info(f"Confirmation SMS sent from {virtual_number} to {personal_number}, SID: {sid}")
#     #     except Exception as e:
#     #         logger.error(f"Error sending SMS from {virtual_number} to {user_mobile}: {e}")
#     # else:
#     #     logger.info("User did not respond to rent/buy prompt. SMS will NOT be sent.")

# def get_session_data(session_id):
#     val = rdb.get(f"session:{session_id}")
#     if val is not None:
#         return UserSession.model_validate(json.loads(val))
#     return None

# def save_session_data(session_id, data):
#     # data must be a dict!
#     rdb.set(f"session:{session_id}", json.dumps(data.model_dump()), ex=3600)
#     logger.info(f"Saved session {session_id} to Redis.")

# def cleanup_session(session_id):
#     rdb.delete(f"session:{session_id}")
#     logger.info(f"Deleted session {session_id} from Redis.")


# @voice_agent.route("/health")
# def health_check():
#     return jsonify({"status": "ok"}), 200

# @voice_agent.route("/")
# def home():
#     return "Multilingual AI Real Estate Slot-filling Voice Agent - In-Memory Sessions"

# @voice_agent.route("/answer", methods=["GET", "POST"]) 
# def answer():  
#     try:
#         session_id = str(uuid.uuid4())
#         logger.info("Twilio Request Data: %s", request.form)
#         logger.info("From: %s", request.form.get('From'))
#         logger.info("To: %s", request.form.get('To'))
#         user_mobile = request.values.get("From")
#         virtual_number = request.values.get("To")
#         logger.info(f"Usernumber: {user_mobile}, Virtual: {virtual_number}")
#         session_data = UserSession(
#             session_id=session_id,
#             user_mobile=user_mobile,
#             virtual_number=virtual_number,
#             interaction_count=0,
#             last_interaction_time=time.time(),
#             slots_filled={},
#             language='en',
#             end_of_conversation=False,
#         )
#         save_session_data(session_id, session_data)
   

#         # Generate TTS audio and upload to GCS
#         try:
#             audio_url = "https://storage.googleapis.com/realestateinbound/WelcomeRealestateInbound.wav"
#         except Exception:
#             logger.error(f"Unable to find welcome audio wave file")
#             # Optionally: use a fallback static audio in GCS
#             audio_url = "https://storage.googleapis.com/realestateinbound/WelcomeRealestateInbound.wav"

#         record_action_url = f"{request.url_root.rstrip('/')}/stt-first?session_id={session_id}"
#         recording_status_callback_url = f"{request.url_root.rstrip('/')}/recording-status?session_id={session_id}"

#         twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
#         <Response>
#             <Play>{audio_url}</Play>
#             <Record maxLength="15" action="{record_action_url}" recordingStatusCallback="{recording_status_callback_url}" playBeep="true" />
#         </Response>"""

#         logger.info(f"New call session started: {session_id}")
#         return Response(twiml, mimetype="application/xml")

#     except Exception as e:
#         logger.error(f"Error in answer endpoint: {e}", exc_info=True)
#         return jsonify({"error": str(e)}), 500

# @voice_agent.route("/stt-first", methods=["GET", "POST"])
# def stt_first():
#     try:
#         session_id = request.args.get("session_id") or request.form.get("session_id")
#         session_data = get_session_data(session_id)
#         recording_url = request.args.get("RecordingUrl") or request.form.get("RecordingUrl")

#         # Session and recording validation
#         if not session_data or getattr(session_data, "end_of_conversation", False):
#             logger.info(f"Session {session_id} ended or does not exist.")
#             return Response(status=200)
#         if not recording_url:
#             logger.info("No recording URL detected; returning early.")
#             return Response(status=200)

#         # Update interaction count
#         session_data.interaction_count += 1
#         session_data.last_interaction_time = time.time()
#         save_session_data(session_id, session_data)

#         # --- Transcription Step ---
#         try:
#             result = TranscriptionService.transcribe_audio(recording_url)
#             logger.info(f"Transcription result: {result}")
#             lang_code = getattr(result, "language", "en")
#             session_data.language = lang_code
#             logger.info(f"user audio input: {getattr(result, 'text', '[no text]')}{getattr(result, 'language', 'en')}")        
#         except Exception as transcribe_err:
#             logger.error(f"Transcription failed: {transcribe_err}", exc_info=True)
#             error_audio_url = "https://storage.googleapis.com/realestateinbound/error_audio.wav"
#             error_twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
#             <Response>
#                 <Play>{error_audio_url}</Play>
#                 <Hangup/>
#             </Response>"""
#             return Response(error_twiml, mimetype="application/xml")

#         # --- Slot Filling ---
#         try:
#             filled = SlotFillingService.extract_slots_with_llm(
#                 result.text,
#                 session_data.slots_filled,
#                 lang_code
#             )
#             session_data.slots_filled.update(filled)
#             save_session_data(session_id, session_data)
#         except Exception as slotfill_err:
#             logger.error(f"Slot filling failed: {slotfill_err}", exc_info=True)
#             error_audio_url = "https://storage.googleapis.com/realestateinbound/error_audio.wav"
#             error_twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
#             <Response>
#                 <Play>{error_audio_url}</Play>
#                 <Hangup/>
#             </Response>"""
#             return Response(error_twiml, mimetype="application/xml")

#         # --- Next Slot Prompt or Confirmation ---
#         try:
#             next_slot_id = SlotFillingService.next_missing_slot(session_data.slots_filled)
#             logger.info(f"Next slot: {next_slot_id}")
#             if next_slot_id:
#                 audio_url = slot_audio_url(next_slot_id, lang_code)
#                 logger.info(f"Sending slot audio to Twilio: {audio_url}")
#                 record_action_url = f"{request.url_root.rstrip('/')}/stt-first?session_id={session_id}"
#                 recording_status_callback_url = f"{request.url_root.rstrip('/')}/recording-status?session_id={session_id}"
#                 twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
#                 <Response>
#                     <Play>{audio_url}</Play>
#                     <Record maxLength="12" action="{record_action_url}" recordingStatusCallback="{recording_status_callback_url}" playBeep="true" />
#                 </Response>"""
#             else:
#                 audio_url = confirmation_audio_url(lang_code)
#                 logger.info(f"Sending confirmation audio to Twilio: {audio_url}")
#                 twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
#                 <Response>
#                     <Play>{audio_url
#                     }</Play>
#                     <Hangup/>
#                 </Response>"""
#                 logger.info(f"Call completed. Collected data: {session_data.slots_filled}")
#                 threading.Thread(
#                     target=post_call_cleanup,
#                     args=(
#                         session_data.slots_filled,
#                         getattr(session_data, "virtual_number", ""),
#                         getattr(session_data, "user_mobile", ""),
#                         getattr(session_data, "language", "en"),
#                     ),
#                     daemon=True
#                 ).start()
#                 session_data.end_of_conversation = True
#                 cleanup_session(session_id)

#             return Response(twiml, mimetype="application/xml")
#         except Exception as prompt_err:
#             logger.error(f"Error preparing prompt or response: {prompt_err}", exc_info=True)
#             error_audio_url = "https://storage.googleapis.com/realestateinbound/error_audio.wav"
#             error_twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
#             <Response>
#                 <Play>{error_audio_url}</Play>
#                 <Hangup/>
#             </Response>"""
#             return Response(error_twiml, mimetype="application/xml")

#     except Exception as e:
#         logger.error(f"Unknown error in stt-first endpoint: {e}", exc_info=True)
#         error_audio_url = "https://storage.googleapis.com/realestateinbound/error_audio.wav"
#         error_twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
#         <Response>
#             <Play>{error_audio_url}</Play>
#             <Hangup/>
#         </Response>"""
#         return Response(error_twiml, mimetype="application/xml")
                
# @voice_agent.route("/recording-status", methods=["POST"])
# def recording_status():
#     try:
#         session_id = request.args.get("session_id") or request.form.get("session_id")
#         status = request.values.get("RecordingStatus")
#         recording_url = request.form.get("RecordingUrl") or request.args.get("RecordingUrl")
#         logger.info(f"Recording status callback for session {session_id}, status={status}, url={recording_url}")
#         return "", 200
#     except Exception as e:
#         logger.error(f"Error in recording-status: {e}")
#         return "", 500
    
# def slot_audio_url(slot_id, lang_code):
#     # Accepts Enum or string, returns correct filename
#     if hasattr(slot_id, "value"):
#         actual_id = slot_id.value
#     else:
#         actual_id = str(slot_id)
#     filename = f"{actual_id}_{lang_code}.wav"
#     return f"https://storage.googleapis.com/{GCS_BUCKET}/{filename}"


# def confirmation_audio_url(lang_code):
#     filename = f"confirmation_{lang_code}.wav"
#     return f"https://storage.googleapis.com/{GCS_BUCKET}/{filename}"


