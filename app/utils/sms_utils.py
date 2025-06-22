import os
import logging
import json
from twilio.rest import Client

logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', 'YOUR_TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', 'YOUR_TWILIO_AUTH_TOKEN')
# TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER', 'YOUR_TWILIO_PHONE_NUMBER')
NUMBER_MAP_PATH = os.getenv('NUMBER_MAP_PATH', 'number_map.json')

def load_number_map():
    with open(NUMBER_MAP_PATH, "r") as f:
        return json.load(f)

def get_personal_number(virtual_number):
    number_map = load_number_map()
    return number_map.get(virtual_number)

def send_sms(virtual_number: str, message: str) -> str:
    """
    Send SMS FROM the virtual_number (Twilio/Plivo) TO the user's personal number.
    """
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and virtual_number):
        logger.error("Twilio credentials are not set")
        raise ValueError("Twilio credentials are missing")
    personal_number = get_personal_number(virtual_number)
    logger.info(f"Sending final collect requirements to {personal_number} and message: {message}")
    # if not personal_number:
    #     logger.error(f"No personal number mapped for virtual number {virtual_number}")
    #     raise ValueError(f"No personal number mapped for virtual number {virtual_number}")
    # try:
    #     client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    #     sms = client.messages.create(
    #         body=message,
    #         from_=virtual_number,   # Send FROM the virtual number the user called
    #         to=personal_number      # Send TO the personal number mapped in the JSON
    #     )
    #     logger.info(f"SMS sent to {personal_number} from {virtual_number}: SID {sms.sid}")
    #     return sms.sid, sms.personal_number
    # except Exception as e:
    #     logger.error(f"Failed to send SMS to {personal_number}: {e}")
    #     raise

