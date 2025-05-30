from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
import time

class SlotPrompt(BaseModel):
    en: str
    hi: Optional[str] = None
    te: Optional[str] = None
    ta: Optional[str] = None

class Slot(BaseModel):
    id: str
    prompt: SlotPrompt

class SlotSchema(BaseModel):
    slots: List[Slot] = [
        Slot(id="tenant_name", prompt=SlotPrompt(
        en="May I know your name, please?", 
        hi="कृपया अपना नाम बताएं।", 
        te="మీ పేరు చెప్పగలరా?", 
        ta="உங்கள் பெயரை கூற முடியுமா?")),

    Slot(id="rent_or_buy", prompt=SlotPrompt(
        en="Are you looking to rent or to buy?", 
        hi="क्या आप किराए पर लेना चाहते हैं या खरीदना चाहते हैं?", 
        te="మీరు అద్దెకు తీసుకోవాలనుకుంటున్నారా లేదా కొనుగోలు చేయాలనుకుంటున్నారా?", 
        ta="நீங்கள் வாடகைக்கு அல்லது வாங்க விரும்புகிறீர்களா?")),

    Slot(id="location", prompt=SlotPrompt(
        en="Which location(s) do you prefer?", 
        hi="आप किन स्थानों को प्राथमिकता देंगे?", 
        te="మీరు ఏ ప్రాంతాలను ఇష్టపడతారు?", 
        ta="நீங்கள் எந்த இடங்களை விரும்புகிறீர்கள்?")),

    Slot(id="bhk_type", prompt=SlotPrompt(
        en="What type of BHK are you interested in example: 3bhk?", 
        hi="आप किस प्रकार के BHK में रुचि रखते हैं?", 
        te="మీరు ఏ BHK టైప్ ఆసక్తి చూపిస్తున్నారు?", 
        ta="நீங்கள் எந்த வகை BHK விரும்புகிறீர்கள்?")),

    Slot(id="tenant_type", prompt=SlotPrompt(
        en="Will the property be for bachelors or family example: bachelors?", 
        hi="क्या संपत्ति बैचलर्स, परिवार या अन्य किसी के लिए है?", 
        te="ఈ ప్రాపర్టీ బ్యాచిలర్స్, ఫ్యామిలీ లేదా ఇంకెవరైనా కోసం కావాలా?", 
        ta="இந்த சொத்து தனிப்பட்டவர்களுக்கு, குடும்பத்திற்கு அல்லது வேறு யாருக்காகவும் வேண்டுமா?")),

    Slot(id="facing", prompt=SlotPrompt(
        en="Do you have a preference for the facing direction example: east facing?", 
        hi="क्या आपके पास फेसिंग दिशा के लिए कोई पसंद है?", 
        te="మీరు ఏ ముఖదిశలో ఇష్టం ఉన్నదా?", 
        ta="முகப்புத் திசையில் உங்களுக்கு விருப்பம் உள்ளதா?")),

    Slot(id="floor_pref", prompt=SlotPrompt(
        en="Which floor do you prefer example: 5th floor?", 
        hi="आप किस मंजिल को पसंद करेंगे?", 
        te="మీరు ఏ ఫ్లోర్ ఇష్టపడతారు?", 
        ta="நீங்கள் எந்த மாடியை விரும்புகிறீர்கள்?")),

    Slot(id="budget", prompt=SlotPrompt(
        en="What is your preferred budget example: fifty thousand?", 
        hi="आपका पसंदीदा बजट क्या है?", 
        te="మీరు ఎటువంటి బడ్జెట్ చూస్తున్నారు?", 
        ta="நீங்கள் விரும்பும் பட்ஜெட் எது?")),

    Slot(id="furnishing", prompt=SlotPrompt(
        en="Do you have a preference for furnished, semi-furnished, or unfurnished?", 
        hi="क्या आप फर्निश्ड, सेमी-फर्निश्ड या अनफर्निश्ड पसंद करेंगे?", 
        te="మీరు ఫర్నిష్డ్, సెమీ-ఫర్నిష్డ్ లేదా అన్ఫర్నిష్డ్ ఇష్టపడతారా?", 
        ta="முழுமையாக, பகுதி, அல்லது இல்லாமல் அமைக்கப்பட்ட வீட்டில் உங்களுக்கு விருப்பமா?")),
    Slot(id="possession_date", prompt=SlotPrompt(
        en="When would you like to take possession date or move in date example: june 1st week?", 
        hi="आप कब कब्जा लेना या शिफ्ट होना चाहेंगे?", 
        te="మీరు ఎప్పుడు ఇంట్లోకి మారాలని అనుకుంటున్నారు?", 
        ta="நீங்கள் எப்போது வீடு பிடிக்க விரும்புகிறீர்கள்?")),

    Slot(id="profession_details", prompt=SlotPrompt(
        en="Could you please share your profession or occupation details example: software engineer?", 
        hi="कृपया अपना पेशा या व्यवसाय बताएं।", 
        te="మీ వృత్తి లేదా ఉద్యోగం చెప్పగలరా?", 
        ta="உங்கள் தொழில் அல்லது வேலை கூற முடியுமா?")),
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
    slots_filled: Dict[str, str] = {}
    call_start_time: float = Field(default_factory=time.time)
    last_interaction_time: float = Field(default_factory=time.time)
    interaction_count: int = 0
    user_mobile: str = Field(..., pattern=r"^\+\d{8,15}$")
    virtual_number: str = Field(..., pattern=r"^\+\d{8,15}$")
    end_of_conversation: bool = False
    slot_retry_count: int = 0

