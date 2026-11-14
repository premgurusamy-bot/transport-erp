import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { get, post, put } from "../api";
import { useAuth } from "../auth";
import { enumOpts, opts, ResourcePage, useLookup } from "../components/Resource";
import { Badge, Btn, Card, dt, Form, Modal, Table, toast, useData } from "../components/ui";
import { SubNav } from "./ErpApp";

export default function Admin() {
  const { can } = useAuth();
  return (
    <div className="stack">
      <SubNav items={[{ to: "/erp/admin", label: "Customers" }, { to: "/erp/admin/masters", label: "Other masters", show: can("masters.read") },
        { to: "/erp/admin/users", label: "Users & roles", show: can("users.manage") }, { to: "/erp/admin/settings", label: "Settings", show: can("settings.read") },
        { to: "/erp/admin/audit", label: "Audit", show: can("audit.read") }, { to: "/erp/admin/integrations", label: "Integrations" },
        { to: "/erp/admin/notifications", label: "Messages", show: can("settings.read") }]} />
      <Routes>
        <Route index element={<Customers />} />
        <Route path="masters" element={<Masters />} />
        <Route path="users" element={<Users />} />
        <Route path="settings" element={<Settings />} />
        <Route path="audit" element={<Audit />} />
        <Route path="integrations" element={<Integrations />} />
        <Route path="notifications" element={<Notifications />} />
      </Routes>
    </div>
  );
}

function Customers() {
  const { can } = useAuth();
  const [credit, setCredit] = useState<any>(null);
  return (
    <div className="stack">
      <ResourcePage title="Customers" path="/masters/customers" canWrite={can("masters.write")}
        note="Duplicates are detected by normalised name and GSTIN. GSTIN is checked offline for format/check digit only (not official verification)."
        cols={[{ key: "code", label: "Code" }, { key: "name", label: "Name" }, { key: "gstin", label: "GSTIN" }, { key: "gst_mode", label: "GST" },
          { key: "billing_cycle", label: "Billing" }, { key: "status", label: "Status", badge: true },
          { key: "c", label: "", render: (r: any) => can("credit.read") && <Btn kind="ghost" onClick={(e) => { e.stopPropagation(); setCredit(r); }}>Credit</Btn> }]}
        fields={[{ name: "name", label: "Legal name", required: true }, { name: "gstin", label: "GSTIN" }, { name: "pan", label: "PAN" }, { name: "group_name", label: "Group" },
          { name: "billing_address", label: "Billing address", type: "textarea" }, { name: "phone", label: "Phone", type: "tel" }, { name: "email", label: "Email", type: "email" },
          { name: "gst_mode", label: "GST mode (verify with CA)", type: "select", options: enumOpts("RCM", "FCM") },
          { name: "billing_cycle", label: "Billing cycle", type: "select", options: enumOpts("per_lr", "per_trip", "weekly", "monthly") },
          { name: "status", label: "Status", type: "select", options: enumOpts("prospect", "active", "on_hold", "inactive") },
          { name: "confirm_not_duplicate", label: "I confirm this is not a duplicate", type: "checkbox" }]} />
      {credit && <CreditModal customer={credit} onClose={() => setCredit(null)} />}
    </div>
  );
}

function CreditModal({ customer, onClose }: { customer: any; onClose: () => void }) {
  const { can } = useAuth();
  const { data } = useData(() => get(`/customers/${customer.id}/credit`), [customer.id]);
  return (
    <Modal title={`Credit - ${customer.name}`} onClose={onClose}>
      {data && <dl className="dl">{Object.entries(data.exposure).map(([k, v]: any) => <><dt key={k}>{k.replace(/_/g, " ")}</dt><dd>{String(v)}</dd></>)}</dl>}
      <Table rows={data?.profiles} cols={[{ key: "limit_amount", label: "Limit", money: true }, { key: "credit_days", label: "Days" }, { key: "advance_pct", label: "Advance %" },
        { key: "status", label: "Status", badge: true }, { key: "effective_from", label: "From", date: true }]} />
      {can("credit.write") && <Form fields={[{ name: "limit_amount", label: "Limit ₹", type: "number", required: true }, { name: "credit_days", label: "Days", type: "number", required: true },
        { name: "advance_pct", label: "Advance %", type: "number" }, { name: "deposit_amount", label: "Deposit ₹", type: "number" },
        { name: "risk_category", label: "Risk", type: "select", options: enumOpts("low", "medium", "high") }, { name: "reason", label: "Reason", required: true }]}
        submitLabel="Propose (needs credit approval)" onSubmit={async (v) => { await post("/credit-profiles", { customer_id: customer.id, ...v }); toast("Sent for approval"); onClose(); }} />}
    </Modal>
  );
}

function Masters() {
  const { can } = useAuth();
  const w = can("masters.write");
  const lk = useLookup();
  const [tab, setTab] = useState("locations");
  return (
    <div className="stack">
      <div className="tabs">{["locations", "route-distances", "goods-categories", "charge-types", "reason-codes", "vehicle-types", "facilities", "company-bank-accounts"].map((t) =>
        <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t.replace(/-/g, " ")}</button>)}</div>
      {tab === "locations" && <ResourcePage title="Locations" path="/masters/locations" canWrite={w} note="Only service-verified locations are shown on the website."
        cols={[{ key: "city", label: "City" }, { key: "district", label: "District" }, { key: "state", label: "State" }, { key: "pincode", label: "PIN" }, { key: "service_verified", label: "Verified coverage" }]}
        fields={[{ name: "city", label: "City", required: true }, { name: "district", label: "District" }, { name: "state", label: "State", required: true }, { name: "state_code", label: "GST state code" },
          { name: "pincode", label: "PIN" }, { name: "lat", label: "Latitude", type: "number" }, { name: "lng", label: "Longitude", type: "number" },
          { name: "service_verified", label: "Service verified (route, partner, capacity)", type: "checkbox" }, { name: "service_notes", label: "Notes", type: "textarea" }]} />}
      {tab === "route-distances" && <ResourcePage title="Lane distances" path="/masters/route-distances" canWrite={w}
        cols={[{ key: "origin_id", label: "From", render: (r: any) => lk.data?.locations.find((l: any) => l.id === r.origin_id)?.label }, { key: "destination_id", label: "To", render: (r: any) => lk.data?.locations.find((l: any) => l.id === r.destination_id)?.label },
          { key: "km", label: "Km" }, { key: "toll_estimate", label: "Toll est.", money: true }, { key: "source", label: "Source" }]}
        fields={[{ name: "origin_id", label: "From", type: "select", options: opts(lk.data?.locations), required: true }, { name: "destination_id", label: "To", type: "select", options: opts(lk.data?.locations), required: true },
          { name: "km", label: "Km", type: "number", required: true }, { name: "toll_estimate", label: "Toll ₹", type: "number" }, { name: "restrictions", label: "Restrictions", type: "textarea" }]} />}
      {tab === "goods-categories" && <ResourcePage title="Goods categories" path="/masters/goods-categories" canWrite={w} note="Tags drive the PTL compatibility engine."
        cols={[{ key: "code", label: "Code" }, { key: "name", label: "Name" }, { key: "hazard_class", label: "Hazard" }, { key: "tags", label: "Tags", render: (r: any) => r.tags.join(", ") },
          { key: "incompatible_tags", label: "Incompatible with", render: (r: any) => r.incompatible_tags.join(", ") }, { key: "ptl_allowed", label: "PTL allowed" }]}
        fields={[{ name: "code", label: "Code", required: true }, { name: "name", label: "Name", required: true }, { name: "hazard_class", label: "Hazard class" },
          { name: "ptl_allowed", label: "Allowed in shared loads", type: "checkbox" }, { name: "requires_special_approval", label: "Needs special approval", type: "checkbox" }]} />}
      {tab === "charge-types" && <ResourcePage title="Charge types" path="/masters/charge-types" canWrite={w} cols={[{ key: "code", label: "Code" }, { key: "name", label: "Name" }, { key: "kind", label: "Kind" }, { key: "gst_applicable", label: "GST" }]}
        fields={[{ name: "code", label: "Code", required: true }, { name: "name", label: "Name", required: true }, { name: "kind", label: "Kind", type: "select", options: enumOpts("freight", "accessorial", "pass_through"), required: true }, { name: "gst_applicable", label: "GST applicable", type: "checkbox" }]} />}
      {tab === "reason-codes" && <ResourcePage title="Reason codes" path="/masters/reason-codes" canWrite={w} cols={[{ key: "category", label: "Category" }, { key: "code", label: "Code" }, { key: "label", label: "Label" }, { key: "label_ta", label: "தமிழ்" }]}
        fields={[{ name: "category", label: "Category", type: "select", options: enumOpts("cancellation", "delay", "claim", "exception", "override"), required: true }, { name: "code", label: "Code", required: true }, { name: "label", label: "Label", required: true }, { name: "label_ta", label: "Tamil label" }]} />}
      {tab === "vehicle-types" && <ResourcePage title="Vehicle types" path="/masters/vehicle-types" canWrite={w} cols={[{ key: "code", label: "Code" }, { key: "name", label: "Name" }, { key: "body_type", label: "Body" }, { key: "nominal_tons", label: "Nominal t" }]}
        fields={[{ name: "code", label: "Code", required: true }, { name: "name", label: "Name", required: true }, { name: "body_type", label: "Body", required: true }, { name: "nominal_tons", label: "Nominal tons", type: "number", required: true }, { name: "length_ft", label: "Length ft", type: "number" }]} />}
      {tab === "facilities" && <ResourcePage title="Facilities" path="/masters/facilities" canWrite={w} note="Mark verified only after professional verification of approved use, fire safety, structure, access and local authority requirements."
        cols={[{ key: "code", label: "Code" }, { key: "name", label: "Name" }, { key: "kind", label: "Kind" }, { key: "verified", label: "Verified" }, { key: "max_vehicle_type", label: "Access" }]}
        fields={[{ name: "code", label: "Code", required: true }, { name: "name", label: "Name", required: true }, { name: "kind", label: "Kind", type: "select", options: enumOpts("office", "godown", "partner_warehouse", "cross_dock"), required: true },
          { name: "address", label: "Address", type: "textarea" }, { name: "verified", label: "Verified", type: "checkbox" }, { name: "verification_notes", label: "Verification evidence", type: "textarea" }]} />}
      {tab === "company-bank-accounts" && <ResourcePage title="Company bank & cash accounts" path="/masters/company-bank-accounts" canWrite={can("accounts.approve")}
        cols={[{ key: "name", label: "Name" }, { key: "bank_name", label: "Bank" }, { key: "account_number_masked", label: "Account" }, { key: "ledger_code", label: "Ledger" }, { key: "opening_balance", label: "Opening", money: true }]}
        fields={[{ name: "name", label: "Name", required: true }, { name: "bank_name", label: "Bank", required: true }, { name: "account_number_masked", label: "Account (masked, e.g. XXXX1234)", required: true },
          { name: "ifsc", label: "IFSC" }, { name: "ledger_code", label: "Ledger code", required: true }, { name: "opening_balance", label: "Opening balance ₹", type: "number" }, { name: "opening_date", label: "Opening date", type: "date" }]} />}
    </div>
  );
}

function Users() {
  const users = useData(() => get("/users"), []);
  const roles = useData(() => get("/roles"), []);
  const lk = useLookup();
  const [adding, setAdding] = useState(false);
  const [roleView, setRoleView] = useState<any>(null);
  return (
    <div className="stack">
      <Card title="Users" note="Role changes and deactivation revoke sessions immediately." actions={<Btn onClick={() => setAdding(true)}>+ User</Btn>}>
        <Table rows={users.data} cols={[{ key: "name", label: "Name" }, { key: "email", label: "Email" }, { key: "phone", label: "Phone" }, { key: "roles", label: "Roles", render: (r: any) => r.roles.join(", ") },
          { key: "is_active", label: "Active" }, { key: "last_login_at", label: "Last login", date: true }, { key: "access_valid_to", label: "Access until", date: true },
          { key: "a", label: "", render: (r: any) => r.is_active && <Btn kind="ghost" onClick={async () => { const reason = prompt("Reason for deactivation"); if (reason) { try { await post(`/users/${r.id}/deactivate`, { roles: [], reason }); users.reload(); } catch (e: any) { toast(e.message, "red"); } } }}>Deactivate</Btn> }]} />
      </Card>
      <Card title="Roles"><Table rows={roles.data?.roles} onRow={setRoleView} cols={[{ key: "name", label: "Role" }, { key: "code", label: "Code" }, { key: "is_external", label: "External" },
        { key: "permissions", label: "Permissions", render: (r: any) => `${r.permissions.length} permissions` }]} /></Card>
      {roleView && <Modal title={roleView.name} onClose={() => setRoleView(null)}><ul className="cols">{roleView.permissions.map((p: string) => <li key={p} title={roles.data.permissions[p]}>{p}</li>)}</ul></Modal>}
      {adding && <Modal title="New user" onClose={() => setAdding(false)}>
        <Form fields={[{ name: "name", label: "Name", required: true }, { name: "email", label: "Email", type: "email" }, { name: "phone", label: "Phone (OTP)", type: "tel" },
          { name: "password", label: "Initial password (10+ chars, letter and digit)", type: "password" },
          { name: "role", label: "Role", type: "select", options: (roles.data?.roles || []).map((r: any) => ({ value: r.code, label: r.name })), required: true },
          { name: "customer_id", label: "Customer (customer users)", type: "select", options: opts(lk.data?.customers) },
          { name: "owner_id", label: "Owner (owner users)", type: "select", options: opts(lk.data?.owners) },
          { name: "vendor_id", label: "Vendor (vendor users)", type: "select", options: opts(lk.data?.vendors) },
          { name: "access_valid_to", label: "Access valid until (CA/auditor)", type: "datetime-local" }, { name: "access_purpose", label: "Access purpose (CA/auditor)" }]}
          onSubmit={async (v) => { const { role, ...rest } = v; await post("/users", { ...rest, roles: [role] }); toast("User created"); setAdding(false); users.reload(); }} />
      </Modal>}
    </div>
  );
}

function Settings() {
  const { can } = useAuth();
  const { data, reload } = useData(() => get("/settings"), []);
  const [edit, setEdit] = useState<any>(null);
  const [val, setVal] = useState("");
  const [reason, setReason] = useState("");
  const [hist, setHist] = useState<any>(null);
  return (
    <Card title="Business configuration" note="Every change is versioned with effective date, reason and audit. Financial/safety policies can only be changed by the Owner/Director.">
      <Table rows={data} cols={[{ key: "key", label: "Setting" }, { key: "value", label: "Value", render: (r: any) => <code className="small">{JSON.stringify(r.value)}</code> },
        { key: "version", label: "v" }, { key: "is_default", label: "Default" },
        { key: "e", label: "", render: (r: any) => <div className="row gap">
          {can("settings.write") && <Btn kind="ghost" onClick={() => { setEdit(r); setVal(JSON.stringify(r.value, null, 2)); setReason(""); }}>Change</Btn>}
          <Btn kind="ghost" onClick={async () => setHist(await get(`/settings/${r.key}/history`))}>History</Btn></div> }]} />
      {edit && <Modal title={edit.key} onClose={() => setEdit(null)}>
        <textarea rows={10} className="mono" value={val} onChange={(e) => setVal(e.target.value)} />
        <label><span>Reason *</span><input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
        <Btn disabled={reason.length < 3} onClick={async () => {
          try { await put(`/settings/${edit.key}`, { value: JSON.parse(val), reason }); toast("Saved as new version"); setEdit(null); reload(); }
          catch (e: any) { toast(e.message || "Invalid JSON", "red"); }
        }}>Save new version</Btn>
      </Modal>}
      {hist && <Modal title="History" onClose={() => setHist(null)}><Table rows={hist} cols={[{ key: "version", label: "v" }, { key: "value", label: "Value", render: (r: any) => <code>{JSON.stringify(r.value)}</code> },
        { key: "reason", label: "Reason" }, { key: "effective_from", label: "Effective", date: true }]} /></Modal>}
    </Card>
  );
}

function Audit() {
  const [entity, setEntity] = useState("");
  const { data } = useData(() => get(`/audit${entity ? `?entity=${entity}` : ""}`), [entity]);
  const [ver, setVer] = useState<any>(null);
  return (
    <Card title="Audit trail (hash-chained, tamper-evident)" actions={<>
      <input placeholder="Entity (e.g. booking)" value={entity} onChange={(e) => setEntity(e.target.value)} />
      <Btn kind="ghost" onClick={async () => setVer(await get("/audit/verify"))}>Verify chain</Btn></>}>
      {ver && <p><Badge v={ver.ok ? "ok" : "failed"} /> {ver.ok ? `Chain intact (${ver.checked} records)` : `Chain broken at record ${ver.broken_at_id}`}</p>}
      <Table rows={data} cols={[{ key: "at", label: "When", date: true }, { key: "actor", label: "Who" }, { key: "action", label: "Action" }, { key: "entity", label: "Entity" },
        { key: "reason", label: "Reason" }, { key: "after", label: "Change", render: (r: any) => <code className="small">{JSON.stringify(r.after)?.slice(0, 120)}</code> }]} />
    </Card>
  );
}

function Integrations() {
  const { data } = useData(() => get("/integrations"), []);
  return (
    <Card title="Integrations" note="Nothing is reported as LIVE until an authenticated connection has been tested. See INTEGRATIONS.md and BLOCKERS.md.">
      <Table rows={data} cols={[{ key: "kind", label: "Integration" }, { key: "adapter", label: "Adapter" }, { key: "mode", label: "Mode", badge: true },
        { key: "live_verified", label: "Live verified" }, { key: "last_success_at", label: "Last success", date: true }, { key: "note", label: "Note" }]} />
    </Card>
  );
}

function Notifications() {
  const { data, reload } = useData(() => get("/notifications"), []);
  return (
    <Card title="Communication log" note="Consent/opt-out and daily caps apply. Sensitive messages are HELD until approved. Delivery is MOCK until providers are connected.">
      <Table rows={data} cols={[{ key: "at", label: "When", date: true }, { key: "channel", label: "Channel" }, { key: "template", label: "Template" }, { key: "recipient", label: "To" },
        { key: "status", label: "Status", badge: true }, { key: "provider", label: "Provider" }, { key: "body", label: "Message" },
        { key: "a", label: "", render: (r: any) => r.status === "held" && <Btn kind="ghost" onClick={async () => { await post(`/notifications/${r.id}/approve`); reload(); }}>Approve & send</Btn> }]} />
    </Card>
  );
}
export { dt };
