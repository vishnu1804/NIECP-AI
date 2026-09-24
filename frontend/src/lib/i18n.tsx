/**
 * Localization (spec §29): English, Tamil, Hindi. Extensible by adding a dict.
 */
import React, { createContext, useContext, useEffect, useState } from "react";

export type Lang = "en" | "ta" | "hi";

export const LANGUAGES: { code: Lang; native: string; name: string }[] = [
  { code: "en", native: "English", name: "English" },
  { code: "ta", native: "தமிழ்", name: "Tamil" },
  { code: "hi", native: "हिन्दी", name: "Hindi" },
];

const STRINGS: Record<Lang, Record<string, string>> = {
  en: {
    "app.tagline": "AI-powered industrial approval & compliance navigator",
    "nav.dashboard": "Dashboard",
    "nav.projects": "Projects",
    "nav.approvals": "Approvals",
    "nav.documents": "Documents",
    "nav.applications": "Applications",
    "nav.compliance": "Compliance",
    "nav.calendar": "Calendar",
    "nav.queries": "Queries",
    "nav.inspections": "Inspections",
    "nav.schemes": "Schemes",
    "nav.portals": "Gov portals",
    "nav.radar": "Change radar",
    "nav.assistant": "AI Assistant",
    "nav.notifications": "Notifications",
    "nav.settings": "Settings",
    "nav.admin": "Admin",
    "action.runAnalysis": "Run AI analysis",
    "action.next": "Next",
    "action.back": "Back",
    "action.save": "Save",
    "action.confirm": "Confirm",
    "action.cancel": "Cancel",
    "action.openPortal": "Open official portal",
    "action.start": "Start project",
    "action.explore": "Explore platform",
    "easy.welcome": "Let's understand your business.",
    "easy.on": "Easy mode",
    "easy.off": "Standard mode",
    "home.hero": "Simplify Industrial Approvals with AI",
    "home.sub": "NIECP-AI helps you understand potential approvals, prepare documents, track applications and manage compliance through one intelligent platform.",
  },
  ta: {
    "app.tagline": "தொழில்துறை அனுமதி மற்றும் இணக்க வழிகாட்டி",
    "nav.dashboard": "டாஷ்போர்டு",
    "nav.projects": "திட்டங்கள்",
    "nav.approvals": "அனுமதிகள்",
    "nav.documents": "ஆவணங்கள்",
    "nav.applications": "விண்ணப்பங்கள்",
    "nav.compliance": "இணக்கம்",
    "nav.calendar": "நாட்காட்டி",
    "nav.queries": "விசாரணைகள்",
    "nav.inspections": "ஆய்வுகள்",
    "nav.schemes": "திட்டங்கள்",
    "nav.portals": "அரசு இணையதளங்கள்",
    "nav.radar": "மாற்ற ரேடார்",
    "nav.assistant": "AI உதவியாளர்",
    "nav.notifications": "அறிவிப்புகள்",
    "nav.settings": "அமைப்புகள்",
    "nav.admin": "நிர்வாகம்",
    "action.runAnalysis": "AI பகுப்பாய்வு இயக்கவும்",
    "action.next": "அடுத்து",
    "action.back": "பின்",
    "action.save": "சேமி",
    "action.confirm": "உறுதிப்படுத்து",
    "action.cancel": "ரத்து",
    "action.openPortal": "அதிகாரப்பூர்வ இணையதளம்",
    "action.start": "திட்டத்தைத் தொடங்கு",
    "action.explore": "மேலும் பார்க்க",
    "easy.welcome": "உங்கள் வணிகத்தைப் புரிந்துகொள்வோம்.",
    "easy.on": "எளிய முறை",
    "easy.off": "நிலையான முறை",
    "home.hero": "தொழில்துறை அனுமதிகளை AI உடன் எளிதாக்குங்கள்",
    "home.sub": "சாத்தியமான அனுமதிகளைப் புரிந்துகொள்ள, ஆவணங்களைத் தயாரிக்க, விண்ணப்பங்களைக் கண்காணிக்க மற்றும் இணக்கத்தை நிர்வகிக்க உதவுகிறது.",
  },
  hi: {
    "app.tagline": "एआई-संचालित औद्योगिक अनुमोदन एवं अनुपालन मार्गदर्शक",
    "nav.dashboard": "डैशबोर्ड",
    "nav.projects": "परियोजनाएँ",
    "nav.approvals": "अनुमोदन",
    "nav.documents": "दस्तावेज़",
    "nav.applications": "आवेदन",
    "nav.compliance": "अनुपालन",
    "nav.calendar": "कैलेंडर",
    "nav.queries": "प्रश्न",
    "nav.inspections": "निरीक्षण",
    "nav.schemes": "योजनाएँ",
    "nav.portals": "सरकारी पोर्टल",
    "nav.radar": "परिवर्तन रडार",
    "nav.assistant": "एआई सहायक",
    "nav.notifications": "सूचनाएँ",
    "nav.settings": "सेटिंग्स",
    "nav.admin": "प्रशासन",
    "action.runAnalysis": "एआई विश्लेषण चलाएँ",
    "action.next": "आगे",
    "action.back": "पीछे",
    "action.save": "सहेजें",
    "action.confirm": "पुष्टि करें",
    "action.cancel": "रद्द करें",
    "action.openPortal": "आधिकारिक पोर्टल खोलें",
    "action.start": "परियोजना शुरू करें",
    "action.explore": "प्लेटफ़ॉर्म देखें",
    "easy.welcome": "आइए आपके व्यवसाय को समझें।",
    "easy.on": "आसान मोड",
    "easy.off": "मानक मोड",
    "home.hero": "एआई के साथ औद्योगिक अनुमोदन सरल करें",
    "home.sub": "संभावित अनुमोदन समझने, दस्तावेज़ तैयार करने, आवेदन ट्रैक करने और अनुपालन प्रबंधित करने में मदद करता है।",
  },
};

interface I18nCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string) => string;
  statusLabel: (value: string | null | undefined) => string;
}

const Ctx = createContext<I18nCtx>({ lang: "en", setLang: () => {}, t: (k) => k, statusLabel: (v) => v || "" });

export function I18nProvider({ children, initial }: { children: React.ReactNode; initial?: Lang }) {
  const [lang, setLangState] = useState<Lang>(initial || (localStorage.getItem("niecp.lang") as Lang) || "en");

  const setLang = (l: Lang) => {
    setLangState(l);
    localStorage.setItem("niecp.lang", l);
    document.documentElement.lang = l === "ta" ? "ta" : l === "hi" ? "hi" : "en";
  };

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const t = (key: string) => STRINGS[lang]?.[key] ?? STRINGS.en[key] ?? key;
  const statusLabel = (v: string | null | undefined) => {
    if (!v) return "—";
    const key = `state.${v.toLowerCase()}`;
    const translated = STRINGS[lang]?.[key];
    if (translated) return translated;
    return v.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  };

  return <Ctx.Provider value={{ lang, setLang, t, statusLabel }}>{children}</Ctx.Provider>;
}

export const useI18n = () => useContext(Ctx);
