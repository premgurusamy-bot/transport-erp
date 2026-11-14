import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { get, post } from "../api";
import { useAuth } from "../auth";
import { enumOpts } from "../components/Resource";
import { Badge, Btn, Card, Form, inr, Modal, Table, toast, useData } from "../components/ui";
import { SubNav } from "./ErpApp";

export default function People() {
  const { can } = useAuth();
  return (
    <div className="stack">
      <SubNav items={[{ to: "/erp/people", label: "Checklists" }, { to: "/erp/people/sops", label: "SOP library" },
        { to: "/erp/people/employees", label: "Employees", show: can("hr.read") }, { to: "/erp/people/payroll", label: "Payroll", show: can("payroll.prepare") || can("payroll.approve") }]} />
      <Routes>
        <Route index element={<Checklists />} />
        <Route path="sops" element={<Sops />} />
        <Route path="employees" element={<Employees />} />
        <Route path="payroll" element={<Payroll />} />
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
          actions={<input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} />}>
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
