"""
Localization (spec §29): en / ta / hi with an architecture that accepts more.

The backend owns UI strings used in API responses (statuses, email, AI fallback
lines); the frontend carries its own i18n bundle for chrome strings. Keys are
flat `dotted.path` names so adding a language = adding a dict.
"""
from __future__ import annotations

from typing import Any

SUPPORTED_LANGUAGES: list[dict[str, str]] = [
    {"code": "en", "name": "English", "native": "English"},
    {"code": "ta", "name": "Tamil", "native": "தமிழ்"},
    {"code": "hi", "name": "Hindi", "native": "हिन्दी"},
]

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "app.tagline": "AI-powered industrial approval & compliance navigator",
        "nav.dashboard": "Dashboard",
        "nav.projects": "Projects",
        "nav.approvals": "Approvals",
        "nav.documents": "Documents",
        "nav.applications": "Applications",
        "nav.compliance": "Compliance",
        "nav.calendar": "Calendar",
        "nav.queries": "Queries",
        "nav.schemes": "Schemes",
        "nav.portals": "Government portals",
        "nav.assistant": "AI Assistant",
        "nav.settings": "Settings",
        "action.run_analysis": "Run AI analysis",
        "action.next": "Next",
        "action.back": "Back",
        "action.save": "Save",
        "action.confirm": "Confirm",
        "action.cancel": "Cancel",
        "action.open_portal": "Open official portal",
        "state.draft": "Draft",
        "state.ready": "Ready to apply",
        "state.submitted": "Submitted",
        "state.query": "Query raised",
        "state.approved": "Approved",
        "state.rejected": "Rejected",
        "ai.unavailable": "AI assistance is temporarily unavailable. Your saved project information remains available.",
        "ai.unverified": "I could not verify this from the available official sources.",
        "net.offline": "You are offline. Changes will be saved locally and synchronized when the connection returns.",
        "gov.unavailable": "Official integration is currently unavailable. You can continue through the official portal.",
        "doc.failure": "Document could not be processed. Please upload a clearer copy.",
        "sync.conflict": "Your offline version and server version are different.",
        "easy.welcome": "Let's understand your business.",
        "onboarding.step": "Step",
        "onboarding.of": "of",
    },
    "ta": {
        "app.tagline": "தொழில்துறை அனுமதி மற்றும் இணக்க வழிகாட்டி",
        "nav.dashboard": "டாஷ்போர்டு",
        "nav.projects": "திட்டங்கள்",
        "nav.approvals": "அனுமதிகள்",
        "nav.documents": "ஆவணங்கள்",
        "nav.applications": "விண்ணப்பங்கள்",
        "nav.compliance": "இணக்கம்",
        "nav.calendar": "நாட்காட்டி",
        "nav.queries": "விசாரணைகள்",
        "nav.schemes": "திட்டங்கள்",
        "nav.portals": "அரசு இணையதளங்கள்",
        "nav.assistant": "AI உதவியாளர்",
        "nav.settings": "அமைப்புகள்",
        "action.run_analysis": "AI பகுப்பாய்வை இயக்கவும்",
        "action.next": "அடுத்து",
        "action.back": "பின்",
        "action.save": "சேமி",
        "action.confirm": "உறுதிப்படுத்து",
        "action.cancel": "ரத்து",
        "action.open_portal": "அதிகாரப்பூர்வ இணையதளத்தைத் திற",
        "state.draft": "வரைவு",
        "state.ready": "விண்ணப்பிக்க தயார்",
        "state.submitted": "சமர்ப்பிக்கப்பட்டது",
        "state.query": "விசாரணை எழுப்பப்பட்டது",
        "state.approved": "அனுமதிக்கப்பட்டது",
        "state.rejected": "நிராகரிக்கப்பட்டது",
        "ai.unavailable": "AI உதவி தற்காலிகமாக கிடைக்கவில்லை. உங்கள் சேமித்த திட்டத் தகவல் பாதுகாப்பாக உள்ளது.",
        "ai.unverified": "இதை கிடைக்கக்கூடிய அதிகாரப்பூர்வ ஆதாரங்களில் சரிபார்க்க முடியவில்லை.",
        "net.offline": "நீங்கள் ஆஃப்லைனில் உள்ளீர்கள். இணைப்பு திரும்பியதும் மாற்றங்கள் சேமிக்கப்பட்டு ஒத்திசைக்கப்படும்.",
        "gov.unavailable": "அதிகாரப்பூர்வ இணைப்பு தற்போது கிடைக்கவில்லை. அதிகாரப்பூர்வ இணையதளத்தின் மூலம் தொடரலாம்.",
        "doc.failure": "ஆவணத்தை செயலாக்க முடியவில்லை. தெளிவான நகலை பதிவேற்றவும்.",
        "sync.conflict": "உங்கள் ஆஃப்லைன் பதிப்பும் சேவையக பதிப்பும் வேறுபடுகின்றன.",
        "easy.welcome": "உங்கள் வணிகத்தைப் புரிந்துகொள்வோம்.",
        "onboarding.step": "படி",
        "onboarding.of": "இல்",
    },
    "hi": {
        "app.tagline": "एआई-संचालित औद्योगिक अनुमोदन एवं अनुपालन मार्गदर्शक",
        "nav.dashboard": "डैशबोर्ड",
        "nav.projects": "परियोजनाएँ",
        "nav.approvals": "अनुमोदन",
        "nav.documents": "दस्तावेज़",
        "nav.applications": "आवेदन",
        "nav.compliance": "अनुपालन",
        "nav.calendar": "कैलेंडर",
        "nav.queries": "प्रश्न",
        "nav.schemes": "योजनाएँ",
        "nav.portals": "सरकारी पोर्टल",
        "nav.assistant": "एआई सहायक",
        "nav.settings": "सेटिंग्स",
        "action.run_analysis": "एआई विश्लेषण चलाएँ",
        "action.next": "आगे",
        "action.back": "पीछे",
        "action.save": "सहेजें",
        "action.confirm": "पुष्टि करें",
        "action.cancel": "रद्द करें",
        "action.open_portal": "आधिकारिक पोर्टल खोलें",
        "state.draft": "ड्राफ्ट",
        "state.ready": "आवेदन के लिए तैयार",
        "state.submitted": "जमा कर दिया",
        "state.query": "प्रश्न पूछा गया",
        "state.approved": "स्वीकृत",
        "state.rejected": "अस्वीकृत",
        "ai.unavailable": "एआई सहायता अस्थायी रूप से उपलब्ध नहीं है। आपकी सहेजी गई परियोजना जानकारी सुरक्षित है।",
        "ai.unverified": "मैं इसे उपलब्ध आधिकारिक स्रोतों से सत्यापित नहीं कर सका।",
        "net.offline": "आप ऑफ़लाइन हैं। बदलाव स्थानीय रूप से सहेजे जाएंगे और कनेक्शन लौटने पर सिंक होंगे।",
        "gov.unavailable": "आधिकारिक एकीकरण अभी उपलब्ध नहीं है। आधिकारिक पोर्टल से जारी रखें।",
        "doc.failure": "दस्तावेज़ संसाधित नहीं हो सका। कृपया एक स्पष्ट प्रति अपलोड करें।",
        "sync.conflict": "आपका ऑफ़लाइन संस्करण और सर्वर संस्करण अलग-अलग हैं।",
        "easy.welcome": "आइए आपके व्यवसाय को समझें।",
        "onboarding.step": "चरण",
        "onboarding.of": "में",
    },
}


def t(lang: str, key: str) -> str:
    lang = lang if lang in STRINGS else "en"
    return STRINGS[lang].get(key) or STRINGS["en"].get(key) or key


def all_strings() -> dict[str, dict[str, str]]:
    return STRINGS


def localized_enum(value: Any, lang: str) -> str:
    """Best-effort localization of a status/enum value via nav/state keys."""
    text = str(value)
    key = f"state.{text.lower()}"
    translated = t(lang, key)
    return translated if translated != key else text.replace("_", " ").title()
