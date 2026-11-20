// English / Tamil UI labels. Data (names, addresses) is shown as entered.
const ta: Record<string, string> = {
  Dashboard: "முகப்பு", Operations: "செயல்பாடுகள்", Bookings: "முன்பதிவுகள்", "LR / Consignments": "LR / சரக்கு ரசீது", Trips: "பயணங்கள்",
  "Fleet board": "வாகன நிலை", Masters: "முதன்மை தரவு", Customers: "வாடிக்கையாளர்கள்", Vehicles: "வாகனங்கள்", Drivers: "ஓட்டுநர்கள்",
  Vendors: "விற்பனையாளர்கள்", Routes: "வழித்தடங்கள்", "Rate contracts": "கட்டண ஒப்பந்தங்கள்", Billing: "பில்லிங்", Invoices: "விலைப்பட்டியல்கள்",
  "Receipts": "வரவுகள்", Accounts: "கணக்குகள்", Vouchers: "வவுச்சர்கள்", Ledgers: "பேரேடுகள்", "Bank reconciliation": "வங்கி சமரசம்",
  Fleet: "வாகனப் படை", "Diesel & fuel": "டீசல் & எரிபொருள்", Maintenance: "பராமரிப்பு", Tyres: "டயர்கள்", "Tolls & FASTag": "சுங்கம் & FASTag",
  Warehouse: "கிடங்கு", Stock: "இருப்பு", Purchase: "கொள்முதல்", "Vendor bills": "விற்பனையாளர் பில்கள்", Documents: "ஆவணங்கள்", HR: "மனிதவளம்",
  Employees: "பணியாளர்கள்", Attendance: "வருகை", Payroll: "சம்பளம்", Compliance: "சட்ட இணக்கம்", Reports: "அறிக்கைகள்", Admin: "நிர்வாகம்",
  Company: "நிறுவனம்", Settings: "அமைப்புகள்", Users: "பயனர்கள்", Roles: "பங்குகள்", "Audit trail": "தணிக்கை பதிவு", Backup: "காப்புப்பிரதி",
  Notifications: "அறிவிப்புகள்", Save: "சேமி", Cancel: "ரத்து", Close: "மூடு", New: "புதியது", Edit: "திருத்து", Search: "தேடு",
  "Sign in": "உள்நுழை", "Sign out": "வெளியேறு", Username: "பயனர் பெயர்", Password: "கடவுச்சொல்", Profile: "சுயவிவரம்", Alerts: "எச்சரிக்கைகள்",
  "Total fleet": "மொத்த வாகனங்கள்", "On road": "சாலையில்", Available: "கிடைக்கிறது", "Today's trips": "இன்றைய பயணங்கள்", "Today's LR": "இன்றைய LR",
  "Today's billing": "இன்றைய பில்", "Monthly revenue": "மாத வருவாய்", Receivables: "வர வேண்டியவை", "Pending deliveries": "நிலுவையில் உள்ள டெலிவரிகள்",
  "Net profit": "நிகர லாபம்", "Fuel expenses": "எரிபொருள் செலவு", "Maintenance expenses": "பராமரிப்பு செலவு", "My trips": "என் பயணங்கள்",
  "Book vehicle": "வாகனம் முன்பதிவு", Shipments: "சரக்குகள்", Statement: "கணக்கு அறிக்கை", Complaints: "புகார்கள்", Payments: "கட்டணங்கள்",
  "Loading done": "ஏற்றம் முடிந்தது", "Start trip": "பயணம் தொடங்கு", Delivered: "டெலிவரி முடிந்தது", "Upload POD": "POD பதிவேற்று", Expense: "செலவு",
  Incident: "சம்பவம்", "Odometer": "ஓடோமீட்டர்", Language: "மொழி",
};

let lang = (() => { try { return localStorage.getItem("svsl_lang") || "en"; } catch { return "en"; } })();
export const getLang = () => lang;
export function setLang(l: string) { lang = l; try { localStorage.setItem("svsl_lang", l); } catch { /* ignore */ } }
export const t = (s: string) => (lang === "ta" && ta[s]) || s;
