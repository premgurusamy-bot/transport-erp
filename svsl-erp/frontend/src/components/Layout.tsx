import React, { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, auth, can } from "../lib/api";
import { getLang, setLang, t } from "../lib/i18n";
import { dt } from "../lib/format";
import { Badge } from "./ui";

export type NavItem = { to: string; label: string; perm?: string };
export const NAV: { group: string; items: NavItem[] }[] = [
  { group: "Operations", items: [
    { to: "/", label: "Dashboard", perm: "dashboard:read" },
    { to: "/bookings", label: "Bookings", perm: "bookings:read" },
    { to: "/trips", label: "Trips", perm: "trips:read" },
    { to: "/lr", label: "LR / Consignments", perm: "lr:read" },
    { to: "/fleet-board", label: "Fleet board", perm: "trips:read" },
    { to: "/eway-bills", label: "E-way bills", perm: "lr:read" },
    { to: "/complaints", label: "Complaints", perm: "customers:read" },
  ] },
  { group: "Masters", items: [
    { to: "/customers", label: "Customers", perm: "customers:read" },
    { to: "/vehicles", label: "Vehicles", perm: "vehicles:read" },
    { to: "/drivers", label: "Drivers", perm: "drivers:read" },
    { to: "/vendors", label: "Vendors", perm: "vendors:read" },
    { to: "/routes", label: "Routes", perm: "routes:read" },
    { to: "/rates", label: "Rate contracts", perm: "rates:read" },
  ] },
  { group: "Billing", items: [
    { to: "/invoices", label: "Invoices", perm: "invoices:read" },
    { to: "/receipts", label: "Receipts", perm: "accounts:write" },
  ] },
  { group: "Accounts", items: [
    { to: "/vouchers", label: "Vouchers", perm: "accounts:read" },
    { to: "/ledgers", label: "Ledgers", perm: "accounts:read" },
    { to: "/bank", label: "Bank reconciliation", perm: "accounts:read" },
    { to: "/tally", label: "Tally export / import", perm: "accounts:read" },
  ] },
  { group: "Fleet", items: [
    { to: "/fuel", label: "Diesel & fuel", perm: "fuel:read" },
    { to: "/maintenance", label: "Maintenance", perm: "maintenance:read" },
    { to: "/tyres", label: "Tyres", perm: "maintenance:read" },
    { to: "/tolls", label: "Tolls & FASTag", perm: "routes:read" },
    { to: "/driver-ops", label: "Driver advances & settlement", perm: "drivers:read" },
  ] },
  { group: "Warehouse", items: [
    { to: "/warehouse", label: "Stock", perm: "warehouse:read" },
    { to: "/warehouse-masters", label: "Godowns & items", perm: "warehouse:read" },
  ] },
  { group: "Purchase", items: [
    { to: "/purchase", label: "Vendor bills", perm: "purchase:read" },
  ] },
  { group: "HR", items: [
    { to: "/employees", label: "Employees", perm: "hr:read" },
    { to: "/attendance", label: "Attendance", perm: "hr:read" },
    { to: "/payroll", label: "Payroll", perm: "payroll:read" },
  ] },
  { group: "Compliance", items: [
    { to: "/compliance", label: "Compliance", perm: "compliance:read" },
    { to: "/documents", label: "Documents", perm: "documents:read" },
  ] },
  { group: "Reports", items: [{ to: "/reports", label: "Reports", perm: "reports:read" }] },
  { group: "Admin", items: [
    { to: "/company", label: "Company", perm: "company:read" },
    { to: "/settings", label: "Settings", perm: "settings:read" },
    { to: "/users", label: "Users", perm: "users:read" },
    { to: "/audit", label: "Audit trail", perm: "audit:read" },
    { to: "/backup", label: "Backup", perm: "backup:read" },
  ] },
];

export default function Layout() {
  const nav = useNavigate();
  const loc = useLocation();
  const user = auth.user;
  const [open, setOpen] = useState(false);
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
  const unread = notes.filter((n) => !n.read).length;
  const logout = async () => { await api.post("/api/auth/logout").catch(() => {}); auth.clear(); nav("/login"); };
  return <div className={`shell ${open ? "nav-open" : ""}`}>
    <aside className="side">
      <div className="brand"><img src="/api/company/logo" alt="" onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} /><div><b>SVSL ERP</b><small>Sri Vengarai Suraj Logistics</small></div></div>
      <nav>{NAV.map((g) => {
        const items = g.items.filter((i) => !i.perm || can(i.perm));
        if (!items.length) return null;
        return <div key={g.group} className="nav-g"><div className="nav-gt">{t(g.group)}</div>{items.map((i) => <NavLink key={i.to} to={i.to} end={i.to === "/"}>{t(i.label)}</NavLink>)}</div>;
      })}</nav>
    </aside>
    <div className="main">
      <header className="top">
        <button className="burger" aria-label="Menu" onClick={() => setOpen(!open)}>☰</button>
        <div className="grow" />
        <select aria-label={t("Language")} value={getLang()} onChange={(e) => { setLang(e.target.value); force((x) => x + 1); }}><option value="en">English</option><option value="ta">தமிழ்</option></select>
        <button className="bell" onClick={() => setShowNotes(!showNotes)} aria-label="Notifications">🔔{unread > 0 && <span className="dot">{unread}</span>}</button>
        <NavLink to="/profile" className="who">{user?.full_name} <small>{user?.role}</small></NavLink>
        <button className="btn ghost sm" onClick={logout}>{t("Sign out")}</button>
      </header>
      {showNotes && <div className="notes-pop">
        <div className="row between"><b>{t("Notifications")}</b><button className="btn ghost sm" onClick={() => api.post("/api/notifications/read", {}).then(() => setNotes(notes.map((n) => ({ ...n, read: true }))))}>Mark all read</button></div>
        {notes.length === 0 && <div className="muted">Nothing new</div>}
        {notes.slice(0, 40).map((n) => <div key={n.id} className={`note ${n.read ? "read" : ""}`} onClick={() => { setShowNotes(false); if (n.link) nav(n.link.replace(/\/(\d+)$/, "")); }}>
          <div className="row between"><b>{n.title}</b><Badge v={n.severity} /></div><div className="small">{n.body}</div><div className="muted tiny">{dt(n.at)}</div></div>)}
      </div>}
      <main className="content"><Outlet /></main>
    </div>
  </div>;
}
