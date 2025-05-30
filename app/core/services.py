import time
import os
from pathlib import Path
import json
import time
import logging
import shutil
import assemblyai as aai
import whisper
import openai
import requests
from openai import OpenAI, APIError
from func_timeout import func_timeout, FunctionTimedOut
from typing import Dict, Optional
from langdetect import detect
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.config import Config
from app.core.models import SlotSchema, VoiceMapping, TranscriptionResult
from app.utils.exceptions import TranscriptionError, SynthesisError, SlotFillingError, APIConnectionError
from app.utils.audio import temp_audio_file, download_audio
import tempfile
from app.utils.audio import download_with_retry
from pydub import AudioSegment
from io import BytesIO

logger = logging.getLogger(__name__)
client = openai.OpenAI(api_key="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") 

_whisper_model = None
_slot_schema = SlotSchema()
_voice_mapping = VoiceMapping()

# def foo():
#     temp_dir = Path(os.path.dirname(__file__))
#     print("Temp dir:", temp_dir)
# foo()
# print("DEBUG: Path is", Path)
# print(shutil.which("ffmpeg"),shutil.which("ffprobe"))
# def get_whisper_model():
#     global _whisper_model
#     if _whisper_model is None:
#         logger.info(f"Loading Whisper model: {Config.WHISPER_MODEL_SIZE}")
#         _whisper_model = whisper.load_model(Config.WHISPER_MODEL_SIZE)
#     return _whisper_model

# class TranscriptionService:
#     _model = None  # Class-level model cache

#     @classmethod
#     def get_model(cls):
#         if cls._model is None:
#             logger.info("Loading Whisper model")
#             import whisper  # Lazy import
#             cls._model = whisper.load_model("small")
#         return cls._model

#     @staticmethod
#     def transcribe_audio(audio_url: str) -> 'TranscriptionResult':
#         try:
#             logger.info(f"Downloading audio from {audio_url}")
#             audio_data = download_with_retry(
#                 audio_url,
#                 max_retries=5,
#                 initial_delay=2.0,
#                 backoff_factor=2
#             )

#             if not audio_data or len(audio_data) < 100:
#                 raise TranscriptionError("Audio file is empty or too short")

#             # Create a persistent temp file path
#             temp_dir = Path(tempfile.gettempdir())
#             audio_path = temp_dir / f"whisper_{os.getpid()}_{int(time.time())}.wav"

#             try:
#                 # Atomic write operation
#                 with open(audio_path, "wb") as f:
#                     f.write(audio_data)

#                 # Verify file was written
#                 if not audio_path.exists() or audio_path.stat().st_size < 100:
#                     raise TranscriptionError(f"Audio file not properly written (exists={audio_path.exists()}, size={audio_path.stat().st_size if audio_path.exists() else 0})")

#                 # logger.info(f"Audio ready for transcription at {audio_path} (size: {audio_path.stat().st_size} bytes)")
#                 # logger.info("ffmpeg found: %s", shutil.which("ffmpeg"))
#                 # logger.info("ffprobe found: %s", shutil.which("ffprobe"))

#                 model = get_whisper_model()
#                 abs_path = str(audio_path.resolve())
#                 logger.info(f"Passing absolute path to Whisper: {abs_path}")

#                 try:
#                     result = func_timeout(
#                         30,
#                         model.transcribe,
#                         args=(abs_path,)
#                     )
#                 except FunctionTimedOut:
#                     raise TranscriptionError("Transcription timeout")

#                 # Process results
#                 text = result.get("text", "").strip()
#                 lang = result.get("language", "en").lower()

#                 # Language detection fallback
#                 mapping = getattr(_voice_mapping, "__dict__", _voice_mapping)
#                 if not lang or lang not in mapping:
#                     try:
#                         lang = detect(text[:500])
#                         logger.info(f"Detected language: {lang}")
#                     except Exception as e:
#                         logger.warning(f"Language detection fallback failed: {e}")
#                         lang = "en"

#                 logger.info(f"Transcription successful: '{text[:50]}...' (lang: {lang})")
#                 return TranscriptionResult(
#                     text=text,
#                     language=lang,
#                     confidence=result.get("confidence", 0.0)
#                 )

#             finally:
#                 # Clean up the temp file
#                 try:
#                     if audio_path.exists():
#                         audio_path.unlink()
#                         logger.info(f"Deleted temp file: {audio_path}")
#                 except Exception as e:
#                     logger.warning(f"Could not delete temp file: {e}")

#         except Exception as e:
#             logger.error(f"Transcription pipeline failed: {str(e)}", exc_info=True)
#             raise TranscriptionError(original_error=str(e))

class TranscriptionService:
    @staticmethod
    def transcribe_audio(audio_url: str) -> 'TranscriptionResult':
        try:
            # 1. Set up AssemblyAI API key
            api_key = getattr(Config, "ASSEMBLYAI_API_KEY", None)
            if not api_key:
                raise ValueError("ASSEMBLYAI_API_KEY is not set in Config")
            
            aai.settings.api_key = api_key
            
            # 2. Create transcriber with configuration
            config = aai.TranscriptionConfig(
                language_detection=True,
                punctuate=True,
                format_text=True,
                word_boost = ["aws", "azure", "google cloud"],
                boost_param = "high",
            )
            
            transcriber = aai.Transcriber(config=config)
            
            # 3. Transcribe directly from URL (if AssemblyAI can access it)
            logger.info(f"Starting direct URL transcription of {audio_url}")
            transcript = transcriber.transcribe(audio_url)
            
            # 4. Check transcription status
            if transcript.status == aai.TranscriptStatus.error:
                raise TranscriptionError(f"Transcription failed: {transcript.error}")
            
            text = transcript.text.strip() if transcript.text else ""
            if not text:
                raise TranscriptionError("Transcription returned empty text")
            
            # Get detected language
            detected_language = getattr(transcript, 'language_code', 'en')
            lang = detected_language.lower() if detected_language else "en"
            
            logger.info(f"Direct URL transcription successful: '{text[:50]}...' (lang: {lang})")
            
            return TranscriptionResult(
                text=text,
                language=lang,
                confidence=getattr(transcript, 'confidence', 1.0)
            )
            
        except Exception as e:
            logger.error(f"Direct URL transcription failed: {str(e)}")
            # Fallback to download and upload method
            logger.info("Falling back to download and upload method")
            return TranscriptionService.transcribe_audio(audio_url)


class SynthesisService:
    @staticmethod
    @retry(stop=stop_after_attempt(Config.MAX_RETRIES),
           wait=wait_exponential(multiplier=1, min=1, max=10),
           retry=retry_if_exception_type(APIConnectionError))
    def slow_down_audio(audio_bytes, speed=0.9):
        audio = AudioSegment.from_file(BytesIO(audio_bytes), format="wav")
        slowed = audio._spawn(audio.raw_data, overrides={
            "frame_rate": int(audio.frame_rate * speed)
        }).set_frame_rate(audio.frame_rate)
        output = BytesIO()
        slowed.export(output, format="wav")
        return output.getvalue()

    @staticmethod
    def synthesize_speech(text: str, lang_code: str) -> str:
        try:
            voice = getattr(_voice_mapping, lang_code, _voice_mapping.en)
            logger.info(f"Synthesizing speech in {lang_code} using voice {voice}")
            
            # Make request to OpenTTS
            params = {"text": text, "voice": voice, "ssml": "false", "rate": "0.90"}
            resp = requests.get(Config.OPENTTS_URL, params=params, timeout=Config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            
            # Slow down audio
            slowed_audio = SynthesisService.slow_down_audio(resp.content, speed=0.9)

            # Create temporary file and save audio
            with temp_audio_file() as audio_path:
                with open(audio_path, "wb") as f:
                    f.write(slowed_audio)
                
                # Create persistent file
                persistent_path = os.path.join(
                    tempfile.gettempdir(),
                    f"tts_{int(time.time())}_{os.path.basename(audio_path)}"
                )
                
                # Copy to persistent location
                with open(audio_path, "rb") as src, open(persistent_path, "wb") as dst:
                    dst.write(src.read())
                
                logger.info(f"Speech synthesized and saved to {persistent_path}")

                # Ensure Twilio compatible encoding
                try:
                    audio = AudioSegment.from_file(persistent_path)
                    
                    # Check if conversion is needed
                    if audio.frame_rate != 8000 or audio.channels != 1:
                        logger.info(f"Converting {persistent_path} to 8kHz mono for Twilio...")
                        twilio_safe_path = persistent_path.replace(".wav", "_twilio.wav")
                        audio = audio.set_frame_rate(8000).set_channels(1).set_sample_width(2)
                        audio.export(twilio_safe_path, format="wav")
                        logger.info(f"Converted and saved Twilio-safe audio: {twilio_safe_path}")
                        
                        # Clean up original file if conversion successful
                        try:
                            os.remove(persistent_path)
                            logger.info(f"Removed original file: {persistent_path}")
                        except Exception as cleanup_err:
                            logger.warning(f"Could not remove original file {persistent_path}: {cleanup_err}")
                        
                        return twilio_safe_path
                    else:
                        logger.info(f"Audio already 8kHz mono, no conversion needed: {persistent_path}")
                        return persistent_path
                        
                except Exception as conv_err:
                    logger.error(f"Failed to convert audio to Twilio format: {conv_err}. Using original file.")
                    return persistent_path
                    
        except requests.RequestException as e:
            logger.error(f"Speech synthesis request failed: {e}")
            raise APIConnectionError("OpenTTS", e)
        except Exception as e:
            logger.error(f"Speech synthesis failed: {e}", exc_info=True)
            raise SynthesisError(original_error=e)



class SlotFillingService:
    @staticmethod
    def get_prompt(slot_id: str, lang_code: str) -> str:
        for slot in _slot_schema.slots:
            if slot.id == slot_id:
                prompt_dict = slot.prompt.dict()
                return prompt_dict.get(lang_code, prompt_dict["en"])
        return ""
    @staticmethod
    def next_missing_slot(filled: Dict[str, str]) -> Optional[str]:
        for slot in _slot_schema.slots:
            if slot.id not in filled or not filled[slot.id]:
                return slot.id
        return None
    @staticmethod
    @retry(stop=stop_after_attempt(Config.MAX_RETRIES),
           wait=wait_exponential(multiplier=1, min=1, max=10),
           retry=retry_if_exception_type(APIConnectionError))
    
    @staticmethod
    def extract_slots_with_llm(text: str,filled: Dict[str, str],lang_code: str) -> Dict[str, str]:
        try:
            slot_instructions = []
            for slot in _slot_schema.slots:
                if slot.id not in filled or not filled[slot.id]:
                    prompt_dict = slot.prompt.dict()
                    slot_instructions.append({
                        "id": slot.id,
                        "prompt": prompt_dict.get(lang_code, prompt_dict["en"])
                    })
            if not slot_instructions:
                return {}

            slot_descriptions = """Slot keys:
- tenant_name: Name (e.g. "Amit", "Ms. Smith")
- rent_or_buy: "rent" or "buy"
- location: Area(s), comma-separated if many
- bhk_type: "1BHK", "2BHK", "3 bed apartment", etc., or variations ("2 bed", "one bedroom"->"1BHK")
- tenant_type: e.g. "bachelors", "family"
- facing: Direction, e.g. "East"
- floor_pref: Floor, e.g. "Ground", "Upper", "5th floor"
- budget: Amount/range, e.g. "25000 to 30000"
- furnishing: "furnished", "semi-furnished", "unfurnished
-possession_date:date or time frame e.g., "immediately", "from July 2024", "next month","within 15days" 
-profession_details:profession or occupation e.g., "Software Engineer", "Teacher", "Businessman" ``"""
            slot_examples = """Example 1:
User: I am Amit. Looking for a 2BHK rental in Kondapur.
Output: {"tenant_name":"Amit","rent_or_buy":"rent","bhk_type":"2BHK","location":"Kondapur"}
Example 2:
User: buy, semi-furnished, Bangalore, budget 75 lakhs
Output: {"rent_or_buy":"buy","furnishing":"semi-furnished","location":"Bangalore","budget":"75 lakhs"}
Example 3:
User: family, East facing, Whitefield, 3BHK
Output: {"tenant_type":"family","facing":"East","location":"Whitefield","bhk_type":"3BHK"}
Example 4:
User: bachelors
Output: {"tenant_type":"bachelors"}
Example 5:
User: 20,000 to 25,000
Output: {"budget":"20000 to 25000"}
Example 6:
User: unfurnished 1BHK, HSR Layout
Output: {"furnishing":"unfurnished","bhk_type":"1BHK","location":"HSR Layout"}
Example 7:
User: Middle floor
Output: {"floor_pref":"Middle floor"}
Example 8:
User: Rohith
Output: {"tenant_name":"Rohith"}"""


            prompt_instruction = """You are an expert assistant for a real estate slot-filling bot.Extract only the slots mentioned by the user. If multiple values for a slot are present, output as a comma-separated list in the same JSON key (e.g., "location": "Bangalore, Hyderabad").
Normalize BHK values to "1BHK", "2BHK", Output only valid slot keys as defined above and new/updated slots only.Omit any slot not mentioned.Respond with **only** a valid JSON object, with no extra text or explanation"""

            system_prompt = (
                prompt_instruction.strip() + "\n\n"
                + slot_descriptions.strip() + "\n\n"
                + slot_examples.strip()
            )
            user_prompt = f"User: {text}"

            # logger.info(f"Sending extraction request to OpenAI for text: '{text}'")
            # logger.info(f"Sending system prompt to Open AI: {system_prompt}")

            response = client.chat.completions.create(
                model="gpt-4.1-nano",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=256,
                temperature=0.0,
            )

            try:
                content = response.choices[0].message.content
                logger.info(f"RAW LLM RESPONSE: {content}")
                slots_json = json.loads(content)
                logger.info(f"Extracted slots: {slots_json}")
                return slots_json
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse LLM response as JSON: {e}")
                logger.error(f"Raw response: {content}")
                return {}
            except Exception as e:
                logger.error(f"Error processing LLM response: {e}")
                return {}

        except openai.OpenAIError as e:
            logger.error(f"OpenAI API error: {e}")
            raise APIConnectionError("OpenAI", e)
        except Exception as e:
            logger.error(f"Slot filling failed: {e}")
            raise SlotFillingError(original_error=e)

    @staticmethod
    def confirmation_text(tenant_name: str, lang_code: str) -> str:
        templates = {
            "en": f"Thank you! {tenant_name}, your details have been successfully recorded. Goodbye.",  
            "hi": f"धन्यवाद! {tenant_name} आपका विवरण सफलतापूर्वक सहेज लिया है। अलविदा।",  
            "te": f"ధన్యవాదాలు! {tenant_name} మీ వివరాలు విజయవంతంగా నమోదు చేయబడ్డాయి. వీడ్కోలు.",  
            "ta": f"நன்றி! {tenant_name} உங்கள் விவரங்கள் வெற்றிகரமாக பதிவு செய்யப்பட்டுள்ளன. பிரியாவிடை."  
        }
        return templates.get(lang_code, templates["en"])

    @staticmethod
    def lead_info_text(slots_filled: Dict[str, str]) -> str:
        collected_lines = []
        for slot in _slot_schema.slots:
            value = slots_filled.get(slot.id, "-")
            collected_lines.append(f"{slot.id}: {value}")
        return "\n".join(collected_lines)


