// Indian number, currency and date formats.
const inrFmt = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const numFmt = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

export function inr(v: any): string {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  return isNaN(n) ? String(v) : inrFmt.format(n);
}

export function num(v: any): string {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  return isNaN(n) ? String(v) : numFmt.format(n);
}

export function dt(v: any): string {
  if (!v) return "";
  const s = String(v);
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) { const [y, m, d] = s.split("-"); return `${d}-${m}-${y}`; }
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  return d.toLocaleString("en-IN", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).replace(/\//g, "-");
}

export const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
export const monthStart = () => today().slice(0, 8) + "01";
export function fyStart(): string {
  const d = new Date(); const y = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1;
  return `${y}-04-01`;
}
export const label = (s: string) => (s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
