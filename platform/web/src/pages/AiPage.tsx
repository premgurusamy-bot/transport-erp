import { useState } from "react";
import { get, post } from "../api";
import { useAuth } from "../auth";
import { Badge, Btn, Card, ErrorBox, Table, useData } from "../components/ui";

export function AiChat({ app = "web", fixed }: { app?: string; fixed?: string }) {
  const list = useData(() => get("/ai/assistants"), []);
  const [assistant, setAssistant] = useState(fixed || "");
  const [q, setQ] = useState("");
  const [log, setLog] = useState<any[]>([]);
  const [err, setErr] = useState<any>(null);
  const ask = async () => {
    setErr(null);
    try {
      const r = await (await import("../api")).api("/ai/ask", { method: "POST", body: { assistant: assistant || list.data?.[0]?.code, question: q }, app });
      setLog((l) => [{ q, ...r }, ...l]); setQ("");
    } catch (e) { setErr(e); }
  };
  return (
    <Card title="AI assistant" note="Advisory only: it reads your authorised data, summarises and recommends. It cannot pay, approve, file, change prices or bypass controls.">
      <div className="row gap">
        {!fixed && <select aria-label="Assistant" value={assistant} onChange={(e) => setAssistant(e.target.value)}>{(list.data || []).map((a: any) => <option key={a.code} value={a.code}>{a.title}</option>)}</select>}
        <input aria-label="Question" className="grow" value={q} placeholder="Ask, e.g. 'summary of today'" onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && q && ask()} />
        <Btn disabled={!q} onClick={ask}>Ask</Btn>
      </div>
      <ErrorBox error={err} />
      {log.map((x, i) => <div key={i} className="ai-msg"><b>{x.q}</b><pre>{x.answer}</pre>
        <p className="small muted"><Badge v={x.mode} /> {x.assistant} · {x.provider} · status {x.status} · data as of {x.data_as_of} · {x.disclaimer}</p></div>)}
    </Card>
  );
}

export default function AiPage() {
  const { can } = useAuth();
  const usage = useData(() => (can("ai.admin") ? get("/ai/usage") : Promise.resolve(null)), []);
  return (
    <div className="stack">
      <AiChat />
      {usage.data && <Card title="AI usage & budget" note={`Prompt version ${usage.data.prompt_version}. At the cap, non-essential assistants pause; core ERP continues.`}>
        <p>Today ₹{usage.data.budget.day_inr} / ₹{usage.data.budget.daily_cap} ({usage.data.budget.day_pct}%) · Month ₹{usage.data.budget.month_inr} / ₹{usage.data.budget.monthly_cap} ({usage.data.budget.month_pct}%)</p>
        <p>Providers: {Object.entries(usage.data.providers).map(([k, v]: any) => `${k} (${v.mode}${v.available ? "" : ", no key configured"})`).join(" · ")}</p>
        <Table rows={usage.data.by_assistant} cols={[{ key: "assistant", label: "Assistant" }, { key: "provider", label: "Provider" }, { key: "calls", label: "Calls" },
          { key: "tokens", label: "Tokens" }, { key: "cost_inr", label: "₹", money: true }]} />
      </Card>}
    </div>
  );
}
