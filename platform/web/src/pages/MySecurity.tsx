import { useState } from "react";
import { post } from "../api";
import { useAuth } from "../auth";
import { Btn, Card, ErrorBox, toast } from "../components/ui";

export default function MySecurity() {
  const { me } = useAuth();
  const [setup, setSetup] = useState<any>(null);
  const [code, setCode] = useState("");
  const [err, setErr] = useState<any>(null);
  const [on, setOn] = useState(!!me?.mfa_enabled);
  const pw = async () => {
    const cur = prompt("Current password"); const nw = cur && prompt("New password (10+ characters, letters and digits)");
    if (cur && nw) { try { await post("/auth/change-password", { current_password: cur, new_password: nw }); toast("Password changed; other sessions signed out"); } catch (e: any) { toast(e.message, "red"); } }
  };
  return (
    <div className="stack">
      <Card title="Two-step sign-in (authenticator app)" note="Recommended for Owner/Director, Accounts and administrators. Works with Google Authenticator, Microsoft Authenticator and similar apps.">
        <ErrorBox error={err} />
        {on ? <>
          <p>Two-step sign-in is <b>ON</b>. To turn it off, enter a current code.</p>
          <input inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} placeholder="6-digit code" />
          <Btn kind="danger" onClick={async () => { try { await post("/auth/mfa/disable", { code }); setOn(false); setCode(""); toast("Turned off"); } catch (e) { setErr(e); } }}>Turn off</Btn>
        </> : !setup ? <Btn onClick={async () => { try { setSetup(await post("/auth/mfa/setup")); } catch (e) { setErr(e); } }}>Set up</Btn> : <>
          <p>1. In your authenticator app choose <b>Enter a setup key</b> and type: <code className="mono">{setup.secret}</code> (time-based).</p>
          <p className="small muted">Or open this link on the phone: <code className="mono small">{setup.otpauth_uri}</code></p>
          <p>2. Enter the 6-digit code shown in the app:</p>
          <input inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} placeholder="6-digit code" />
          <Btn onClick={async () => { try { await post("/auth/mfa/enable", { code }); setOn(true); setSetup(null); setCode(""); toast("Two-step sign-in enabled"); } catch (e) { setErr(e); } }}>Confirm</Btn>
          <p className="small muted">Lost phone? An administrator can reset two-step sign-in after verifying your identity in person.</p>
        </>}
      </Card>
      <Card title="Password"><Btn kind="ghost" onClick={pw}>Change password</Btn></Card>
    </div>
  );
}
