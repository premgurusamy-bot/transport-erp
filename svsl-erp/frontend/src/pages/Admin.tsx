import React, { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, can, qs } from "../lib/api";
import { dt, label } from "../lib/format";
import ResourcePage from "../components/ResourcePage";
import { Badge, Btn, Card, Field, FieldInput, Modal, Page, RefSelect, Table, Tabs, download, run, toast, useLoad } from "../components/ui";

export function Company() {
  const meta = useLoad<any>("/api/company/meta");
  const { data, setData, reload } = useLoad<any>("/api/company");
  const [tab, setTab] = useState("Profile");
  if (!meta.data || !data) return null;
  const groups = [["Profile", ["legal_name", "trade_name", "gstin", "pan", "cin", "gst_registration_type", "gst_registration_date", "authorized_signatory", "signatory_designation"]],
    ["Address & contact", ["address", "city", "state", "state_code", "pincode", "email", "phone", "website"]],
    ["Documents & terms", ["fy_start_month", "terms_lr", "terms_invoice", "lr_print_declaration"]]] as const;
  const fields = meta.data.fields;
  return <Page title="Company">
    <Tabs tabs={["Profile", "Address & contact", "Documents & terms", "Branches & locations", "Bank accounts", "Logo"]} value={tab} onChange={setTab} />
    {groups.map(([g, names]) => tab === g && <Card key={g}><div className="form-grid">
      {names.map((n) => { const f = fields.find((x: any) => x.name === n); return f && <Field key={n} label={f.label} help={f.help} wide={f.type === "text"}>{n === "state_code" ? <select value={data.state_code || ""} onChange={(e) => setData({ ...data, state_code: e.target.value, state: meta.data.states[e.target.value] })}><option value="">—</option>{Object.entries(meta.data.states).map(([c, s]: any) => <option key={c} value={c}>{c} – {s}</option>)}</select> : <FieldInput f={{ ...f, readonly: !can("company:write") }} value={data[n]} onChange={(v) => setData({ ...data, [n]: v })} />}</Field>; })}
    </div>{can("company:write") && <Btn kind="primary" onClick={async () => { const r = await run(() => api.put("/api/company", data), "Company saved"); if (r) setData(r); }}>Save</Btn>}</Card>)}
    {tab === "Branches & locations" && <ResourcePage embedded name="branches" columns={["code", "name", "kind", "city", "state_code", "gstin", "phone", "manager"]} />}
    {tab === "Bank accounts" && <ResourcePage embedded name="bank_accounts" columns={["bank_name", "branch_name", "account_no", "ifsc", "upi_id", "print_on_invoice"]} />}
    {tab === "Logo" && <Card>
      {data.logo_url && <img src={data.logo_url + "?t=" + Date.now()} alt="logo" style={{ maxHeight: 100 }} />}
      {can("company:write") && <input type="file" accept="image/png,image/jpeg" onChange={async (e) => { const f = e.target.files?.[0]; if (!f) return; const fd = new FormData(); fd.append("file", f); if (await run(() => api.form("/api/company/logo", fd), "Logo uploaded")) reload(); }} />}
      <p className="muted small">PNG or JPEG, under 2 MB. Printed on LRs, invoices and reports.</p>
    </Card>}
  </Page>;
}

const SECTION_HELP: Record<string, string> = {
  gst: "GST defaults. Each invoice uses the GST treatment of the contract / customer / this default.", lr: "LR printing and validation rules.", invoice: "Invoice defaults.", accounts: "Books lock date (no posting before this date).",
  alerts: "Alert thresholds.", payroll: "Statutory payroll configuration – verify rates before use.", backup: "Automatic daily backup.", retention: "How long logs are kept.", notifications: "Channels switched on for automatic messages.", branding: "Look & feel.", language: "Languages.",
};

export function Settings() {
  const { data, setData } = useLoad<any>("/api/settings");
  const [tab, setTab] = useState("gst");
  const integ = useLoad<any>("/api/integrations/status");
  const [sub, setSub] = useState("General");
  if (!data) return null;
  const sec = data[tab] || {};
  const save = async () => { const r = await run(() => api.put(`/api/settings/${tab}`, sec), "Settings saved"); if (r) setData({ ...data, [tab]: r }); };
  const set = (k: string, v: any) => setData({ ...data, [tab]: { ...sec, [k]: v } });
  return <Page title="Settings">
    <Tabs tabs={["General", "GST treatments", "Numbering", "Notification templates", "Integrations"]} value={sub} onChange={setSub} />
    {sub === "General" && <div className="settings">
      <nav className="report-list">{Object.keys(data).map((k) => <a key={k} className={k === tab ? "on" : ""} onClick={() => setTab(k)}>{label(k)}</a>)}</nav>
      <Card title={label(tab)} className="grow">
        <p className="muted small">{SECTION_HELP[tab]}</p>
        <div className="form-grid">{Object.entries(sec).map(([k, v]) => <Field key={k} label={label(k)} wide={typeof v === "object" || (typeof v === "string" && v.length > 60)}>
          {typeof v === "boolean" ? <input type="checkbox" checked={v} onChange={(e) => set(k, e.target.checked)} />
            : typeof v === "number" ? <input type="number" step="any" value={v} onChange={(e) => set(k, e.target.value === "" ? "" : Number(e.target.value))} />
              : v !== null && typeof v === "object" ? <textarea className="mono" rows={5} defaultValue={JSON.stringify(v, null, 1)} onBlur={(e) => { try { set(k, JSON.parse(e.target.value)); } catch { toast.err(`${label(k)}: invalid JSON`); } }} />
                : k === "lock_before" ? <input type="date" value={(v as string) || ""} onChange={(e) => set(k, e.target.value || null)} />
                  : <input value={(v as string) ?? ""} onChange={(e) => set(k, e.target.value)} />}
        </Field>)}</div>
        {can("settings:write") && <Btn kind="primary" onClick={save}>Save</Btn>}
      </Card>
    </div>}
    {sub === "GST treatments" && <><div className="warn-box">Seeded GST treatments are defaults and are marked "not verified". Confirm each rate, SAC and mechanism with your GST practitioner, then tick "Verified".</div>
      <ResourcePage embedded name="gst_treatments" columns={["code", "name", "service_type", "sac", "gst_rate", "charge_mechanism", "itc_eligible", "verified", "is_active"]} /></>}
    {sub === "Numbering" && <><p className="muted small">Format tokens: {"{prefix} {fy} {branch} {no}"}. The next number can only be increased, so numbers are never duplicated.</p><ResourcePage embedded name="number_series" columns={["doc_type", "fy", "prefix", "next_no", "padding", "pattern"]} /></>}
    {sub === "Notification templates" && <ResourcePage embedded name="notification_templates" columns={["event", "channel", "recipients", "subject", "body", "is_active"]} />}
    {sub === "Integrations" && integ.data && <Card title="External integrations">
      <Table cols={[{ key: "name", label: "Integration" }, { key: "on", label: "Status", render: (r) => <Badge v={r.on ? "Active" : "Not configured"} /> }, { key: "note", label: "What is needed" }]} rows={[
        { name: "Email (SMTP)", on: integ.data.email, note: "SMTP_HOST, SMTP_FROM (+ user/password) in the server .env" },
        { name: "WhatsApp Business API", on: integ.data.whatsapp, note: "Meta WhatsApp Cloud API token & phone number id; approved message templates for business-initiated messages. Click-to-chat links work without it." },
        { name: "SMS gateway", on: integ.data.sms, note: "DLT-registered sender ID & templates with your SMS provider; gateway URL & key" },
        { name: "E-invoice (IRP / GSP)", on: integ.data.einvoice_irp, note: "API credentials from NIC/IRP or a GSP for your GSTIN. Until then: download JSON → upload on IRP → record IRN." },
        { name: "E-way bill API", on: integ.data.ewaybill_api, note: "E-way bill API credentials (NIC/GSP). Until then: generate on the portal and record the number." },
        { name: "FASTag", on: false, note: integ.data.notes.fastag },
        { name: "GPS vendor", on: false, note: integ.data.notes.gps },
      ]} />
      {can("settings:write") && <TestChannel />}
    </Card>}
  </Page>;
}

function TestChannel() {
  const [f, setF] = useState({ channel: "email", to: "" });
  return <div className="row gap"><select value={f.channel} onChange={(e) => setF({ ...f, channel: e.target.value })}><option value="email">Email</option><option value="whatsapp">WhatsApp</option><option value="sms">SMS</option></select><input placeholder="Recipient" value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} />
    <Btn onClick={async () => { const r: any = await run(() => api.post("/api/notifications/test", f)); if (r) r.status === "sent" ? toast.ok("Sent") : toast.err(`${r.status}: ${r.error || ""}`); }}>Send test</Btn></div>;
}

export function Users() {
  const [sp] = useSearchParams();
  const [tab, setTab] = useState("Users");
  const users = useLoad<any[]>("/api/users");
  const roles = useLoad<any[]>("/api/roles");
  const cat = useLoad<Record<string, string>>(tab === "Roles" ? "/api/roles/catalogue" : null);
  const hist = useLoad<any[]>(tab === "Login history" ? "/api/login-history" : null);
  const sess = useLoad<any[]>(tab === "Sessions" ? "/api/sessions" : null);
  const [u, setU] = useState<any>(sp.get("customer_id") ? { customer_id: Number(sp.get("customer_id")), must_change_password: true } : null);
  const [r, setR] = useState<any>(null);
  const saveUser = async () => { const res = await run(() => (u.id ? api.put(`/api/users/${u.id}`, u) : api.post("/api/users", u)), "Saved"); if (res) { setU(null); users.reload(); } };
  return <Page title="Users" actions={can("users:write") && tab === "Users" && <Btn kind="primary" onClick={() => setU({ must_change_password: true, language: "en" })}>+ User</Btn>}>
    <Tabs tabs={["Users", "Roles", "Login history", "Sessions"]} value={tab} onChange={setTab} />
    {tab === "Users" && <Table cols={[{ key: "username", label: "Username" }, { key: "full_name", label: "Name" }, { key: "role", label: "Role" }, { key: "mobile", label: "Mobile" }, { key: "totp_enabled", label: "2FA", type: "bool" }, { key: "last_login_at", label: "Last login", type: "datetime" }, { key: "is_active", label: "Active", type: "bool" }, { key: "locked", label: "Locked", type: "bool" }]} rows={users.data || []} onRow={can("users:write") ? (x) => setU({ ...x }) : undefined} />}
    {tab === "Roles" && <Table cols={[{ key: "name", label: "Role" }, { key: "description", label: "Description" }, { key: "permissions", label: "Permissions", render: (x) => x.permissions.includes("*") ? "All" : `${x.permissions.length} permissions` }]} rows={roles.data || []} onRow={can("users:write") ? (x) => setR({ ...x }) : undefined} />}
    {tab === "Roles" && can("users:write") && <Btn onClick={() => setR({ name: "", description: "", permissions: [] })}>+ Custom role</Btn>}
    {tab === "Login history" && <Table dense cols={[{ key: "at", label: "When", type: "datetime" }, { key: "username", label: "User" }, { key: "success", label: "OK", type: "bool" }, { key: "reason", label: "Reason" }, { key: "ip", label: "IP" }, { key: "user_agent", label: "Device" }]} rows={hist.data || []} />}
    {tab === "Sessions" && <Table dense cols={[{ key: "username", label: "User" }, { key: "created_at", label: "Signed in", type: "datetime" }, { key: "last_seen_at", label: "Last seen", type: "datetime" }, { key: "ip", label: "IP" }, { key: "x", label: "", render: (s) => can("users:write") && <Btn small onClick={async () => { await run(() => api.del(`/api/auth/sessions/${s.id}`), "Session ended"); sess.reload(); }}>End</Btn> }]} rows={sess.data || []} />}
    {u && <Modal title={u.id ? `Edit ${u.username}` : "New user"} onClose={() => setU(null)} footer={<Btn kind="primary" onClick={saveUser}>Save</Btn>}>
      <div className="form-grid">
        {!u.id && <Field label="Username"><input value={u.username || ""} onChange={(e) => setU({ ...u, username: e.target.value })} /></Field>}
        <Field label="Full name"><input value={u.full_name || ""} onChange={(e) => setU({ ...u, full_name: e.target.value })} /></Field>
        <Field label="Role"><select value={u.role_id || ""} onChange={(e) => setU({ ...u, role_id: Number(e.target.value) })}><option value="">—</option>{(roles.data || []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
        <Field label="Email"><input value={u.email || ""} onChange={(e) => setU({ ...u, email: e.target.value })} /></Field>
        <Field label="Mobile"><input value={u.mobile || ""} onChange={(e) => setU({ ...u, mobile: e.target.value })} /></Field>
        <Field label="Branch"><RefSelect refName="branches" value={u.branch_id} onChange={(v) => setU({ ...u, branch_id: v })} /></Field>
        <Field label="Customer (portal logins)"><RefSelect refName="customers" value={u.customer_id} onChange={(v) => setU({ ...u, customer_id: v })} /></Field>
        <Field label="Driver (driver app logins)"><RefSelect refName="drivers" value={u.driver_id} onChange={(v) => setU({ ...u, driver_id: v })} /></Field>
        <Field label={u.id ? "Reset password (optional)" : "Password"} help="Min 8 chars, letters and numbers"><input type="password" autoComplete="new-password" value={u.password || ""} onChange={(e) => setU({ ...u, password: e.target.value })} /></Field>
        <Field label="Language"><select value={u.language || "en"} onChange={(e) => setU({ ...u, language: e.target.value })}><option value="en">English</option><option value="ta">தமிழ்</option></select></Field>
        {u.id && <Field label="Active"><input type="checkbox" checked={u.is_active} onChange={(e) => setU({ ...u, is_active: e.target.checked })} /></Field>}
        {u.locked && <Field label="Unlock"><input type="checkbox" checked={!!u.unlock} onChange={(e) => setU({ ...u, unlock: e.target.checked })} /></Field>}
        {u.totp_enabled && <Field label="Reset 2FA"><input type="checkbox" checked={!!u.reset_2fa} onChange={(e) => setU({ ...u, reset_2fa: e.target.checked })} /></Field>}
      </div>
    </Modal>}
    {r && cat.data && <Modal wide title={r.id ? `Role – ${r.name}` : "New role"} onClose={() => setR(null)} footer={!r.permissions.includes("*") && <Btn kind="primary" onClick={async () => { if (await run(() => (r.id ? api.put(`/api/roles/${r.id}`, r) : api.post("/api/roles", r)), "Role saved")) { setR(null); roles.reload(); } }}>Save</Btn>}>
      {r.permissions.includes("*") ? <p>This role has full access and cannot be edited.</p> : <>
        {!r.is_system && <Field label="Name"><input value={r.name} onChange={(e) => setR({ ...r, name: e.target.value })} /></Field>}
        <Field label="Description"><input value={r.description || ""} onChange={(e) => setR({ ...r, description: e.target.value })} /></Field>
        <div className="perm-grid">{Object.entries(cat.data).map(([k, v]) => <label key={k} className="row gap small"><input type="checkbox" checked={r.permissions.includes(k)} onChange={(e) => setR({ ...r, permissions: e.target.checked ? [...r.permissions, k] : r.permissions.filter((x: string) => x !== k) })} />{v}</label>)}</div>
      </>}
    </Modal>}
  </Page>;
}

export function Audit() {
  const [f, setF] = useState<any>({ entity: "", username: "", action: "", from: "", to: "" });
  const { data } = useLoad<any>(`/api/audit${qs({ ...f, limit: 300 })}`);
  const [v, setV] = useState<any>(null);
  return <Page title="Audit trail">
    <div className="toolbar">{["entity", "username", "action"].map((k) => <input key={k} placeholder={k} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} />)}<input type="date" value={f.from} onChange={(e) => setF({ ...f, from: e.target.value })} /><input type="date" value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} /></div>
    <Table dense cols={[{ key: "at", label: "When", type: "datetime" }, { key: "username", label: "User" }, { key: "action", label: "Action", type: "badge" }, { key: "entity", label: "Record" }, { key: "entity_id", label: "Id" }, { key: "reason", label: "Reason" }, { key: "ip", label: "IP" }]} rows={data?.items || []} onRow={setV} />
    {v && <Modal wide title={`${v.action} ${v.entity} #${v.entity_id}`} onClose={() => setV(null)}>
      <p className="muted">{dt(v.at)} by {v.username} {v.reason ? `– ${v.reason}` : ""}</p>
      <div className="grid2"><Card title="Before"><pre className="mono small">{JSON.stringify(v.before, null, 1)}</pre></Card><Card title="After"><pre className="mono small">{JSON.stringify(v.after, null, 1)}</pre></Card></div>
    </Modal>}
  </Page>;
}

export function Backup() {
  const { data, reload } = useLoad<any[]>("/api/backups");
  const [restore, setRestore] = useState<any>(null);
  const doRestore = async () => {
    const fd = new FormData();
    fd.append("confirm", restore.confirm || "");
    fd.append("keep_users", String(restore.keep_users !== false));
    if (restore.file) fd.append("file", restore.file); else fd.append("backup_id", String(restore.id));
    const r: any = await run(() => api.form("/api/backups/restore", fd));
    if (r) { toast.ok(`Restored ${r.restored_tables} tables (${r.rows} rows). Safety backup: ${r.pre_restore_backup}`); setRestore(null); reload(); }
  };
  return <Page title="Backup" actions={can("backup:write") && <><Btn kind="primary" onClick={async () => { const r: any = await run(() => api.post("/api/backups", { include_files: true })); if (r) { toast.ok(`Backup ${r.status}: ${r.file_name}`); reload(); } }}>Backup now</Btn>
    <Btn onClick={() => download("/api/export/all")}>Export all data (Excel)</Btn>{can("backup:restore") && <Btn kind="danger" onClick={() => setRestore({ keep_users: true })}>Restore from file</Btn>}</>}>
    <p className="muted small">Each backup is a verified ZIP (every table as JSON with SHA-256 checksums + uploaded documents) and, when PostgreSQL tools are installed, a pg_dump file. Copy backups to another disk / cloud storage regularly. Automatic daily backups are configured in Settings → Backup.</p>
    <Table cols={[{ key: "at", label: "When", type: "datetime" }, { key: "kind", label: "Kind" }, { key: "file_name", label: "File" }, { key: "rows", label: "Rows", type: "number" }, { key: "size_bytes", label: "Bytes", type: "number" }, { key: "status", label: "Status", type: "badge" },
      { key: "x", label: "", render: (b) => <div className="row gap">{can("backup:write") && <Btn small onClick={() => download(`/api/backups/${b.id}/download`)}>ZIP</Btn>}{b.pg_dump_file && can("backup:write") && <Btn small onClick={() => download(`/api/backups/${b.id}/download?kind=dump`)}>pg_dump</Btn>}
        <Btn small kind="ghost" onClick={async () => { const r: any = await run(() => api.post(`/api/backups/${b.id}/verify`)); if (r) r.ok ? toast.ok("Backup verified") : toast.err(r.problems.join("; ")); reload(); }}>Verify</Btn>{can("backup:restore") && <Btn small kind="danger" onClick={() => setRestore({ id: b.id, name: b.file_name, keep_users: true })}>Restore</Btn>}</div> }]} rows={data || []} />
    {restore && <Modal title="Restore database" onClose={() => setRestore(null)} footer={<Btn kind="danger" disabled={restore.confirm !== "RESTORE"} onClick={doRestore}>Restore</Btn>}>
      <div className="warn-box">All business data will be replaced by the backup. An automatic safety backup is taken first. Users, roles, backup history and the audit trail are kept.</div>
      {restore.id ? <p>Backup: <b>{restore.name}</b></p> : <Field label="Backup file (.zip)"><input type="file" accept=".zip" onChange={(e) => setRestore({ ...restore, file: e.target.files?.[0] })} /></Field>}
      <Field label="Keep current users & roles"><input type="checkbox" checked={restore.keep_users} onChange={(e) => setRestore({ ...restore, keep_users: e.target.checked })} /></Field>
      <Field label="Type RESTORE to confirm"><input value={restore.confirm || ""} onChange={(e) => setRestore({ ...restore, confirm: e.target.value })} /></Field>
    </Modal>}
  </Page>;
}
