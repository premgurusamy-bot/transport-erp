// Charts, stat cards and icons. Plain SVG (no chart library); every colour is a CSS variable, so they follow the theme.
import React, { useRef, useState } from "react";
import { inr, num } from "../lib/format";
import { t } from "../lib/i18n";

// ------------------------------------------------------------------ icons (24×24 stroke icons)
const P: Record<string, string> = {
  dashboard: "M3 3h8v8H3zM13 3h8v5h-8zM13 10h8v11h-8zM3 13h8v8H3z",
  truck: "M1 5h13v11H1zM14 9h4l4 4v3h-8zM5.5 19a2 2 0 1 0 0-.01M18.5 19a2 2 0 1 0 0-.01",
  route: "M6 19a2 2 0 1 0 0-.01M18 5a2 2 0 1 0 0-.01M6 17V9a4 4 0 0 1 4-4h2M18 7v8a4 4 0 0 1-4 4h-2",
  file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h6",
  box: "M21 8 12 3 3 8v8l9 5 9-5zM3 8l9 5 9-5M12 13v8",
  users: "M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M23 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8",
  user: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8",
  rupee: "M6 3h12M6 8h12M6 3h3a5 5 0 0 1 0 10H6l9 8",
  wallet: "M20 7H5a2 2 0 0 1 0-4h13v4M3 5v14a2 2 0 0 0 2 2h15V7M16 14h.01",
  book: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5zM4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5",
  bank: "M3 21h18M5 21V10M9 21V10M15 21V10M19 21V10M2 10l10-7 10 7z",
  fuel: "M3 22h12M4 22V4a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v18M4 10h10M14 13h2a2 2 0 0 1 2 2v3a2 2 0 0 0 4 0V9l-3-3",
  wrench: "M14.7 6.3a4 4 0 0 0 5 5L22 14l-8 8-2.3-2.3a4 4 0 0 0-5-5L2 10l8-8z",
  tyre: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8",
  toll: "M3 21V8l9-5 9 5v13M8 21v-6h8v6M3 12h18",
  warehouse: "M22 8.4V20a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V8.4L12 3zM6 21v-8h12v8M6 17h12",
  cart: "M9 22a1 1 0 1 0 0-.01M20 22a1 1 0 1 0 0-.01M1 1h4l2.7 13.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L23 6H6",
  briefcase: "M20 7H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16",
  shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10M9 12l2 2 4-4",
  chart: "M3 3v18h18M7 15l4-4 3 3 6-6",
  pie: "M21.2 15.9A10 10 0 1 1 8 2.8M22 12A10 10 0 0 0 12 2v10z",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1",
  building: "M3 21h18M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16M9 7h1M14 7h1M9 11h1M14 11h1M9 15h1M14 15h1",
  upload: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12",
  history: "M3 3v5h5M3.1 13A9 9 0 1 0 6 5.3L3 8M12 7v5l4 2",
  save: "M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2M17 21v-8H7v8M7 3v5h8",
  alert: "M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0M12 9v4M12 17h.01",
  clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20M12 6v6l4 2",
  check: "M22 11.1V12a10 10 0 1 1-5.9-9.1M22 4 12 14l-3-3",
  pin: "M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 0 1 18 0M12 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6",
  bell: "M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0",
  menu: "M3 12h18M3 6h18M3 18h18",
  chevron: "M9 18l6-6-6-6",
  palette: "M12 22a10 10 0 1 1 10-10c0 2.8-2.2 4-4 4h-2a2 2 0 0 0-1.5 3.3A1.7 1.7 0 0 1 12 22M7.5 10.5h.01M10.5 7h.01M15 7.5h.01M17 11h.01",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8",
  monitor: "M2 3h20v14H2zM8 21h8M12 17v4",
  up: "M7 17 17 7M7 7h10v10", down: "M7 7l10 10M17 7v10H7",
  plus: "M12 5v14M5 12h14", calendar: "M3 4h18v18H3zM16 2v4M8 2v4M3 10h18",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
  message: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
  barcode: "M3 5v14M7 5v14M11 5v14M14 5v14M18 5v14M21 5v14",
  gauge: "M12 14l4-4M3.3 19a10 10 0 1 1 17.4 0",
  layout: "M3 3h18v18H3zM3 9h18M9 21V9",
};
export function Icon({ name, size = 18, className = "" }: { name: string; size?: number; className?: string }) {
  return <svg viewBox="0 0 24 24" width={size} height={size} className={`ic ${className}`} aria-hidden="true"><path d={P[name] || P.file} /></svg>;
}

// ------------------------------------------------------------------ number helpers
/** ₹ in Indian short form: 1.2 Cr, 38.7 L, 15.1 K */
export function short(v: any, rupee = true): string {
  const n = Number(v || 0), a = Math.abs(n), s = n < 0 ? "-" : "", r = rupee ? "₹" : "";
  if (a >= 1e7) return `${s}${r}${(a / 1e7).toFixed(a >= 1e9 ? 0 : 2)} Cr`;
  if (a >= 1e5) return `${s}${r}${(a / 1e5).toFixed(2)} L`;
  if (a >= 1e3) return `${s}${r}${(a / 1e3).toFixed(1)} K`;
  return `${s}${r}${Math.round(a)}`;
}
/** % change from previous to current; null when there is nothing to compare with */
export function change(cur: any, prev: any): number | null {
  const c = Number(cur || 0), p = Number(prev || 0);
  if (!p) return null;
  return Math.round(((c - p) / Math.abs(p)) * 1000) / 10;
}
const PALETTE = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)", "var(--c7)"];
export const color = (i: number) => PALETTE[i % PALETTE.length];

// ------------------------------------------------------------------ stat card
export function Delta({ value, goodWhen = "up", suffix = "since last period" }: { value: number | null; goodWhen?: "up" | "down"; suffix?: string }) {
  if (value === null || value === undefined || !isFinite(value)) return null;
  const dir = value > 0 ? "up" : value < 0 ? "down" : "flat";
  const tone = dir === "flat" ? "flat" : (dir === goodWhen ? "up" : "down");
  return <><span className={`delta ${tone}`}><Icon name={dir === "down" ? "down" : "up"} size={12} />{Math.abs(value)}%</span><span>{suffix}</span></>;
}

export function StatCard({ icon, label, value, foot, tone, delta, goodWhen, deltaText, spark, onClick }: {
  icon?: string; label: string; value: React.ReactNode; foot?: React.ReactNode; tone?: "good" | "bad" | "warn" | "info"; delta?: number | null; goodWhen?: "up" | "down"; deltaText?: string; spark?: number[]; onClick?: () => void;
}) {
  return <div className={`stat ${onClick ? "click" : ""}`} onClick={onClick} role={onClick ? "button" : undefined}>
    <div className="stat-h">{icon && <span className={`stat-ic ${tone || ""}`}><Icon name={icon} /></span>}<span>{t(label)}</span>{spark && <Sparkline values={spark} />}</div>
    <div className="stat-v">{value}</div>
    <div className="stat-f">{delta !== undefined && <Delta value={delta} goodWhen={goodWhen} suffix={deltaText} />}{foot}</div>
  </div>;
}

export function Sparkline({ values, tone = "var(--brand)" }: { values: number[]; tone?: string }) {
  if (values.length < 2) return null;
  const max = Math.max(...values), min = Math.min(...values), span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 80 + 2},${24 - ((v - min) / span) * 20}`).join(" ");
  return <svg className="spark" viewBox="0 0 84 26" aria-hidden="true"><polyline points={pts} fill="none" stroke={tone} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

export function Progress({ pct, tone, slim, label }: { pct: number; tone?: "info" | "warn" | "bad"; slim?: boolean; label?: string }) {
  const p = Math.max(0, Math.min(100, Math.round(pct)));
  return <div className={`progress ${tone || ""} ${slim ? "slim" : ""}`} role="progressbar" aria-valuenow={p} aria-valuemin={0} aria-valuemax={100}><i style={{ width: `${p}%` }} /><b>{label ?? `${p}%`}</b></div>;
}

// ------------------------------------------------------------------ tooltip helper
function useTip() {
  const box = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const show = (e: React.MouseEvent, text: string) => {
    const r = box.current?.getBoundingClientRect();
    if (r) setTip({ x: e.clientX - r.left, y: e.clientY - r.top, text });
  };
  const node = tip && <div className="tip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>;
  return { box, show, hide: () => setTip(null), node };
}

// ------------------------------------------------------------------ donut
export type Slice = { label: string; value: number; color?: string; sub?: string };
export function Donut({ data, center, centerSub, fmt = (v: number) => num(v), onSlice, size = 170 }: { data: Slice[]; center?: React.ReactNode; centerSub?: string; fmt?: (v: number) => string; onSlice?: (s: Slice) => void; size?: number }) {
  const tip = useTip();
  const total = data.reduce((a, s) => a + Math.max(0, s.value), 0);
  const R = 70, r = 46, cx = 85, cy = 85;
  let a0 = -Math.PI / 2;
  const arcs = data.map((s, i) => {
    const frac = total ? Math.max(0, s.value) / total : 0;
    const a1 = a0 + frac * Math.PI * 2;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const p = (ang: number, rad: number) => `${cx + rad * Math.cos(ang)},${cy + rad * Math.sin(ang)}`;
    const d = frac >= 0.9999 ? `M${cx},${cy - R}A${R},${R} 0 1 1 ${cx - 0.01},${cy - R}L${cx - 0.01},${cy - r}A${r},${r} 0 1 0 ${cx},${cy - r}Z`
      : `M${p(a0, R)}A${R},${R} 0 ${large} 1 ${p(a1, R)}L${p(a1, r)}A${r},${r} 0 ${large} 0 ${p(a0, r)}Z`;
    const out = { d, s, c: s.color || color(i), frac };
    a0 = a1;
    return out;
  });
  return <div className="donut-box">
    <div className="chart-wrap" ref={tip.box}>
      <svg viewBox="0 0 170 170" style={{ width: size, height: size }} role="img" aria-label={data.map((s) => `${s.label} ${fmt(s.value)}`).join(", ")}>
        {total === 0 && <circle cx={cx} cy={cy} r={(R + r) / 2} fill="none" stroke="var(--line)" strokeWidth={R - r} />}
        {arcs.map((a) => a.frac > 0 && <path key={a.s.label} className="slice" d={a.d} fill={a.c} stroke="var(--panel)" strokeWidth="2" style={{ cursor: onSlice ? "pointer" : "default" }}
          onMouseMove={(e) => tip.show(e, `${a.s.label}: ${fmt(a.s.value)} (${Math.round(a.frac * 100)}%)`)} onMouseLeave={tip.hide} onClick={() => onSlice?.(a.s)} />)}
        {center !== undefined && <text x={cx} y={centerSub ? cy + 2 : cy + 7} textAnchor="middle" className="donut-c1" style={{ fontSize: String(center).length > 7 ? 15 : String(center).length > 5 ? 18 : 22 }}>{center}</text>}
        {centerSub && <text x={cx} y={cy + 20} textAnchor="middle" className="donut-c2">{centerSub}</text>}
      </svg>
      {tip.node}
    </div>
    <div className="donut-legend">{arcs.map((a) => <div key={a.s.label} onClick={() => onSlice?.(a.s)} style={{ cursor: onSlice ? "pointer" : "default" }}>
      <span><i className="sw" style={{ background: a.c }} />{a.s.label}</span><b>{fmt(a.s.value)}</b>{a.s.sub && <small className="muted" style={{ paddingLeft: 17 }}>{a.s.sub}</small>}
    </div>)}</div>
  </div>;
}

// ------------------------------------------------------------------ bar chart (grouped; negative values allowed)
export type Series = { name: string; values: number[]; color?: string; colors?: string[] };
function niceStep(range: number, ticks = 4) {
  const raw = range / ticks, mag = Math.pow(10, Math.floor(Math.log10(raw || 1))), n = raw / mag;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * mag;
}
export function Bars({ labels, series, height = 220, fmt = (v: number) => short(v), axisFmt, legend = true }: { labels: string[]; series: Series[]; height?: number; fmt?: (v: number) => string; axisFmt?: (v: number) => string; legend?: boolean }) {
  const tip = useTip();
  const all = series.flatMap((s) => s.values.map(Number));
  let max = Math.max(0, ...all), min = Math.min(0, ...all);
  if (max === min) max = 1;
  const step = niceStep(max - min);
  max = Math.ceil(max / step) * step; min = Math.floor(min / step) * step;
  const W = Math.max(600, labels.length * Math.max(34, series.length * 16 + 18)), H = height, L = 52, B = 26, T = 8;
  const plotW = W - L - 6, plotH = H - B - T, y = (v: number) => T + ((max - v) / (max - min)) * plotH;
  const group = plotW / Math.max(1, labels.length), bw = Math.min(26, (group - 10) / series.length);
  const maxChars = Math.max(3, Math.floor(group / 6.3));
  const ticks: number[] = [];
  for (let v = min; v <= max + step / 2; v += step) ticks.push(Math.round(v * 100) / 100);
  return <div>
    <div className="bars-scroll"><div className="chart-wrap" ref={tip.box} style={{ minWidth: Math.min(W, 520) }}>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={series.map((s) => s.name).join(", ")}>
        <g className="grid">{ticks.map((v) => <line key={v} x1={L} x2={W - 4} y1={y(v)} y2={y(v)} />)}</g>
        {ticks.map((v) => <text key={v} x={L - 6} y={y(v) + 3.5} textAnchor="end" className="axis">{(axisFmt || fmt)(v)}</text>)}
        <line className="zero" x1={L} x2={W - 4} y1={y(0)} y2={y(0)} />
        {labels.map((lb, i) => {
          const gx = L + i * group + (group - bw * series.length) / 2;
          return <g key={lb + i}>
            {series.map((s, j) => {
              const v = Number(s.values[i] || 0), top = y(Math.max(0, v)), h = Math.abs(y(v) - y(0));
              return <rect key={s.name} className="bar" x={gx + j * bw} y={top} width={Math.max(2, bw - 3)} height={Math.max(v ? 1 : 0, h)} rx="3" fill={s.colors?.[i] || s.color || color(j)}
                onMouseMove={(e) => tip.show(e, `${lb} · ${s.name}: ${fmt(v)}`)} onMouseLeave={tip.hide} />;
            })}
            <text x={L + i * group + group / 2} y={H - 8} textAnchor="middle" className="axis"><title>{lb}</title>{lb.length > maxChars ? lb.slice(0, maxChars - 1) + "…" : lb}</text>
          </g>;
        })}
      </svg>
      {tip.node}
    </div></div>
    {legend && series.length > 1 && <div className="legend">{series.map((s, j) => <span key={s.name}><i className="sw" style={{ background: s.color || color(j) }} />{s.name}</span>)}</div>}
  </div>;
}

// ------------------------------------------------------------------ gauge (0-100)
export function Gauge({ value, label, sub }: { value: number | null; label?: string; sub?: string }) {
  const v = value === null || value === undefined ? null : Math.max(0, Math.min(100, value));
  const cx = 100, cy = 100, R = 80, w = 18;
  const pt = (pct: number, r: number) => { const a = Math.PI * (1 - pct / 100); return [cx + r * Math.cos(a), cy - r * Math.sin(a)]; };
  const arc = (p0: number, p1: number) => { const [x0, y0] = pt(p0, R), [x1, y1] = pt(p1, R); return `M${x0},${y0}A${R},${R} 0 0 1 ${x1},${y1}`; };
  const [nx, ny] = pt(v ?? 0, R - 26);
  const tone = v === null ? "var(--c7)" : v >= 85 ? "var(--c3)" : v >= 70 ? "var(--c2)" : "var(--bad)";
  return <div className="gauge-box">
    <svg viewBox="0 0 200 150" className="chart" style={{ maxWidth: 260 }} role="img" aria-label={`${label || ""} ${v ?? "no data"}%`}>
      <path d={arc(0, 100)} stroke="var(--muted-bg)" strokeWidth={w} fill="none" strokeLinecap="round" />
      {v !== null && v > 0 && <path d={arc(0, v)} stroke={tone} strokeWidth={w} fill="none" strokeLinecap="round" />}
      {v !== null && <><line x1={cx} y1={cy} x2={nx} y2={ny} stroke="var(--ink)" strokeWidth="3" strokeLinecap="round" /><circle cx={cx} cy={cy} r="6" fill="var(--ink)" /></>}
      <text x={cx} y={cy + 44} textAnchor="middle" className="gauge-v">{v === null ? "–" : `${v}%`}</text>
    </svg>
    {label && <div className="muted small" style={{ marginTop: -2 }}>{label}</div>}
    {sub && <div className="muted tiny">{sub}</div>}
  </div>;
}

// ------------------------------------------------------------------ stacked breakdown bar
export function Breakdown({ items, fmt = (v: number) => num(v), onPick }: { items: { label: string; value: number; color: string; sub?: string }[]; fmt?: (v: number) => string; onPick?: (label: string) => void }) {
  const total = items.reduce((a, i) => a + i.value, 0) || 1;
  return <div>
    <div className="stack" role="img" aria-label={items.map((i) => `${i.label} ${fmt(i.value)}`).join(", ")}>{items.map((i) => i.value > 0 && <span key={i.label} title={`${i.label}: ${fmt(i.value)}`} style={{ width: `${(100 * i.value) / total}%`, background: i.color }} />)}</div>
    <div className="stack-legend">{items.map((i) => <button key={i.label} type="button" onClick={() => onPick?.(i.label)} disabled={!onPick}>
      <i className="sw" style={{ background: i.color }} /><span>{i.label}</span><b>{fmt(i.value)}</b>{i.sub && <small>{i.sub}</small>}</button>)}</div>
  </div>;
}

export { inr };
