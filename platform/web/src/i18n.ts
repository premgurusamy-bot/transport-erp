// Tamil / English localisation foundation. Add keys here; missing Tamil falls back to English.
import { useSyncExternalStore } from "react";

const dict: Record<string, { en: string; ta: string }> = {
  "app.name": { en: "G ROAD LINES", ta: "ஜி ரோடு லைன்ஸ்" },
  "nav.controlTower": { en: "Control Tower", ta: "கட்டுப்பாட்டு மையம்" },
  "nav.approvals": { en: "Approvals", ta: "ஒப்புதல்கள்" },
  "nav.enquiries": { en: "Enquiries", ta: "விசாரணைகள்" },
  "nav.quotations": { en: "Quotations", ta: "விலைப்புள்ளிகள்" },
  "nav.bookings": { en: "Bookings", ta: "முன்பதிவுகள்" },
  "nav.dispatch": { en: "Dispatch", ta: "அனுப்புதல்" },
  "nav.trips": { en: "Trips", ta: "பயணங்கள்" },
  "nav.fleet": { en: "Fleet", ta: "வாகனங்கள்" },
  "nav.drivers": { en: "Drivers", ta: "ஓட்டுநர்கள்" },
  "nav.owners": { en: "Vehicle Owners", ta: "வாகன உரிமையாளர்கள்" },
  "nav.supply": { en: "Vendors & Stores", ta: "விற்பனையாளர்கள்" },
  "nav.finance": { en: "Accounts", ta: "கணக்குகள்" },
  "nav.bank": { en: "Bank Reconciliation", ta: "வங்கி சமரசம்" },
  "nav.reports": { en: "Reports", ta: "அறிக்கைகள்" },
  "nav.risk": { en: "Complaints & Claims", ta: "புகார்கள் & கோரிக்கைகள்" },
  "nav.people": { en: "HR & SOP", ta: "மனிதவளம்" },
  "nav.marketing": { en: "Marketing", ta: "சந்தைப்படுத்தல்" },
  "nav.ai": { en: "AI Assistants", ta: "AI உதவியாளர்கள்" },
  "nav.admin": { en: "Administration", ta: "நிர்வாகம்" },
  "nav.masters": { en: "Master Data", ta: "அடிப்படை தரவு" },
  "action.save": { en: "Save", ta: "சேமி" },
  "action.signIn": { en: "Sign in", ta: "உள்நுழை" },
  "action.signOut": { en: "Sign out", ta: "வெளியேறு" },
  "driver.parkFirst": { en: "Park safely before using the app. Never use the phone while driving.", ta: "வாகனத்தை பாதுகாப்பாக நிறுத்திய பின் மட்டுமே பயன்படுத்தவும். ஓட்டும்போது கைபேசியை பயன்படுத்தாதீர்கள்." },
  "driver.myTrips": { en: "My trips", ta: "என் பயணங்கள்" },
  "driver.sos": { en: "SOS / Emergency", ta: "அவசர உதவி" },
  "website.hero": { en: "Reliable FTL & PTL transport from Coimbatore", ta: "கோயம்புத்தூரிலிருந்து நம்பகமான முழு & பகிர்வு லாரி போக்குவரத்து" },
  "website.enquire": { en: "Get a quotation", ta: "விலைப்புள்ளி பெறுக" },
};

let lang: "en" | "ta" = (() => { try { return (localStorage.getItem("grl.lang") as any) || "en"; } catch { return "en"; } })();
const subs = new Set<() => void>();
export function setLang(l: "en" | "ta") {
  lang = l;
  try { localStorage.setItem("grl.lang", l); } catch { /* ignore */ }
  subs.forEach((f) => f());
}
export function useLang() {
  return useSyncExternalStore((cb) => { subs.add(cb); return () => subs.delete(cb); }, () => lang);
}
export function t(key: string): string {
  const e = dict[key];
  return e ? (e[lang] || e.en) : key;
}
