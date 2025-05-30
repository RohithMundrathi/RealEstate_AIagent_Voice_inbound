# import os
# import logging
# import uuid
# from flask import Blueprint, request, url_for, Response, jsonify
# from app.core.services import TranscriptionService, SynthesisService, SlotFillingService
# from app.core.models import UserSession
# from flask import send_file
# import tempfile
# import time

# logger = logging.getLogger(__name__)

# voice_agent = Blueprint("voice_agent", __name__)

# # === In-memory session store ===
# _sessions = {}

# def get_session_data(session_id):
#     return _sessions.get(session_id)

# def save_session_data(session_id, data):
#     _sessions[session_id] = data

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
#         session_data = UserSession(session_id=session_id)
#         save_session_data(session_id, session_data)
#         audio_path = SynthesisService.synthesize_speech(
#             "Welcome! Please tell us about your rental or purchase requirement after the beep.",
#             "en"
#         )
#         audio_url = request.url_root.rstrip("/") + url_for(
#             "voice_agent.serve_audio",
#             filename=os.path.basename(audio_path)
#         )
#         plivo_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
#         <Response>
#             <Play>{audio_url}</Play>
#             <Record action="{request.url_root.rstrip('/')}/stt-first" maxLength="15" playBeep="true" recordSession="{session_id}"/>
#         </Response>"""
#         logger.info(f"New call session started: {session_id}")
#         return Response(plivo_xml, mimetype="application/xml")
#     except Exception as e:
#         logger.error(f"Error in answer endpoint: {e}")
#         error_audio_path = SynthesisService.synthesize_speech(
#             "We're sorry, but we're experiencing technical difficulties. Please try again later.",
#             "en"
#         )
#         error_audio_url = request.url_root.rstrip("/") + url_for(
#             "voice_agent.serve_audio",
#             filename=os.path.basename(error_audio_path)
#         )
#         error_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
#         <Response>
#             <Play>{error_audio_url}</Play>
#             <Hangup/>
#         </Response>"""
#         return Response(error_xml, mimetype="application/xml")

# @voice_agent.route("/stt-first", methods=["GET", "POST"])
# def stt_first():
#     try:
#         session_id = request.form.get("recordSession")
#         if not session_id:
#             raise ValueError("Missing session ID")
#         session_data = get_session_data(session_id)
#         if not session_data:
#             raise ValueError(f"Invalid session ID: {session_id}")
#         session_data.interaction_count += 1
#         session_data.last_interaction_time = time.time()
#         audio_url = request.form.get("RecordUrl")
#         if not audio_url:
#             raise ValueError("Missing audio URL")
#         if not audio_url.endswith(".wav"):
#             audio_url += ".wav"
#         result = TranscriptionService.transcribe_audio(audio_url)
#         lang_code = result.language
#         session_data.language = lang_code
#         filled = SlotFillingService.extract_slots_with_llm(
#             result.text,
#             session_data.slots_filled,
#             lang_code
#         )
#         session_data.slots_filled.update(filled)
#         save_session_data(session_id, session_data)
#         next_slot = SlotFillingService.next_missing_slot(session_data.slots_filled)
#         if next_slot:
#             next_prompt = SlotFillingService.get_prompt(next_slot, lang_code)
#             audio_path = SynthesisService.synthesize_speech(next_prompt, lang_code)
#             audio_url = request.url_root.rstrip("/") + url_for(
#                 "voice_agent.serve_audio",
#                 filename=os.path.basename(audio_path)
#             )
#             plivo_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
#             <Response>
#                 <Play>{audio_url}</Play>
#                 <Record action="{request.url_root.rstrip('/')}/stt-next" maxLength="12" playBeep="true" recordSession="{session_id}"/>
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
#             plivo_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
#             <Response>
#                 <Play>{audio_url}</Play>
#                 <Hangup/>
#             </Response>"""
#             logger.info(f"Call completed. Collected data: {session_data.slots_filled}")
#         return Response(plivo_xml, mimetype="application/xml")
#     except Exception as e:
#         logger.error(f"Error in stt-first endpoint: {e}")
#         error_audio_path = SynthesisService.synthesize_speech(
#             "We're sorry, but we're experiencing technical difficulties. Please try again later.",
#             "en"
#         )
#         error_audio_url = request.url_root.rstrip("/") + url_for(
#             "voice_agent.serve_audio",
#             filename=os.path.basename(error_audio_path)
#         )
#         error_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
#         <Response>
#             <Play>{error_audio_url}</Play>
#             <Hangup/>
#         </Response>"""
#         return Response(error_xml, mimetype="application/xml")

# @voice_agent.route("/stt-next", methods=["GET", "POST"])
# def stt_next():
#     try:
#         session_id = request.form.get("recordSession")
#         if not session_id:
#             raise ValueError("Missing session ID")
#         session_data = get_session_data(session_id)
#         if not session_data:
#             raise ValueError(f"Invalid session ID: {session_id}")
#         session_data.interaction_count += 1
#         session_data.last_interaction_time = time.time()
#         audio_url = request.form.get("RecordUrl")
#         if not audio_url:
#             raise ValueError("Missing audio URL")
#         if not audio_url.endswith(".wav"):
#             audio_url += ".wav"
#         lang_code = session_data.language
#         filled = session_data.slots_filled
#         result = TranscriptionService.transcribe_audio(audio_url)
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
#             audio_path = SynthesisService.synthesize_speech(next_prompt, lang_code)
#             audio_url = request.url_root.rstrip("/") + url_for(
#                 "voice_agent.serve_audio",
#                 filename=os.path.basename(audio_path)
#             )
#             plivo_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
#             <Response>
#                 <Play>{audio_url}</Play>
#                 <Record action="{request.url_root.rstrip('/')}/stt-next" maxLength="12" playBeep="true" recordSession="{session_id}"/>
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
#             plivo_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
#             <Response>
#                 <Play>{audio_url}</Play>
#                 <Hangup/>
#             </Response>"""
#             logger.info(f"Call completed. Collected data: {session_data.slots_filled}")
#         return Response(plivo_xml, mimetype="application/xml")
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
#         error_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
#         <Response>
#             <Play>{error_audio_url}</Play>
#             <Hangup/>
#         </Response>"""
#         return Response(error_xml, mimetype="application/xml")

# @voice_agent.route("/audio/<filename>")
# def serve_audio(filename):
#     path = os.path.join(tempfile.gettempdir(), filename)
#     return send_file(path, mimetype="audio/wav")
