import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { api, get, post } from "../api";
import { useAuth } from "../auth";
import { enumOpts } from "../components/Resource";
import { Badge, Btn, Card, Form, inr, Modal, Table, toast, useData } from "../components/ui";
import { SubNav } from "./ErpApp";

export default function People() {
  const { can } = useAuth();
  return (
    <div className="stack">
      <SubNav items={[{ to: "/erp/people", label: "Checklists" }, { to: "/erp/people/sops", label: "SOP library" },
        { to: "/erp/people/employees", label: "Employees", show: can("hr.read") }, { to: "/erp/people/attendance", label: "Attendance & leave", show: can("hr.write") },
        { to: "/erp/people/outage", label: "Outage forms", show: can("controltower.read") }, { to: "/erp/people/payroll", label: "Payroll", show: can("payroll.prepare") || can("payroll.approve") }]} />
      <Routes>
        <Route index element={<Checklists />} />
        <Route path="sops" element={<Sops />} />
        <Route path="employees" element={<Employees />} />
        <Route path="payroll" element={<Payroll />} />
        <Route path="attendance" element={<AttendanceLeave />} />
        <Route path="outage" element={<OutageForms />} />
      </Routes>
    </div>
  );
}

function Checklists() {
  const { data, reload } = useData(() => get("/checklists/today"), []);
  const [sel, setSel] = useState<any>(null);
  const [answers, setAnswers] = useState<Record<string, boolean>>({});
  return (
    <Card title="Daily / weekly / monthly checklists" note="Every critical process has an owner, a backup, a deadline and evidence.">
      <Table rows={data} cols={[{ key: "title", label: "Checklist" }, { key: "frequency", label: "Frequency" }, { key: "owner_role", label: "Owner" }, { key: "backup_role", label: "Backup" },
        { key: "period_key", label: "Period" }, { key: "status", label: "Status", badge: true },
        { key: "a", label: "", render: (r: any) => r.mine && r.status !== "completed" && <Btn kind="ghost" onClick={() => { setSel(r); setAnswers({}); }}>Complete</Btn> }]} />
      {sel && <Modal title={sel.title} onClose={() => setSel(null)}>
        {sel.items.map((i: string) => <label key={i} className="row gap"><input type="checkbox" checked={!!answers[i]} onChange={(e) => setAnswers({ ...answers, [i]: e.target.checked })} />{i}</label>)}
        <Btn onClick={async () => { const results = Object.fromEntries(sel.items.map((i: string) => [i, !!answers[i]]));
          await post(`/checklists/${sel.id}/complete`, { results }); toast("Saved - unchecked items raised as exceptions"); setSel(null); reload(); }}>Submit</Btn>
      </Modal>}
    </Card>
  );
}

function Sops() {
  const { can } = useAuth();
  const { data, reload } = useData(() => get("/sops"), []);
  const [view, setView] = useState<any>(null);
  return (
    <Card title="SOP library" note="Versioned; approval by the approver role; staff acknowledge training.">
      <Table rows={data} onRow={setView} cols={[{ key: "code", label: "Code" }, { key: "version", label: "v" }, { key: "title", label: "Title" }, { key: "department", label: "Dept" },
        { key: "status", label: "Status", badge: true }, { key: "acknowledged", label: "Acknowledged by me" }]} />
      {view && <Modal title={`${view.title} v${view.version}`} onClose={() => setView(null)}>
        <ol>{view.steps.map((s: string, i: number) => <li key={i}>{s}</li>)}</ol>
        <div className="row gap">
          {can("sop.approve") && view.status === "draft" && <Btn onClick={async () => { try { await post(`/sops/${view.id}/approve`); toast("Approved"); setView(null); reload(); } catch (e: any) { toast(e.message, "red"); } }}>Approve</Btn>}
          {view.status === "approved" && !view.acknowledged && <Btn kind="ghost" onClick={async () => { await post(`/sops/${view.id}/acknowledge`); setView(null); reload(); }}>I have read and understood</Btn>}
        </div>
      </Modal>}
    </Card>
  );
}

function Employees() {
  const { can } = useAuth();
  const { data, reload } = useData(() => get("/employees"), []);
  const [adding, setAdding] = useState(false);
  return (
    <Card title="Employees" note="Salary visible only with HR salary permission. Exit revokes system access immediately." actions={can("hr.write") && <Btn onClick={() => setAdding(true)}>+ Employee</Btn>}>
      <Table rows={data} cols={[{ key: "code", label: "Code" }, { key: "name", label: "Name" }, { key: "department", label: "Dept" }, { key: "designation", label: "Designation" },
        { key: "employment_type", label: "Type" }, { key: "monthly_salary", label: "Salary", render: (r: any) => (String(r.monthly_salary).includes("*") ? r.monthly_salary : inr(r.monthly_salary)) },
        { key: "status", label: "Status", badge: true },
        { key: "x", label: "", render: (r: any) => can("hr.write") && r.status === "active" && <Btn kind="danger" onClick={async () => {
          const reason = prompt("Exit reason"); if (reason) { await post(`/employees/${r.id}/exit`, { exited_on: new Date().toISOString().slice(0, 10), reason }); reload(); } }}>Exit</Btn> }]} />
      {adding && <Modal title="New employee" onClose={() => setAdding(false)}>
        <Form fields={[{ name: "name", label: "Name", required: true }, { name: "department", label: "Department", type: "select", required: true, options: enumOpts("office", "operations", "accounts", "drivers", "store", "sales", "management") },
          { name: "designation", label: "Designation" }, { name: "employment_type", label: "Type", type: "select", options: enumOpts("permanent", "temporary", "contract") },
          { name: "phone", label: "Phone", type: "tel" }, { name: "joined_on", label: "Joined", type: "date" }, ...(can("hr.view_salary") ? [{ name: "monthly_salary", label: "Monthly salary ₹", type: "number" as const }] : [])]}
          onSubmit={async (v) => { await post("/employees", v); setAdding(false); reload(); }} />
      </Modal>}
    </Card>
  );
}

function Payroll() {
  const { can } = useAuth();
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const { data, reload } = useData(() => get(`/payroll/${period}`), [period]);
  return (
    <Card title="Payroll" note="Statutory rates are configurable placeholders - verify with your CA. Driver trip pay is calculated separately (no double counting)."
          actions={<input aria-label="Period" type="month" value={period} onChange={(e) => setPeriod(e.target.value)} />}>
      <div className="row gap">
        {can("payroll.prepare") && (!data || data.status === "draft") && <Btn onClick={async () => { await post(`/payroll/${period}/prepare`); reload(); }}>Prepare</Btn>}
        {can("payroll.prepare") && data?.status === "draft" && <Btn kind="ghost" onClick={async () => { await post(`/payroll/${period}/submit`); toast("Sent for approval"); reload(); }}>Submit for approval</Btn>}
        {data && <Badge v={data.status} />}
      </div>
      {data && <><p>Gross {inr(data.totals.gross)} · Net {inr(data.totals.net)} · PF {inr(data.totals.pf)} · ESI {inr(data.totals.esi)}</p>
        <Table rows={data.payslips} cols={[{ key: "employee_id", label: "Employee" }, { key: "days_payable", label: "Days" }, { key: "gross", label: "Gross", money: true }, { key: "net", label: "Net", money: true }]} /></>}
    </Card>
  );
}

function AttendanceLeave() {
  const emps = useData(() => get("/employees"), []);
  const leave = useData(() => get("/leave"), []);
  const [day, setDay] = useState(new Date().toISOString().slice(0, 10));
  const mark = async (e: any, status: string) => {
    try { await post("/attendance", { employee_id: e.id, day, status }); toast(`${e.name}: ${status}`); }
    catch (x: any) {
      const reason = x.code === "reason_required" ? prompt("Already marked - correction reason") : null;
      if (reason) { await post("/attendance", { employee_id: e.id, day, status, correction_reason: reason }); toast("Corrected (audited)"); } else if (x.code !== "reason_required") toast(x.message, "red");
    }
  };
  return (
    <div className="stack">
      <Card title="Attendance" note="Corrections need a reason and are audited." actions={<input type="date" value={day} onChange={(e) => setDay(e.target.value)} />}>
        <Table rows={(emps.data || []).filter((e: any) => e.status === "active")} cols={[{ key: "name", label: "Employee" }, { key: "department", label: "Dept" },
          { key: "m", label: "Mark", render: (e: any) => <div className="row gap wrap">{["present", "absent", "half_day", "leave", "field_duty"].map((st) =>
            <Btn key={st} kind="ghost" onClick={() => mark(e, st)}>{st.replace("_", " ")}</Btn>)}</div> }]} />
      </Card>
      <Card title="Leave requests">
        <Table rows={leave.data} cols={[{ key: "employee_id", label: "Employee", render: (r: any) => (emps.data || []).find((e: any) => e.id === r.employee_id)?.name || (r.driver_id ? "Driver" : "—") },
          { key: "from_date", label: "From" }, { key: "to_date", label: "To" }, { key: "kind", label: "Kind" }, { key: "reason", label: "Reason" }, { key: "status", label: "Status", badge: true },
          { key: "a", label: "", render: (r: any) => r.status === "requested" && <div className="row gap">
            <Btn onClick={async () => { await post(`/leave/${r.id}/decide`, { approve: true }); leave.reload(); }}>Approve</Btn>
            <Btn kind="danger" onClick={async () => { await post(`/leave/${r.id}/decide`, { approve: false }); leave.reload(); }}>Reject</Btn></div> }]} />
        <Form fields={[{ name: "employee_id", label: "Employee", type: "select", options: (emps.data || []).map((e: any) => ({ value: e.id, label: e.name })), required: true },
          { name: "from_date", label: "From", type: "date", required: true }, { name: "to_date", label: "To", type: "date", required: true },
          { name: "kind", label: "Kind", type: "select", options: enumOpts("casual", "sick", "earned", "unpaid") }, { name: "reason", label: "Reason" }]}
          submitLabel="Record leave request" onSubmit={async (v) => { await post("/leave", v); leave.reload(); }} />
      </Card>
    </div>
  );
}

const FORM_KINDS = ["enquiry", "booking", "dispatch", "trip", "pod", "fuel", "expense", "incident"];

function OutageForms() {
  const review = useData(() => get("/outage-forms/review"), []);
  const [kind, setKind] = useState("pod");
  const [count, setCount] = useState(10);
  const [entry, setEntry] = useState<Record<string, any>>({ kind: "pod" });
  return (
    <div className="stack">
      <Card title="Issue numbered outage forms" note="Use only when the system is unavailable. Each number can be entered once; unissued numbers are rejected. No payments, statutory filings or credit approvals on paper.">
        <div className="row gap"><select aria-label="Form kind" value={kind} onChange={(e) => setKind(e.target.value)}>{FORM_KINDS.map((k) => <option key={k}>{k}</option>)}</select>
          <input type="number" min={1} max={200} value={count} onChange={(e) => setCount(Number(e.target.value))} />
          <Btn onClick={async () => { const b = await api("/outage-forms", { method: "POST", body: { kind, count } }); const a = document.createElement("a"); a.href = URL.createObjectURL(b as Blob); a.download = `GRL_outage_${kind}.pdf`; a.click(); }}>Download PDF</Btn></div>
      </Card>
      <Card title="Enter a completed paper form (after recovery)" note="Original date/time from the form is kept. Entries wait for review by a different supervisor.">
        <div className="grid-form">
          <label><span>Kind</span><select value={entry.kind} onChange={(e) => setEntry({ ...entry, kind: e.target.value })}>{FORM_KINDS.map((k) => <option key={k}>{k}</option>)}</select></label>
          <label><span>Form number</span><input placeholder="PF-POD-00001" onChange={(e) => setEntry({ ...entry, form_number: e.target.value.trim() })} /></label>
          <label><span>Original date/time</span><input type="datetime-local" onChange={(e) => setEntry({ ...entry, at: e.target.value })} /></label>
          <label className="span2"><span>Contents (as written)</span><textarea onChange={(e) => setEntry({ ...entry, text: e.target.value })} /></label>
        </div>
        <Btn disabled={!entry.form_number || !entry.at} onClick={async () => {
          const r = await post("/sync/events", { events: [{ client_event_id: crypto.randomUUID(), device_id: "office", event_type: "paper_form", source: "paper_form",
            occurred_at: new Date(entry.at).toISOString(), payload: { kind: entry.kind, form_number: entry.form_number, text: entry.text } }] });
          const x = r.results[0]; toast(x.status === "rejected" ? x.result.error : "Entered - awaiting supervisor review", x.status === "rejected" ? "red" : "green"); review.reload();
        }}>Enter form</Btn>
      </Card>
      <Card title="Supervisor review">
        <Table rows={review.data} cols={[{ key: "occurred_at", label: "Original time", date: true }, { key: "payload", label: "Form", render: (r: any) => `${r.payload.form_number} (${r.payload.kind})` },
          { key: "text", label: "Contents", render: (r: any) => r.payload.text }, { key: "status", label: "Status", badge: true },
          { key: "a", label: "", render: (r: any) => r.status === "needs_review" && <Btn kind="ghost" onClick={async () => {
            const note = prompt("Reconciliation note (required)"); if (!note) return;
            try { await post(`/outage-forms/review/${r.client_event_id}`, { approve: true, note }); review.reload(); } catch (e: any) { toast(e.message, "red"); } }}>Mark reconciled</Btn> }]} empty="No paper forms entered" />
      </Card>
    </div>
  );
}
