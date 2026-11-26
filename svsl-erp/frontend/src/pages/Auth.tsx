import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, auth } from "../lib/api";
import { changeServer, isAndroidApp } from "../lib/native";
import { t } from "../lib/i18n";
import { dt } from "../lib/format";
import { Btn, Card, Field, Page, Table, run, toast, useLoad } from "../components/ui";

export function homeFor(u: any) {
  if (u?.permissions?.includes("portal:access") && u.customer_id) return "/portal";
  if (u?.permissions?.includes("driver_app:access") && u.driver_id) return "/driver";
  return "/";
}

export function Login() {
  const nav = useNavigate();
  const [f, setF] = useState({ username: "", password: "", otp: "" });
  const [needOtp, setNeedOtp] = useState(false);
  const [err, setErr] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    try {
      const r = await api.post("/api/auth/login", { username: f.username, password: f.password, otp: f.otp || undefined });
      auth.save(r.token, r.user);
      nav(r.user.must_change_password ? "/profile?first=1" : homeFor(r.user));
    } catch (ex: any) {
      if (ex.message === "OTP_REQUIRED") { setNeedOtp(true); setErr("Enter the 6-digit code from your authenticator app"); }
      else setErr(ex.message);
    }
  };
  return <div className="login-bg">
    <form className="login" onSubmit={submit}>
      <img src="/api/company/logo" alt="" className="login-logo" onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />
      <h1>Sree Venkateswara Logistics</h1>
      <p className="muted">Transport & Logistics ERP · Coimbatore</p>
      <Field label={t("Username")}><input autoFocus autoComplete="username" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></Field>
      <Field label={t("Password")}><input type="password" autoComplete="current-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
      {needOtp && <Field label="Authenticator code"><input inputMode="numeric" maxLength={6} value={f.otp} onChange={(e) => setF({ ...f, otp: e.target.value })} autoFocus /></Field>}
      {err && <div className="error-box">{err}</div>}
      <button className="btn primary block" type="submit">{t("Sign in")}</button>
      {isAndroidApp && <button type="button" className="btn ghost block" onClick={changeServer}>Change server address</button>}
    </form>
  </div>;
}

/** About & licences: the open-source components the app is built with, and their licence texts. */
function AboutCard() {
  const [text, setText] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const open = async () => {
    try { const r = await fetch("/third-party-licenses.txt"); setText(r.ok ? await r.text() : "The licence file is not available on this server."); } catch { setText("The licence file could not be loaded."); }
  };
  const shown = text && q ? text.split(/\n-{20,}\n/).filter((b) => b.toLowerCase().includes(q.toLowerCase())).join("\n" + "-".repeat(78) + "\n") : text;
  return <Card title="About & licences" actions={text ? <a className="small" href="/third-party-licenses.txt" target="_blank" rel="noreferrer">Open as file</a> : null}>
    <p><b>SVL ERP</b> version 1.0.0 – Transport & Logistics ERP for Sree Venkateswara Logistics.</p>
    <p className="small muted">This software uses open-source components (for example React, FastAPI, SQLAlchemy, PostgreSQL, ReportLab, Electron and Capacitor). They belong to their authors and are used under their licences, whose full texts are listed here.</p>
    {text === null ? <Btn onClick={open}>Show third-party licences</Btn> : <>
      <input type="search" placeholder="Search a component…" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: "100%", marginBottom: 8 }} />
      <pre className="mono small" style={{ maxHeight: 420, overflow: "auto", whiteSpace: "pre-wrap", background: "var(--panel-2)", padding: 12, borderRadius: 8, border: "1px solid var(--line)" }}>{shown}</pre>
    </>}
  </Card>;
}

export function Profile() {
  const first = location.search.includes("first=1");
  const nav = useNavigate();
  const [pw, setPw] = useState({ old_password: "", new_password: "", confirm: "" });
  const [twofa, setTwofa] = useState<any>(null);
  const [code, setCode] = useState("");
  const me = useLoad<any>("/api/auth/me");
  const sessions = useLoad<any[]>("/api/auth/sessions");
  const change = async () => {
    if (pw.new_password !== pw.confirm) return toast.err("New passwords do not match");
    const r = await run(() => api.post("/api/auth/change-password", pw), "Password changed");
    if (r) { const u = { ...auth.user!, must_change_password: false }; auth.setUser(u); if (first) nav(homeFor(u)); }
  };
  return <Page title={t("Profile")}>
    {first && <div className="warn-box">Please set a new password before continuing.</div>}
    <div className="grid2">
      <Card title="Change password">
        <Field label="Current password"><input type="password" value={pw.old_password} onChange={(e) => setPw({ ...pw, old_password: e.target.value })} /></Field>
        <Field label="New password" help="At least 8 characters with letters and numbers"><input type="password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
        <Field label="Confirm new password"><input type="password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} /></Field>
        <Btn kind="primary" onClick={change}>Change password</Btn>
      </Card>
      <Card title="Two-factor authentication">
        {me.data?.totp_enabled ? <>
          <p>Two-factor authentication is <b>enabled</b>.</p>
          <Btn kind="danger" onClick={async () => { const p = prompt("Enter your password to disable 2FA"); if (p && await run(() => api.post("/api/auth/2fa/disable", { password: p }), "2FA disabled")) me.reload(); }}>Disable</Btn>
        </> : twofa ? <>
          <p>Scan with Google Authenticator / Microsoft Authenticator, then enter the 6-digit code.</p>
          <img src={twofa.qr} alt="QR code" width={180} />
          <p className="mono small">{twofa.secret}</p>
          <Field label="Code"><input value={code} onChange={(e) => setCode(e.target.value)} maxLength={6} /></Field>
          <Btn kind="primary" onClick={async () => { if (await run(() => api.post("/api/auth/2fa/enable", { code }), "2FA enabled")) { setTwofa(null); me.reload(); } }}>Enable</Btn>
        </> : <Btn onClick={async () => setTwofa(await run(() => api.post("/api/auth/2fa/setup")))}>Set up 2FA</Btn>}
      </Card>
    </div>
    <Card title="Active sessions">
      <Table cols={[{ key: "created_at", label: "Signed in", type: "datetime" }, { key: "last_seen_at", label: "Last active", type: "datetime" }, { key: "ip", label: "IP" }, { key: "user_agent", label: "Device" },
        { key: "x", label: "", render: (s) => s.current ? <b>This device</b> : <Btn small onClick={async () => { await run(() => api.del(`/api/auth/sessions/${s.full_id}`), "Signed out"); sessions.reload(); }}>Sign out</Btn> }]} rows={sessions.data || []} />
    </Card>
    <AboutCard />
  </Page>;
}

export const fmtDt = dt;
