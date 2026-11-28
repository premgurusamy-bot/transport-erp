import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, auth } from "../lib/api";
import { loadAppInfo, loadLicence } from "../lib/appinfo";
import { Field } from "../components/ui";

/** First start of a new installation: the customer's company and the first administrator. */
export default function Setup() {
  const nav = useNavigate();
  const [info, setInfo] = useState<any>(null);
  const [step, setStep] = useState(1);
  const [c, setC] = useState<any>({ legal_name: "", trade_name: "", gstin: "", phone: "", email: "", address: "", city: "", state_code: "", pincode: "" });
  const [a, setA] = useState<any>({ full_name: "", username: "admin", password: "", confirm: "" });
  const [sample, setSample] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { loadAppInfo(true).then((i) => { if (!i.setup_needed) nav("/login", { replace: true }); else setInfo(i); }); }, []);
  if (!info) return <div className="login-bg" />;
  const next = (e: React.FormEvent) => {
    e.preventDefault(); setErr("");
    if (c.legal_name.trim().length < 2) return setErr("Enter the company name");
    if (c.gstin && c.state_code && c.gstin.slice(0, 2) !== c.state_code) return setErr("The GSTIN does not match the selected state");
    setStep(2);
  };
  const finish = async (e: React.FormEvent) => {
    e.preventDefault(); setErr("");
    if (!a.full_name.trim()) return setErr("Enter your name");
    if (a.password !== a.confirm) return setErr("The passwords do not match");
    setBusy(true);
    try {
      const r = await api.post("/api/setup", { company: c, admin: a, sample_data: sample });
      auth.save(r.token, r.user);
      await loadAppInfo(true); await loadLicence(true);
      nav("/", { replace: true });
    } catch (ex: any) { setErr(ex.message); } finally { setBusy(false); }
  };
  const up = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setC({ ...c, [k]: e.target.value });
  return <div className="login-bg">
    <form className="login setup" onSubmit={step === 1 ? next : finish}>
      <div className="login-brand"><img src="/brand/logo-wordmark.png" alt="A Prime Transport ERP – Transport Management Software" /></div>
      <div className="steps-mini"><span className={step === 1 ? "on" : "done"}>1 · Your company</span><span className={step === 2 ? "on" : ""}>2 · Administrator</span></div>
      {!info.setup_allowed_here ? <div className="warn-box">This is a new installation. Finish the first-time setup on the main ERP computer (open A Prime Transport ERP there).</div>
        : step === 1 ? <>
          <h1>Welcome! Let's set up your company</h1>
          <p className="muted small">This name and address are printed on LRs, invoices and reports. You can change everything later in Admin → Company.</p>
          <Field label="Company legal name" required><input autoFocus value={c.legal_name} onChange={up("legal_name")} placeholder="e.g. Sri Murugan Transports" /></Field>
          <Field label="Trade name (if different)"><input value={c.trade_name} onChange={up("trade_name")} /></Field>
          <div className="grid2 tight">
            <Field label="State"><select value={c.state_code} onChange={up("state_code")}><option value="">—</option>{Object.entries(info.states || {}).map(([k, s]: any) => <option key={k} value={k}>{s}</option>)}</select></Field>
            <Field label="City"><input value={c.city} onChange={up("city")} /></Field>
          </div>
          <Field label="GSTIN (optional)"><input value={c.gstin} maxLength={15} onChange={(e) => setC({ ...c, gstin: e.target.value.toUpperCase() })} /></Field>
          <Field label="Address"><textarea rows={2} value={c.address} onChange={up("address")} /></Field>
          <div className="grid2 tight">
            <Field label="Phone"><input value={c.phone} onChange={up("phone")} /></Field>
            <Field label="Email"><input type="email" value={c.email} onChange={up("email")} /></Field>
          </div>
          {err && <div className="error-box">{err}</div>}
          <button className="btn primary block" type="submit">Next</button>
        </> : <>
          <h1>Create your administrator login</h1>
          <p className="muted small">This person can do everything, including adding the other users. Keep the password safe.</p>
          <Field label="Your name" required><input autoFocus value={a.full_name} onChange={(e) => setA({ ...a, full_name: e.target.value })} /></Field>
          <Field label="Username" required><input autoComplete="username" value={a.username} onChange={(e) => setA({ ...a, username: e.target.value.toLowerCase() })} /></Field>
          <Field label="Password" required help="At least 8 characters, with letters and numbers"><input type="password" autoComplete="new-password" value={a.password} onChange={(e) => setA({ ...a, password: e.target.value })} /></Field>
          <Field label="Confirm password" required><input type="password" autoComplete="new-password" value={a.confirm} onChange={(e) => setA({ ...a, confirm: e.target.value })} /></Field>
          <label className="check-line"><input type="checkbox" checked={sample} onChange={(e) => setSample(e.target.checked)} /> Fill with DEMO data to explore (three months of sample trips, invoices and accounts – remove it later with Admin → Backup → Factory reset)</label>
          {err && <div className="error-box">{err}</div>}
          <button className="btn primary block" type="submit" disabled={busy}>{busy ? (sample ? "Creating sample data…" : "Setting up…") : "Start using A Prime Transport ERP"}</button>
          <button className="btn ghost block" type="button" onClick={() => { setErr(""); setStep(1); }}>Back</button>
        </>}
      <p className="muted tiny" style={{ textAlign: "center", marginBottom: 0 }}>Includes a free trial. Your provider gives you a licence key to continue after it.</p>
    </form>
  </div>;
}
