// Themes: a light/dark mode plus an accent colour. Every colour in the app (including charts) comes from CSS variables
// set by these two attributes on <html>, so switching is instant and needs no reload. Saved per device.
export type Mode = "light" | "dark" | "auto";
export const ACCENTS: { key: string; name: string; light: string; dark: string }[] = [
  { key: "prime", name: "A Prime navy & gold", light: "#12306a", dark: "#8fb0ff" },
  { key: "ocean", name: "Ocean blue", light: "#0f5fa8", dark: "#5aa9f0" },
  { key: "teal", name: "Teal", light: "#0f766e", dark: "#2dd4bf" },
  { key: "indigo", name: "Indigo", light: "#4338ca", dark: "#a5b4fc" },
  { key: "emerald", name: "Emerald", light: "#15803d", dark: "#4ade80" },
  { key: "saffron", name: "Saffron", light: "#c2410c", dark: "#fb923c" },
  { key: "maroon", name: "Maroon", light: "#9f1239", dark: "#fb7185" },
  { key: "slate", name: "Graphite", light: "#334155", dark: "#cbd5e1" },
];

type Theme = { mode: Mode; accent: string; sidebar: "light" | "dark" };
const KEY = "svsl_theme";
const DEFAULT: Theme = { mode: "auto", accent: "prime", sidebar: "light" };
const listeners = new Set<() => void>();
const media = typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

function read(): Theme {
  try { return { ...DEFAULT, ...JSON.parse(localStorage.getItem(KEY) || "{}") }; } catch { return { ...DEFAULT }; }
}
let current = read();

export const getTheme = () => current;
export const resolvedMode = (): "light" | "dark" => (current.mode === "auto" ? (media?.matches ? "dark" : "light") : current.mode);

export function applyTheme() {
  const el = document.documentElement;
  const mode = resolvedMode();
  el.dataset.mode = mode;
  el.dataset.accent = ACCENTS.some((a) => a.key === current.accent) ? current.accent : "prime";
  el.dataset.sidebar = current.sidebar;
  el.style.colorScheme = mode;
  const a = ACCENTS.find((x) => x.key === el.dataset.accent)!;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", mode === "dark" ? "#0e141b" : a.light);
  listeners.forEach((l) => l());
}

export function setTheme(t: Partial<Theme>) {
  current = { ...current, ...t };
  try { localStorage.setItem(KEY, JSON.stringify(current)); } catch { /* private mode: still applies for this session */ }
  applyTheme();
}

export function onThemeChange(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; }

media?.addEventListener?.("change", () => current.mode === "auto" && applyTheme());
