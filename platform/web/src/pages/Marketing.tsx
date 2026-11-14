import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { get, post } from "../api";
import { useAuth } from "../auth";
import { enumOpts, ResourcePage } from "../components/Resource";
import { Badge, Btn, Card, Form, Modal, Table, toast, useData } from "../components/ui";
import { SubNav } from "./ErpApp";

const AGENTS = ["marketing_manager", "market_research", "lead_generation", "content_creator", "social_media", "business_development", "marketing_analyst", "website_seo"];

export default function Marketing() {
  const { can } = useAuth();
  return (
    <div className="stack">
      <SubNav items={[{ to: "/erp/marketing", label: "Content" }, { to: "/erp/marketing/campaigns", label: "Campaigns" },
        { to: "/erp/marketing/opportunities", label: "Opportunities" }, { to: "/erp/marketing/funnel", label: "Funnel & map" }]} />
      <Routes>
        <Route index element={<Content />} />
        <Route path="campaigns" element={<Campaigns />} />
        <Route path="opportunities" element={<ResourcePage title="Business opportunities" path="/opportunities" canWrite={can("marketing.write")}
          note="Coimbatore first. A record here does NOT mean we serve that location - verify route, partner, capacity and profitability."
          cols={[{ key: "name", label: "Business" }, { key: "industry", label: "Industry" }, { key: "city", label: "City" }, { key: "stage", label: "Stage", badge: true },
            { key: "source", label: "Source" }, { key: "confidence", label: "Confidence" }, { key: "data_kind", label: "Data", badge: true }, { key: "next_follow_up", label: "Follow-up" }]}
          fields={[{ name: "name", label: "Business", required: true }, { name: "industry", label: "Industry" }, { name: "city", label: "City" }, { name: "state", label: "State" },
            { name: "source", label: "Lawful source", required: true }, { name: "source_date", label: "Source date", type: "date" },
            { name: "confidence", label: "Confidence", type: "select", options: enumOpts("low", "medium", "high") }, { name: "data_kind", label: "Actual/estimated", type: "select", options: enumOpts("actual", "estimated") },
            { name: "stage", label: "Stage", type: "select", options: enumOpts("identified", "contacted", "qualified", "proposal", "won", "lost") },
            { name: "estimated_monthly_value", label: "Est. monthly value ₹", type: "number" }, { name: "next_follow_up", label: "Next follow-up", type: "date" }]} />} />
        <Route path="funnel" element={<Funnel />} />
      </Routes>
    </div>
  );
}

function Content() {
  const { can } = useAuth();
  const { data, reload } = useData(() => get("/marketing/content"), []);
  const [drafting, setDrafting] = useState(false);
  return (
    <Card title="Content queue" note="Routine content auto-publishes within the daily cap; major/ad/brand content needs management approval. Camera footage is not marketing consent. Publishing is MOCK until platform APIs are connected."
          actions={can("marketing.write") && <Btn onClick={() => setDrafting(true)}>+ AI draft</Btn>}>
      <Table rows={data} cols={[{ key: "title", label: "Title" }, { key: "channel", label: "Channel" }, { key: "kind", label: "Kind" }, { key: "language", label: "Lang" },
        { key: "drafted_by_agent", label: "Agent" }, { key: "status", label: "Status", badge: true }, { key: "publish_mode", label: "Mode", badge: true },
        { key: "p", label: "", render: (r: any) => can("marketing.write") && !["published", "rejected", "pending_approval"].includes(r.status) && <Btn kind="ghost" onClick={async () => {
          try { const x = await post(`/marketing/content/${r.id}/publish`, { media_consent_confirmed: false }); toast(x.note); reload(); } catch (e: any) { toast(e.message, "red"); } }}>Publish</Btn> }]} />
      {drafting && <Modal title="Draft with a marketing agent" onClose={() => setDrafting(false)}>
        <Form fields={[{ name: "agent", label: "Agent", type: "select", options: enumOpts(...AGENTS), required: true },
          { name: "channel", label: "Channel", type: "select", options: enumOpts("facebook", "instagram", "youtube", "whatsapp", "gbp", "linkedin", "website"), required: true },
          { name: "topic", label: "Topic", required: true }, { name: "language", label: "Language", type: "select", options: [{ value: "en", label: "English" }, { value: "ta", label: "தமிழ்" }] },
          { name: "kind", label: "Kind", type: "select", options: enumOpts("routine", "major", "ad", "brand") }]} initial={{ agent: "content_creator", language: "en", kind: "routine" }}
          onSubmit={async (v) => { await post("/marketing/drafts", v); setDrafting(false); reload(); }} />
      </Modal>}
    </Card>
  );
}

function Campaigns() {
  const { can } = useAuth();
  const { data, reload } = useData(() => get("/marketing/campaigns"), []);
  const [adding, setAdding] = useState(false);
  return (
    <Card title="Campaigns" note="Ads stay within approved campaign, audience and budget." actions={can("marketing.write") && <Btn onClick={() => setAdding(true)}>+ Campaign</Btn>}>
      <Table rows={data} cols={[{ key: "code", label: "Ref" }, { key: "name", label: "Name" }, { key: "channels", label: "Channels", render: (r: any) => r.channels.join(", ") },
        { key: "budget", label: "Budget", money: true }, { key: "spent", label: "Spent", money: true }, { key: "leads", label: "Leads" }, { key: "status", label: "Status", badge: true }]} />
      {adding && <Modal title="New campaign" onClose={() => setAdding(false)}>
        <Form fields={[{ name: "name", label: "Name", required: true }, { name: "audience", label: "Audience", type: "textarea" }, { name: "budget", label: "Budget ₹", type: "number" },
          { name: "starts_on", label: "Start", type: "date" }, { name: "ends_on", label: "End", type: "date" }]}
          onSubmit={async (v) => { await post("/marketing/campaigns", { ...v, channels: ["facebook", "gbp"] }); setAdding(false); reload(); }} />
      </Modal>}
    </Card>
  );
}

function Funnel() {
  const { data } = useData(() => get("/marketing/funnel"), []);
  return (
    <Card title="Lead funnel by source" note={data?.note}>
      {data && <Table rows={Object.entries(data.by_source).map(([k, v]: any) => ({ source: k, ...v }))} cols={[{ key: "source", label: "Source" },
        ...["new", "qualifying", "quoted", "won", "lost"].map((s) => ({ key: s, label: s }))]} />}
      <h4>Opportunity map data</h4>
      <Table rows={data?.opportunity_map} cols={[{ key: "name", label: "Business" }, { key: "lat", label: "Lat" }, { key: "lng", label: "Lng" }, { key: "stage", label: "Stage" },
        { key: "data_kind", label: "Data", render: (r: any) => <Badge v={r.data_kind} /> }]} />
    </Card>
  );
}
