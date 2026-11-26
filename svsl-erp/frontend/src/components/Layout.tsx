import React, { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, auth, can } from "../lib/api";
import { dt } from "../lib/format";
import { getLang, setLang, t } from "../lib/i18n";
import { NAV } from "../lib/nav";
import { ACCENTS, getTheme, onThemeChange, setTheme } from "../lib/theme";
import { Icon } from "./charts";
import { Badge } from "./ui";

export { NAV } from "../lib/nav";
export type { NavItem } from "../lib/nav";

/** Theme button + pop-up: light / dark / automatic, accent colour and sidebar style. */
export function ThemePicker() {
  const [open, setOpen] = useState(false);
  const [, force] = useState(0);
  useEffect(() => onThemeChange(() => force((x) => x + 1)), []);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!(e.target as HTMLElement).closest(".theme-pop, .theme-btn")) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  const th = getTheme();
  return <>
    <button className="icon-btn theme-btn" aria-label="Theme" title="Theme" onClick={() => setOpen(!open)}><Icon name="palette" /></button>
    {open && <div className="pop theme-pop" role="dialog" aria-label="Theme">
      <h5>Appearance</h5>
      <div className="seg">{([["light", "sun", "Light"], ["dark", "moon", "Dark"], ["auto", "monitor", "Auto"]] as const).map(([k, ic, l]) =>
        <button key={k} className={th.mode === k ? "on" : ""} onClick={() => setTheme({ mode: k })}><Icon name={ic} size={15} />{l}</button>)}</div>
      <h5>Colour</h5>
      <div className="swatches">{ACCENTS.map((a) => <button key={a.key} className={`swatch ${th.accent === a.key ? "on" : ""}`} title={a.name} aria-label={a.name}
        style={{ background: `linear-gradient(135deg, ${a.light} 50%, ${a.dark} 50%)` }} onClick={() => setTheme({ accent: a.key })} />)}</div>
      <h5>Side menu</h5>
      <div className="seg">{([["light", "Light"], ["dark", "Dark"]] as const).map(([k, l]) => <button key={k} className={th.sidebar === k ? "on" : ""} onClick={() => setTheme({ sidebar: k })}>{l}</button>)}</div>
      <div className="muted tiny">Saved on this device.</div>
    </div>}
  </>;
}

const initials = (s?: string) => (s || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

export default function Layout() {
  const nav = useNavigate();
  const loc = useLocation();
  const user = auth.user;
  const [open, setOpen] = useState(false);
  const [rail, setRail] = useState(() => { try { return localStorage.getItem("svsl_rail") === "1"; } catch { return false; } });
  const [notes, setNotes] = useState<any[]>([]);
  const [showNotes, setShowNotes] = useState(false);
  const [, force] = useState(0);
  useEffect(() => setOpen(false), [loc.pathname]);
  useEffect(() => {
    const load = () => api.get("/api/notifications").then(setNotes).catch(() => {});
    load();
    const id = setInterval(load, 60000);
    return () => clearInterval(id);
  }, []);
  const toggleMenu = () => {
    if (window.matchMedia("(max-width: 900px)").matches) return setOpen(!open);
    const r = !rail; setRail(r);
    try { localStorage.setItem("svsl_rail", r ? "1" : "0"); } catch { /* ignore */ }
  };
  const unread = notes.filter((n) => !n.read).length;
  const logout = async () => { await api.post("/api/auth/logout").catch(() => {}); auth.clear(); nav("/login"); };
  return <div className="app">
    <header className="top">
      <button className="icon-btn burger" aria-label="Menu" onClick={toggleMenu}><Icon name="menu" size={20} /></button>
      <NavLink to="/" className="brand"><img src="/api/company/logo" alt="" onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} /><div><b>SVL ERP</b><small>Sree Venkateswara Logistics</small></div></NavLink>
      <div className="grow" />
      <select className="hide-s" aria-label={t("Language")} value={getLang()} onChange={(e) => { setLang(e.target.value); force((x) => x + 1); }}><option value="en">English</option><option value="ta">தமிழ்</option></select>
      <ThemePicker />
      <button className="icon-btn bell" onClick={() => setShowNotes(!showNotes)} aria-label="Notifications" title={t("Notifications")}><Icon name="bell" />{unread > 0 && <span className="dot">{unread > 99 ? "99+" : unread}</span>}</button>
      <NavLink to="/profile" className="who" title={t("Profile")}><span className="avatar">{initials(user?.full_name)}</span><span><b>{user?.full_name}</b><small>{user?.role}</small></span></NavLink>
      <button className="icon-btn" onClick={logout} aria-label={t("Sign out")} title={t("Sign out")}><Icon name="logout" /></button>
    </header>
    <div className={`shell ${open ? "nav-open" : ""} ${rail ? "rail" : ""}`}>
      <aside className="side" onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}>
        <nav>{NAV.map((g) => {
          const items = g.items.filter((i) => !i.perm || can(i.perm));
          if (!items.length) return null;
          return <div key={g.group} className="nav-g"><div className="nav-gt">{t(g.group)}</div>{items.map((i) => <NavLink key={i.to} to={i.to} title={t(i.label)} end={i.to === "/" || i.to.includes("?")}
            className={({ isActive }) => (isActive && (!i.to.includes("?") || location.search === i.to.slice(i.to.indexOf("?"))) ? "active" : "")}><Icon name={i.icon} /><span>{t(i.label)}</span></NavLink>)}</div>;
        })}</nav>
      </aside>
      <div className="main"><main className="content"><Outlet /></main></div>
    </div>
    {showNotes && <div className="notes-pop">
      <div className="row between" style={{ marginBottom: 6 }}><b>{t("Notifications")}</b><button className="btn ghost sm" onClick={() => api.post("/api/notifications/read", {}).then(() => setNotes(notes.map((n) => ({ ...n, read: true }))))}>Mark all read</button></div>
      {notes.length === 0 && <div className="muted">Nothing new</div>}
      {notes.slice(0, 40).map((n) => <div key={n.id} className={`note ${n.read ? "read" : ""}`} onClick={() => { setShowNotes(false); if (n.link) nav(n.link.replace(/\/(\d+)$/, "")); }}>
        <div className="row between"><b>{n.title}</b><Badge v={n.severity} /></div><div className="small">{n.body}</div><div className="muted tiny">{dt(n.at)}</div></div>)}
    </div>}
  </div>;
}
