from typing import Dict, Optional
from pydantic import BaseModel, Field
import time
from enum import Enum
from typing import List

# Define slot ids as an Enum for safety and IDE support
class SlotID(str, Enum):
    tenant_name = "tenant_name"
    rent_or_buy = "rent_or_buy"
    location = "location"
    bhk_type = "bhk_type"
    tenant_type = "tenant_type"
    facing = "facing"
    floor_pref = "floor_pref"
    budget = "budget"
    furnishing = "furnishing"
    possession_date = "possession_date"
    profession_details = "profession_details"

class Slot(BaseModel):
    id: SlotID

class SlotSchema(BaseModel):
    slots: List[Slot] = [
        Slot(id=SlotID.tenant_name),
        Slot(id=SlotID.rent_or_buy),
        Slot(id=SlotID.location),
        Slot(id=SlotID.bhk_type),
        Slot(id=SlotID.tenant_type),
        Slot(id=SlotID.facing),
        Slot(id=SlotID.floor_pref),
        Slot(id=SlotID.budget),
        Slot(id=SlotID.furnishing),
        Slot(id=SlotID.possession_date),
        Slot(id=SlotID.profession_details),
    ]

class VoiceMapping(BaseModel):
    en: str = "en-us/ljspeech:en"
    hi: str = "hi-in/ekab:hi"
    te: str = "te-in/satish:te"
    ta: str = "ta-in/kal_diphone:ta"

class TranscriptionResult(BaseModel):
    text: str
    language: str
    confidence: Optional[float] = None

class SlotValues(BaseModel):
    values: Dict[str, str] = {}

class UserSession(BaseModel):
    session_id: str
    language: str = "en"
    slots_filled: Dict[str, str] = Field(default_factory=dict)
    call_start_time: float = Field(default_factory=time.time)
    last_interaction_time: float = Field(default_factory=time.time)
    interaction_count: int = 0
    # user_mobile: str = Field(..., pattern=r"^\+\d{8,15}$")
    # virtual_number: str = Field(..., pattern=r"^\+\d{8,15}$")
    user_mobile: Optional[str] = None
    virtual_number: Optional[str] = None
    end_of_conversation: bool = False
    slot_retry_count: int = 0

