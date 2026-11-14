import { useState } from "react";
import { get, post } from "../api";
import { useAuth } from "../auth";
import { Badge, Btn, Card, dt, inr, Table, toast, useData } from "../components/ui";

export default function Approvals() {
  const { me, can } = useAuth();
  const [status, setStatus] = useState("pending");
  const { data, reload } = useData(() => get(`/approvals?status=${status}`), [status]);
  const decide = async (a: any, approve: boolean) => {
    const note = prompt(approve ? "Approval note" : "Reason for rejection (required)") || "";
    if (!approve && !note) return;
    try { await post(`/approvals/${a.id}/decide`, { approve, note }); toast(approve ? "Approved" : "Rejected"); reload(); }
    catch (e: any) { toast(e.message, "red"); }
  };
  return (
    <Card title="Approvals (maker-checker)" note="You cannot approve your own requests. AI recommendations are never approvals."
          actions={<select value={status} onChange={(e) => setStatus(e.target.value)}>{["pending", "approved", "rejected"].map((s) => <option key={s}>{s}</option>)}</select>}>
      <Table rows={data} cols={[
        { key: "code", label: "Ref" }, { key: "kind", label: "Type", render: (r: any) => r.kind.replace(/_/g, " ") }, { key: "title", label: "Request" },
        { key: "amount", label: "Amount", render: (r: any) => (r.amount ? inr(r.amount) : "—") }, { key: "maker_reason", label: "Reason" },
        { key: "origin", label: "Origin", badge: true }, { key: "created_at", label: "Requested", date: true }, { key: "status", label: "Status", badge: true },
        { key: "act", label: "", render: (r: any) => r.status === "pending" && r.maker_id !== me?.id && can(r.required_permission) ? (
          <div className="row gap"><Btn onClick={() => decide(r, true)}>Approve</Btn><Btn kind="danger" onClick={() => decide(r, false)}>Reject</Btn></div>
        ) : r.status === "pending" ? <span className="muted small">{r.maker_id === me?.id ? "Your request" : `Needs ${r.required_permission}`}</span> : dt(r.decided_at) },
      ]} empty="Nothing waiting" />
    </Card>
  );
}
