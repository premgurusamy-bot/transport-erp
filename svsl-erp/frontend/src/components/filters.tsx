// Vehicle-wise / driver-wise / customer-wise … filters for list screens. Values live in the page address
// (e.g. /trips?vehicle_id=3&from=2026-11-01), so a filtered list can be bookmarked, shared or opened from the search.
import React from "react";
import { useSearchParams } from "react-router-dom";
import { Icon } from "./charts";
import { RefSelect } from "./ui";

export type FilterSpec = { key: string; label: string; ref?: string; type?: "date" | "select"; options?: (string | [string, string])[] };

export const F = {
  vehicle: { key: "vehicle_id", label: "Vehicle", ref: "vehicles" } as FilterSpec,
  driver: { key: "driver_id", label: "Driver", ref: "drivers" } as FilterSpec,
  customer: { key: "customer_id", label: "Customer", ref: "customers" } as FilterSpec,
  vendor: { key: "vendor_id", label: "Vendor", ref: "vendors" } as FilterSpec,
  route: { key: "route_id", label: "Route", ref: "routes" } as FilterSpec,
  ledger: { key: "ledger_id", label: "Ledger", ref: "ledgers" } as FilterSpec,
  from: { key: "from", label: "From", type: "date" } as FilterSpec,
  to: { key: "to", label: "To", type: "date" } as FilterSpec,
};

/** Read and change filter values kept in the URL. Setting a filter keeps the other URL parameters (tabs, open record). */
export function useUrlFilters(specs: FilterSpec[]): [Record<string, string>, (k: string, v: string | number | null) => void, () => void] {
  const [sp, setSp] = useSearchParams();
  const values: Record<string, string> = {};
  for (const s of specs) {
    const v = sp.get(s.key);
    if (v) values[s.key] = v;
  }
  const set = (k: string, v: string | number | null) => {
    const next = new URLSearchParams(sp);
    if (v === null || v === "" || v === undefined) next.delete(k); else next.set(k, String(v));
    setSp(next, { replace: true });
  };
  const clear = () => {
    const next = new URLSearchParams(sp);
    specs.forEach((s) => next.delete(s.key));
    setSp(next, { replace: true });
  };
  return [values, set, clear];
}

export function FilterBar({ specs, values, set, clear }: { specs: FilterSpec[]; values: Record<string, string>; set: (k: string, v: any) => void; clear: () => void }) {
  const active = Object.keys(values).length;
  return <div className="filter-bar">
    <span className="filter-ic" title="Filters"><Icon name="search" size={16} /></span>
    {specs.map((s) => <label key={s.key} className={`fchip ${values[s.key] ? "on" : ""}`}>
      <span>{s.label}</span>
      {s.ref ? <RefSelect refName={s.ref} value={values[s.key] ? Number(values[s.key]) : null} onChange={(v) => set(s.key, v)} placeholder="All" />
        : s.type === "date" ? <input type="date" value={values[s.key] || ""} onChange={(e) => set(s.key, e.target.value)} />
        : <select value={values[s.key] || ""} onChange={(e) => set(s.key, e.target.value)}><option value="">All</option>{(s.options || []).map((o) => Array.isArray(o) ? <option key={o[0]} value={o[0]}>{o[1]}</option> : <option key={o}>{o}</option>)}</select>}
    </label>)}
    {active > 0 && <button type="button" className="btn ghost sm" onClick={clear}>Clear {active > 1 ? `${active} filters` : "filter"}</button>}
  </div>;
}
