import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { post } from "../api";
import { homeFor, useAuth } from "../auth";
import { Btn, ErrorBox } from "../components/ui";
import { setLang, t, useLang } from "../i18n";

export default function Login() {
  useLang();
  const { login, otpLogin } = useAuth();
  const nav = useNavigate();
  const [mode, setMode] = useState<"password" | "otp">("password");
  const [id, setId] = useState("");
  const [pw, setPw] = useState("");
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [err, setErr] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const go = async (fn: () => Promise<any>) => {
    setBusy(true);
    setErr(null);
    try { const me = await fn(); if (me) nav(homeFor(me)); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <div className="login-wrap">
      <div className="login card">
        <h1>{t("app.name")}</h1>
        <p className="muted">Transport Business Operating System</p>
        <div className="tabs">
          <button className={mode === "password" ? "on" : ""} onClick={() => setMode("password")}>Staff / Customer / Owner / Vendor</button>
          <button className={mode === "otp" ? "on" : ""} onClick={() => setMode("otp")}>Driver (OTP)</button>
        </div>
        <ErrorBox error={err} />
        {mode === "password" ? (
          <form onSubmit={(e) => { e.preventDefault(); go(() => login(id, pw)); }} className="form">
            <label><span>Email or phone</span><input autoComplete="username" value={id} onChange={(e) => setId(e.target.value)} required /></label>
            <label><span>Password</span><input type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} required /></label>
            <Btn disabled={busy}>{t("action.signIn")}</Btn>
          </form>
        ) : (
          <form onSubmit={(e) => { e.preventDefault(); sent ? go(() => otpLogin(phone, otp)) : go(async () => {
            const r = await post("/auth/otp/request", { phone });
            setSent(r.dev_otp ? `${r.message} (DEVELOPMENT MOCK SMS OTP: ${r.dev_otp})` : r.message);
            return null;
          }); }} className="form">
            <label><span>Mobile number</span><input type="tel" inputMode="numeric" value={phone} onChange={(e) => setPhone(e.target.value)} required /></label>
            {sent && <><p className="small muted">{sent}</p><label><span>OTP</span><input inputMode="numeric" value={otp} onChange={(e) => setOtp(e.target.value)} required /></label></>}
            <Btn disabled={busy}>{sent ? t("action.signIn") : "Send OTP"}</Btn>
          </form>
        )}
        <p className="small"><a onClick={() => setLang("en")}>English</a> · <a onClick={() => setLang("ta")}>தமிழ்</a> · <a href="/">Website</a></p>
      </div>
    </div>
  );
}
