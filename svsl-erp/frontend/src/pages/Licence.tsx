import React, { useState } from "react";
import { NavLink } from "react-router-dom";
import { api, can } from "../lib/api";
import { Licence, loadLicence, useLicence } from "../lib/appinfo";
import { Btn, Card, Kpi, Page, toast } from "../components/ui";
import { Icon } from "../components/charts";

const d = (v?: string | null) => (v ? new Date(v + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—");

const STATE_LABEL: Record<string, [string, string]> = {
  trial: ["Free trial", "warn"], active: ["Licensed", "good"], grace: ["Renewal due", "warn"],
  expired: ["Expired – read-only", "bad"], trial_expired: ["Trial ended – read-only", "bad"], clock_error: ["Check computer date", "bad"],
};

/** Strip above every screen while on trial, close to renewal, in the grace period or read-only. */
export function LicenceBanner() {
  const l = useLicence();
  if (!l) return null;
  const soon = l.state === "active" && l.days_left !== null && l.days_left <= 15;
  if (l.state === "active" && !soon) return null;
  const tone = l.read_only ? "bad" : l.state === "trial" ? "info" : "warn";
  return <div className={`lic-banner ${tone}`} role="status">
    <Icon name={l.read_only ? "alert" : "clock"} size={16} />
    <span>{l.message}</span>
    {can("settings:read") && <NavLink to="/licence" className="btn sm">{l.read_only || l.state === "grace" ? "Enter licence key" : "Licence"}</NavLink>}
  </div>;
}

export default function LicencePage() {
  const l = useLicence();
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  if (!l) return <Page title="Licence"><Card>Loading…</Card></Page>;
  const [label, tone] = STATE_LABEL[l.state] || [l.state, "warn"];
  const activate = async () => {
    setBusy(true);
    try {
      await api.post("/api/licence/activate", { key });
      const n = await loadLicence(true);
      setKey("");
      toast.ok(n?.licensed_to ? `Licence activated for ${n.licensed_to}` : "Licence activated");
    } catch (e: any) { toast.err(e.message); } finally { setBusy(false); }
  };
  const copy = () => { navigator.clipboard?.writeText(l.install_id || "").then(() => toast.ok("Installation ID copied"), () => toast.err("Copy it by hand")); };
  return <Page title="Licence" sub="Your A Prime Transport ERP subscription">
    <div className="kpis">
      <Kpi label="Status" value={label} tone={tone as any} />
      <Kpi label={l.state === "trial" || l.state === "trial_expired" ? "Trial ends" : "Valid until"} value={l.state.startsWith("trial") ? d(l.trial_ends) : l.valid_until ? d(l.valid_until) : l.licence_id ? "Lifetime" : "—"}
        sub={l.days_left !== null && !l.read_only ? `${l.days_left} day${l.days_left === 1 ? "" : "s"} left` : undefined} tone={l.read_only ? "bad" : undefined} />
      <Kpi label="Plan" value={l.plan_label || (l.state.startsWith("trial") ? `${l.trial_days}-day trial` : "—")} />
      <Kpi label="Staff users" value={l.max_users ? `Up to ${l.max_users}` : "Unlimited"} sub="Customer-portal and driver-app logins are not counted" />
    </div>
    <div className={l.read_only ? "error-box" : "calc"} style={{ marginBottom: 12 }}>{l.message}{l.key_error && <><br /><b>Saved key:</b> {l.key_error}</>}</div>
    <div className="grid2">
      <Card title="Licence details">
        {l.install_id && <div className="install-id"><span className="muted small">Installation ID</span><div className="row gap"><b className="mono">{l.install_id}</b><Btn small onClick={copy}>Copy</Btn></div></div>}
        <div className="kv">
          <div><span>Licensed to</span><b>{l.licensed_to || "—"}</b></div>
          <div><span>Licence number</span><b className="mono">{l.licence_id || "—"}</b></div>
          <div><span>Period</span><b>{l.valid_from ? `${d(l.valid_from)} – ${l.valid_until ? d(l.valid_until) : "no end date"}` : "—"}</b></div>
          <div><span>First started on this computer</span><b>{d(l.first_seen)}</b></div>
        </div>
        <p className="small muted">When the period ends you have {l.grace_days} more days to renew. After that the ERP becomes <b>read-only</b>: everything can still be viewed, searched, printed, exported and backed up, but nothing new can be entered until a renewal key is added. No data is ever deleted.</p>
      </Card>
      <Card title="Enter a licence key">
        {can("settings:write") ? <>
          <ol className="small steps-list">
            <li>Send the <b>Installation ID</b> above to your A Prime Transport ERP provider, with your company name and the plan you want.</li>
            <li>Paste the licence key you receive here and press <b>Activate</b>. No internet connection is needed.</li>
          </ol>
          <textarea className="mono" rows={5} style={{ width: "100%" }} placeholder="APRIME1.…" value={key} onChange={(e) => setKey(e.target.value)} />
          <Btn kind="primary" disabled={!key.trim() || busy} onClick={activate}>{busy ? "Checking…" : "Activate"}</Btn>
        </> : <p className="small">Ask your administrator to enter the licence key.</p>}
      </Card>
    </div>
  </Page>;
}

export type { Licence };
