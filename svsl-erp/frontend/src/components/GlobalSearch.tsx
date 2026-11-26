// Search box in the top bar: vehicles, drivers, customers, vendors, employees, trips, LRs and invoices.
// Each result has quick links (e.g. a vehicle's trips, LRs, diesel, maintenance and expenses). Press "/" to focus.
import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, can } from "../lib/api";
import { Icon } from "./charts";

type Item = { id: number; label: string; sub?: string };
type Group = { kind: string; title: string; items: Item[] };
type Link = [label: string, to: string, perm?: string];

function links(kind: string, id: number): Link[] {
  const L: Record<string, Link[]> = {
    vehicle: [["Profile", `/vehicles?open=vehicles.${id}`, "vehicles:read"], ["Trips", `/trips?vehicle_id=${id}`, "trips:read"], ["LRs", `/lr?vehicle_id=${id}`, "lr:read"],
      ["Diesel", `/fuel?vehicle_id=${id}`, "fuel:read"], ["Maintenance", `/maintenance?vehicle_id=${id}`, "maintenance:read"], ["Expenses", `/vouchers?vehicle_id=${id}`, "accounts:read"]],
    driver: [["Profile", `/drivers?open=drivers.${id}`, "drivers:read"], ["Trips", `/trips?driver_id=${id}`, "trips:read"], ["LRs", `/lr?driver_id=${id}`, "lr:read"], ["Diesel", `/fuel?driver_id=${id}`, "fuel:read"]],
    customer: [["Profile", `/customers?open=customers.${id}`, "customers:read"], ["Trips", `/trips?customer_id=${id}`, "trips:read"], ["LRs", `/lr?customer_id=${id}`, "lr:read"],
      ["Invoices", `/invoices?customer_id=${id}`, "invoices:read"], ["Statement", `/reports?r=customer_statement&customer_id=${id}`, "reports:read"]],
    vendor: [["Profile", `/vendors?open=vendors.${id}`, "vendors:read"], ["Bills", `/purchase?vendor_id=${id}`, "purchase:read"], ["Maintenance", `/maintenance?vendor_id=${id}`, "maintenance:read"]],
    employee: [["Profile", `/employees?open=employees.${id}`, "hr:read"]],
    trip: [["Open", `/trips?id=${id}`, "trips:read"]],
    lr: [["Open", `/lr?id=${id}`, "lr:read"]],
    invoice: [["Open", `/invoices?id=${id}`, "invoices:read"]],
  };
  return (L[kind] || []).filter(([, , p]) => !p || can(p));
}

export default function GlobalSearch() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [open, setOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [sel, setSel] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const timer = useRef<any>();

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) { e.preventDefault(); setMobileOpen(true); input.current?.focus(); }
    };
    const click = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) { setOpen(false); setMobileOpen(false); } };
    window.addEventListener("keydown", key);
    document.addEventListener("mousedown", click);
    return () => { window.removeEventListener("keydown", key); document.removeEventListener("mousedown", click); };
  }, []);

  const search = (text: string) => {
    setQ(text);
    clearTimeout(timer.current);
    if (text.trim().length < 2) { setGroups(null); return; }
    timer.current = setTimeout(() => api.get(`/api/search?q=${encodeURIComponent(text.trim())}`).then((g) => { setGroups(g); setSel(0); setOpen(true); }).catch(() => setGroups([])), 250);
  };
  const flat = (groups || []).flatMap((g) => g.items.map((i) => ({ ...i, kind: g.kind })));
  const go = (to: string) => { setOpen(false); setMobileOpen(false); setQ(""); setGroups(null); nav(to); };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { setOpen(false); setMobileOpen(false); (e.target as HTMLInputElement).blur(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, flat.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
    else if (e.key === "Enter" && flat[sel]) { const l = links(flat[sel].kind, flat[sel].id)[0]; if (l) go(l[1]); }
  };
  let n = -1;
  return <>
    <button className="icon-btn search-toggle" aria-label="Search" onClick={() => { setMobileOpen(!mobileOpen); setTimeout(() => input.current?.focus(), 50); }}><Icon name="search" /></button>
    <div className={`gsearch ${mobileOpen ? "open" : ""}`} ref={box}>
      <Icon name="search" size={16} />
      <input ref={input} type="search" value={q} placeholder="Search vehicle, driver, customer, LR, trip, invoice…  ( / )" aria-label="Search"
        onChange={(e) => search(e.target.value)} onFocus={() => groups && setOpen(true)} onKeyDown={onKey} />
      {open && groups && <div className="gresults" role="listbox">
        {groups.length === 0 && <div className="gempty">Nothing found for “{q}”</div>}
        {groups.map((g) => <div key={g.kind}>
          <h6>{g.title}</h6>
          {g.items.map((i) => {
            n += 1;
            const ls = links(g.kind, i.id);
            const idx = n;
            return <div key={i.id} className={`gitem ${idx === sel ? "sel" : ""}`} onMouseEnter={() => setSel(idx)} onClick={() => ls[0] && go(ls[0][1])} role="option" aria-selected={idx === sel}>
              <b>{i.label}</b>{i.sub && <small>{i.sub}</small>}
              {ls.length > 1 && <div className="glinks">{ls.map(([label, to]) => <a key={to} onClick={(e) => { e.stopPropagation(); go(to); }}>{label}</a>)}</div>}
            </div>;
          })}
        </div>)}
      </div>}
    </div>
  </>;
}
