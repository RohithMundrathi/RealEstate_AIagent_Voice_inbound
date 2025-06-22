import json
import time
import logging
import requests
import concurrent.futures
import assemblyai as aai
import openai
import io
from deepgram import DeepgramClient, PrerecordedOptions
import asyncio
from typing import Dict, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.config import Config
from app.core.models import SlotSchema, TranscriptionResult
from app.utils.exceptions import TranscriptionError, SlotFillingError, APIConnectionError

logger = logging.getLogger(__name__)
client = openai.OpenAI(api_key="sk-proj-") 
_slot_schema = SlotSchema()


# class CloudRunOptimizedService:
#     ASSEMBLYAI_UPLOAD_URL = "https://api.assemblyai.com/v2/upload"
#     ASSEMBLYAI_TRANSCRIBE_URL = "https://api.assemblyai.com/v2/transcript"
#     ASSEMBLYAI_API_KEY = getattr(Config, "ASSEMBLYAI_API_KEY", None)
#     if not ASSEMBLYAI_API_KEY:
#         raise ValueError("ASSEMBLYAI_API_KEY is not set in Config")
    

#     @staticmethod
#     def transcribe_audio(audio_url: str, timeout: int = 13) -> TranscriptionResult:
#         """ Transcribes an audio file from a given URL using AssemblyAI, Cloud Run optimized.Enforces an overall timeout."""
#         try:
#             logger.info(f"Starting transcription for {audio_url}")
#             # Enforce total timeout for all steps
#             with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
#                 future = executor.submit(CloudRunOptimizedService._transcribe_flow, audio_url, timeout)
#                 return future.result(timeout=timeout)
#         except concurrent.futures.TimeoutError:
#             logger.error(f"Transcription timed out after {timeout}s")
#             raise TranscriptionError(f"Transcription timed out after {timeout} seconds")
#         except Exception as e:
#             logger.error(f"Transcription failed: {e}")
#             raise TranscriptionError(f"Transcription failed: {e}")

#     @staticmethod
#     def _transcribe_flow(audio_url: str, timeout: int) -> TranscriptionResult:
#         """Performs the full upload–transcribe–poll flow."""
#         t0 = time.time()
#         api_key = CloudRunOptimizedService.ASSEMBLYAI_API_KEY
#         if not api_key:
#             raise TranscriptionError("ASSEMBLYAI_API_KEY is not set in environment variables")

#         # Step 1: Download audio (fast, in-memory, with timeout)
#         logger.info("Downloading audio into memory")
#         audio_data = CloudRunOptimizedService._download_audio_to_memory(audio_url, api_key)

#         elapsed = time.time() - t0
#         # Step 2: Upload audio to AssemblyAI (in-memory, fast)
#         logger.info("Uploading audio to AssemblyAI")
#         upload_url = CloudRunOptimizedService._upload_audio_data(audio_data, api_key)

#         # Step 3: Request transcription
#         logger.info("Requesting transcription")
#         transcript_id = CloudRunOptimizedService._start_transcription(upload_url, api_key)

#         # Step 4: Poll for completion (remaining timeout)
#         elapsed = time.time() - t0
#         remaining_timeout = max(timeout - int(elapsed), 4)  # Leave 1–2s buffer
#         logger.info(f"Polling for transcript (timeout={remaining_timeout}s)")
#         transcript_result = CloudRunOptimizedService._poll_transcription(
#             transcript_id, api_key, max_wait=remaining_timeout
#         )

#         # Step 5: Package result
#         text = transcript_result.get('text', '')
#         language = transcript_result.get('language_code', 'en').lower()
#         confidence = transcript_result.get('confidence', 1.0)
#         logger.info(f"Transcription success: {text[:40]}...")
#         return TranscriptionResult(text=text, language=language, confidence=confidence)

#     @staticmethod
#     def _download_audio_to_memory(audio_url: str, api_key: Optional[str] = None) -> bytes:
#         """Downloads an audio file into memory, with retries for Twilio 404 timing issues."""
#         import time
#         headers = {'User-Agent': 'Mozilla/5.0'}
#         auth = None
#         if 'twilio.com' in audio_url:
#             twilio_sid = getattr(Config, "TWILIO_ACCOUNT_SID", None)
#             twilio_token = getattr(Config, "TWILIO_AUTH_TOKEN", None)
#             logger.info(f"Twilio SID: {twilio_sid}, Token length: {len(twilio_token) if twilio_token else 0}")
#             if twilio_sid and twilio_token:
#                 auth = (twilio_sid, twilio_token)

#         max_retries = 5
#         retry_delay = 2  # seconds

#         for attempt in range(1, max_retries + 1):
#             resp = requests.get(audio_url, timeout=5, headers=headers, auth=auth, stream=True)
#             if resp.status_code == 200:
#                 audio_buffer = io.BytesIO()
#                 for chunk in resp.iter_content(chunk_size=8192):
#                     if chunk:
#                         audio_buffer.write(chunk)
#                 return audio_buffer.getvalue()
#             elif resp.status_code == 404 and 'twilio.com' in audio_url:
#                 logger.warning(
#                     f"Twilio recording not found (404), attempt {attempt}/{max_retries}. "
#                     f"Retrying in {retry_delay}s..."
#                 )
#                 time.sleep(retry_delay)
#             else:
#                 resp.raise_for_status()

#         # If all retries failed
#         logger.error(f"Failed to fetch Twilio recording after {max_retries} retries")
#         resp.raise_for_status()


#     @staticmethod
#     def _upload_audio_data(audio_data: bytes, api_key: str) -> str:
#         """Uploads audio to AssemblyAI and returns upload URL."""
#         headers = {
#             "authorization": api_key,
#             "content-type": "application/octet-stream"
#         }
#         resp = requests.post(
#             CloudRunOptimizedService.ASSEMBLYAI_UPLOAD_URL,
#             headers=headers,
#             data=audio_data,
#             timeout=10
#         )
#         resp.raise_for_status()
#         upload_url = resp.json().get("upload_url")
#         if not upload_url:
#             raise TranscriptionError("No upload_url returned from AssemblyAI")
#         return upload_url

#     @staticmethod
#     def _start_transcription(upload_url: str, api_key: str) -> str:
#         """Starts transcription and returns transcript ID."""
#         headers = {
#             "authorization": api_key,
#             "content-type": "application/json"
#         }
#         payload = {
#             "audio_url": upload_url,
#             "language_code": "en",
#             "punctuate": True,
#             "format_text": True,
#             "speech_model": "nano",
#             "word_boost": ["3bhk", "rent", "bachelors", "family", "east facing",
#                            "software engineer", "Hitech city"],
#             "boost_param": "high"
#         }
#         resp = requests.post(
#             CloudRunOptimizedService.ASSEMBLYAI_TRANSCRIBE_URL,
#             headers=headers,
#             json=payload,
#             timeout=5
#         )
#         resp.raise_for_status()
#         transcript_id = resp.json().get("id")
#         if not transcript_id:
#             raise TranscriptionError("No transcript ID returned from AssemblyAI")
#         return transcript_id

#     @staticmethod
#     def _poll_transcription(transcript_id: str, api_key: str, max_wait: int = 8) -> dict:
#         """Polls AssemblyAI until transcription is done or times out."""
#         headers = {"authorization": api_key}
#         url = f"{CloudRunOptimizedService.ASSEMBLYAI_TRANSCRIBE_URL}/{transcript_id}"
#         start = time.time()
#         while time.time() - start < max_wait:
#             resp = requests.get(url, headers=headers, timeout=5)
#             resp.raise_for_status()
#             data = resp.json()
#             if data.get("status") == "completed":
#                 return data
#             if data.get("status") == "error":
#                 raise TranscriptionError(f"AssemblyAI error: {data.get('error')}")
#             time.sleep(0.5)
#         raise TranscriptionError("AssemblyAI transcription polling timed out")



class CloudRunOptimizedService:

    DEEPGRAM_API_KEY = getattr(Config, "DEEPGRAM_API_KEY", None)
    if not DEEPGRAM_API_KEY:
        raise ValueError("DEEPGRAM_API_KEY is not set in Config")

    @staticmethod
    def transcribe_audio(audio_url: str, timeout: int = 13) -> TranscriptionResult:
        """Cloud Run optimized transcription flow using Deepgram."""

        try:
            logger.info(f"Starting transcription for {audio_url}")
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(CloudRunOptimizedService._transcribe_flow, audio_url, timeout)
                return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            logger.error(f"Transcription timed out after {timeout}s")
            raise TranscriptionError(f"Transcription timed out after {timeout} seconds")
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise TranscriptionError(f"Transcription failed: {e}")

    @staticmethod
    def _transcribe_flow(audio_url: str, timeout: int) -> TranscriptionResult:
        """Download + Transcribe full flow"""

        t0 = time.time()
        api_key = CloudRunOptimizedService.DEEPGRAM_API_KEY

        # Step 1: Download audio from Twilio into memory
        logger.info("Downloading audio into memory")
        audio_data = CloudRunOptimizedService._download_audio_to_memory(audio_url)

        elapsed = time.time() - t0
        remaining_timeout = max(timeout - int(elapsed), 4)

        # Step 2: Start transcription with Deepgram async safe
        logger.info("Uploading to Deepgram for transcription")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        transcript_result = loop.run_until_complete(
            CloudRunOptimizedService._deepgram_transcribe(api_key, audio_data)
        )

        # Step 3: Package result
        text = transcript_result.get('text', '')
        language = transcript_result.get('language', 'en')
        confidence = transcript_result.get('confidence', 1.0)
        logger.info(f"Transcription success: {text[:40]}...")

        return TranscriptionResult(text=text, language=language, confidence=confidence)

    @staticmethod
    def _download_audio_to_memory(audio_url: str) -> bytes:
        """Downloads Twilio recording in-memory with retry."""

        headers = {'User-Agent': 'Mozilla/5.0'}
        auth = None
        if 'twilio.com' in audio_url:
            twilio_sid = getattr(Config, "TWILIO_ACCOUNT_SID", None)
            twilio_token = getattr(Config, "TWILIO_AUTH_TOKEN", None)
            logger.info(f"Twilio SID: {twilio_sid}, Token length: {len(twilio_token) if twilio_token else 0}")
            if twilio_sid and twilio_token:
                auth = (twilio_sid, twilio_token)

        max_retries = 5
        retry_delay = 2  # seconds

        for attempt in range(1, max_retries + 1):
            resp = requests.get(audio_url, timeout=5, headers=headers, auth=auth, stream=True)
            if resp.status_code == 200:
                audio_buffer = io.BytesIO()
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        audio_buffer.write(chunk)
                return audio_buffer.getvalue()
            elif resp.status_code == 404 and 'twilio.com' in audio_url:
                logger.warning(
                    f"Twilio recording not found (404), attempt {attempt}/{max_retries}. "
                    f"Retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)
            else:
                resp.raise_for_status()

        logger.error(f"Failed to fetch Twilio recording after {max_retries} retries")
        resp.raise_for_status()

    @staticmethod
    async def _deepgram_transcribe(api_key: str, audio_data: bytes) -> dict:
        dg_client = DeepgramClient(api_key)
        source = {"buffer": audio_data}
        
        # Define keywords for better detection
        keywords = [
            "east facing:3",        # Higher boost for directional terms
            "facing:4",
            "software engineer:4",   # High boost for professional terms
            "Kondapur:3,"
            "bachelors:4"
        ]
        
        options = PrerecordedOptions(
            model="nova-2-phonecall",  # Use nova-2-general for better accuracy
            smart_format=True,
            punctuate=True,
            detect_language=True,
            keywords=keywords,       # Add keywords for better detection
            profanity_filter=False,  # Disable if interfering with technical terms
            redact=False,
            diarize=False,
            numerals=True,          # Better number detection
            search=["east", "facing", "software", "engineer"]  # Additional search terms
        )
        
        try:
            response = dg_client.listen.prerecorded.v("1").transcribe_file(source, options)
            result = response.results.channels[0].alternatives[0]
            
            return {
                'text': result.transcript,
                'confidence': result.confidence,
                'language': getattr(result, 'language', 'en'),
                'keywords_found': getattr(result, 'keywords', []) 
            }
        except Exception as e:
            logger.exception("Deepgram SDK call failed")
            raise TranscriptionError(f"Deepgram SDK call failed: {e}")





# class TranscriptionService:
#     @staticmethod
#     def transcribe_audio(audio_url: str) -> 'TranscriptionResult':
#         try:
#             timeout = 15
#             # 1. Set up AssemblyAI API key
#             api_key = getattr(Config, "ASSEMBLYAI_API_KEY", None)
#             if not api_key:
#                 raise ValueError("ASSEMBLYAI_API_KEY is not set in Config")
            
#             aai.settings.api_key = api_key
            
#             # 2. Create transcriber with configuration
#             config = aai.TranscriptionConfig(
#                 language_detection=True,
#                 punctuate=True,
#                 format_text=True,
#                 word_boost = ["3bhk", "rent", "bachelors","family","east facing","software engineer","Hitech city"],
#                 boost_param = "high",
#             )
            
#             transcriber = aai.Transcriber(config=config)
            
#             # 3. Transcribe directly from URL (if AssemblyAI can access it)
#             logger.info(f"Starting direct URL transcription of {audio_url}")
#             transcript = TranscriptionService.transcribe_with_timeout(transcriber, audio_url, timeout)
        
#             # 4. Check transcription status
#             if transcript.status == aai.TranscriptStatus.error:
#                 raise TranscriptionError(f"Transcription failed: {transcript.error}")
            
#             text = transcript.text.strip() if transcript.text else ""
#             if not text:
#                 raise TranscriptionError("Transcription returned empty text")
            
#             # Get detected language
#             detected_language = getattr(transcript, 'language_code', 'en')
#             lang = detected_language.lower() if detected_language else "en"
            
#             logger.info(f"Direct URL transcription successful: '{text[:50]}...' (lang: {lang})")
            
#             return TranscriptionResult(
#                 text=text,
#                 language=lang,
#                 confidence=getattr(transcript, 'confidence', 1.0)
#             )
            
#         except Exception as e:
#             logger.error(f"Direct URL transcription failed: {str(e)}")
#             logger.info("Falling back to download and upload method")
#             return TranscriptionService.transcribe_audio(audio_url)
#     @staticmethod
#     def transcribe_with_timeout(transcriber, audio_url, timeout):
#         with concurrent.futures.ThreadPoolExecutor() as executor:
#             future = executor.submit(transcriber.transcribe, audio_url)
#             return future.result(timeout=timeout)

class SlotFillingService:
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
                    slot_instructions.append({"id": slot.id})
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
Output: {"tenant_type":"family","facing":"East facing","location":"Whitefield","bhk_type":"3BHK"}
Example 4:
User: bachelors
Output: {"tenant_type":"bachelors"}
Example 5:
User: 20,000 to 25,000
Output: {"budget":"20000 to 25000"}
Example 6:
User: unfurnished 1BHK, HSR Layout, west
Output: {"furnishing":"unfurnished","bhk_type":"1BHK","location":"HSR Layout","facing":"west facing"}
Example 7:
User: Middle floor
Output: {"floor_pref":"Middle floor"}
Example 8:
User: Rohith
Output: {"tenant_name":"Rohith"}"""


            prompt_instruction = """You are an expert assistant for a real estate slot-filling bot.Extract **only** the slots mentioned by the user, from this list: ["tenant_name", "rent_or_buy", "bhk_type", "location", "furnishing", "budget", "tenant_type", "facing", "floor_pref", "profession_details", ...].If multiple values for a slot are present, output them as a comma-separated string in the same JSON key (e.g., "location": "Bangalore, Hyderabad").
Normalize BHK values to "1BHK", "2BHK", etc.Output **only** valid slot keys (from the list above) and only for new or updated slots. Omit any slot not mentioned.ALWAYS extract the full facing value as heard, e.g., "East facing" or "West facing", not just "East" or "West".
Do **not** hallucinate keys or values.Respond with **only** a valid JSON object, with no extra text or explanation."""

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
    def lead_info_text(slots_filled: Dict[str, str]) -> str:
        collected_lines = []
        for slot in _slot_schema.slots:
            value = slots_filled.get(slot.id, "-")
            collected_lines.append(f"{slot.id}: {value}")
        return "\n".join(collected_lines)


