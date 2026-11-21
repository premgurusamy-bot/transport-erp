import React, { useEffect, useState } from "react";
import { api, auth, can } from "../lib/api";
import { isAndroidApp } from "../lib/native";
import { label } from "../lib/format";
import { Btn, Card, Field, Tabs, run, toast, useLoad } from "../components/ui";

const LABELS: Record<string, string> = {
  paper: "Paper size", orientation: "Orientation", margin_mm: "Margins (mm)", font_size: "Font size (pt)", accent_color: "Accent colour (company name, lines)",
  border_color: "Table border colour", header_fill: "Table header background", logo_position: "Logo position", logo_height_mm: "Logo height (mm)",
  show_legal_name: "Legal name (if different from trade name)", show_address: "Address", show_gstin: "GSTIN", show_pan: "PAN", show_cin: "CIN", show_contact: "Phone / email / website",
  header_lines: "Extra header lines (e.g. ISO certification, branch address)", footer_text: "Footer text on every page", page_numbers: "Page numbers",
  show_signature_image: "Print signature image", show_stamp_image: "Print company stamp / seal image", show_qr: "QR code", show_due_date: "Due date", show_po: "Customer PO number",
  show_place_of_supply: "Place of supply", show_amount_in_words: "Amount in words", show_bank: "Bank details", show_tax_summary: "SAC-wise tax summary table", show_terms: "Terms & conditions",
  show_customer_ack: "Customer acknowledgement box", customer_ack_label: "Customer acknowledgement label", signatory_label: "Signatory label", extra_note: "Extra note (printed above totals)",
  watermark_proforma: "Watermark on proforma invoices (blank = none)", watermark_cancelled: "Watermark on cancelled documents (blank = none)", title: "Title", subtitle: "Subtitle",
  show_driver: "Driver name, mobile & licence", show_distance: "Distance", show_documents: "Invoice / e-way bill / payment terms block", show_delivery_points: "Multiple delivery points",
  show_freight: "Freight amounts", hide_freight_on_copies: "Hide freight amounts on these copies", show_freight_basis: "Freight basis (calculation)", show_declaration: "Declaration",
  signature_labels: "Signature box labels", width_mm: "Roll width (mm)", show_items: "Goods lines", zebra_rows: "Shaded alternate rows", copies: "Copies printed (one page each)", titles: "Document titles",
};
const OPTIONS: Record<string, string[]> = { paper: ["A4", "A5", "Letter", "Legal"], orientation: ["portrait", "landscape"], logo_position: ["left", "right", "center", "none"] };
const GROUPS: [string, (k: string) => boolean][] = [
  ["Page", (k) => ["paper", "orientation", "margin_mm", "font_size", "width_mm", "page_numbers", "footer_text"].includes(k)],
  ["Header", (k) => k.startsWith("logo") || ["show_legal_name", "show_address", "show_gstin", "show_pan", "show_cin", "show_contact", "header_lines", "title", "subtitle", "titles"].includes(k)],
  ["Colours", (k) => k.endsWith("_color") || k === "header_fill"],
  ["Copies", (k) => ["copies", "hide_freight_on_copies"].includes(k)],
  ["Columns", (k) => k === "columns"],
  ["Sections", () => true],
];

async function previewPdf(doc: string, layout: any) {
  if (isAndroidApp) return toast.info("Preview is available on a computer. Save the layout and print a document to check it on the phone.");
  const res = await fetch(`/api/layouts/${doc}/preview`, { method: "POST", headers: { Authorization: `Bearer ${auth.token}`, "Content-Type": "application/json" }, body: JSON.stringify(clean(layout)) });
  if (!res.ok) { let m = "Preview failed"; try { m = (await res.json()).detail; } catch { /* */ } return toast.err(m); }
  const url = URL.createObjectURL(await res.blob());
  window.open(url, "_blank");
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}
const clean = (l: any) => { const c = { ...l }; delete c._assets; return c; };

function ListEditor({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  return <div>{value.map((v, i) => <div className="row gap" key={i} style={{ marginBottom: 4 }}>
    <input className="grow" value={v} placeholder={placeholder} onChange={(e) => onChange(value.map((x, j) => (j === i ? e.target.value : x)))} />
    <button className="x" title="Move up" disabled={i === 0} onClick={() => { const n = [...value]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; onChange(n); }}>↑</button>
    <button className="x" title="Remove" onClick={() => onChange(value.filter((_, j) => j !== i))}>×</button></div>)}
    <Btn small onClick={() => onChange([...value, ""])}>+ Add</Btn></div>;
}

function ColumnsEditor({ value, onChange }: { value: any[]; onChange: (v: any[]) => void }) {
  const set = (i: number, k: string, v: any) => onChange(value.map((c, j) => (j === i ? { ...c, [k]: v } : c)));
  const total = value.filter((c) => c.show).reduce((a, c) => a + Number(c.width || 0), 0) || 1;
  return <div className="table-wrap"><table className="tbl dense edit"><thead><tr><th>Show</th><th>Column</th><th>Heading printed</th><th>Width</th><th>Order</th></tr></thead><tbody>
    {value.map((c, i) => <tr key={c.key}>
      <td><input type="checkbox" checked={c.show} disabled={c.key === "description"} onChange={(e) => set(i, "show", e.target.checked)} /></td>
      <td>{label(c.key)}</td>
      <td><input value={c.label} onChange={(e) => set(i, "label", e.target.value)} /></td>
      <td><input type="number" min={1} max={100} style={{ width: 70 }} value={c.width} onChange={(e) => set(i, "width", e.target.value)} /> {c.show ? `${Math.round((Number(c.width) / total) * 100)}%` : ""}</td>
      <td><button className="x" disabled={i === 0} onClick={() => { const n = [...value]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; onChange(n); }}>↑</button><button className="x" disabled={i === value.length - 1} onClick={() => { const n = [...value]; [n[i + 1], n[i]] = [n[i], n[i + 1]]; onChange(n); }}>↓</button></td>
    </tr>)}</tbody></table></div>;
}

function Input({ k, v, def, set, layout }: { k: string; v: any; def: any; set: (v: any) => void; layout: any }) {
  if (k === "columns") return <ColumnsEditor value={v} onChange={set} />;
  if (k === "titles") return <div className="form-grid">{Object.keys(def).map((t) => <Field key={t} label={label(t)}><input value={v[t] || ""} onChange={(e) => set({ ...v, [t]: e.target.value })} /></Field>)}</div>;
  if (k === "hide_freight_on_copies") return <div className="row gap wrap">{(layout.copies || []).filter(Boolean).map((c: string) => <label key={c} className="row gap small"><input type="checkbox" checked={v.includes(c)} onChange={(e) => set(e.target.checked ? [...v, c] : v.filter((x: string) => x !== c))} />{c}</label>)}</div>;
  if (k === "signature_labels") return <div className="form-grid">{def.map((d: string, i: number) => <input key={i} value={v[i] ?? ""} placeholder={d} onChange={(e) => set(def.map((_: string, j: number) => (j === i ? e.target.value : v[j] ?? def[j])))} />)}</div>;
  if (Array.isArray(def)) return <ListEditor value={v} onChange={set} />;
  if (typeof def === "boolean") return <input type="checkbox" checked={!!v} onChange={(e) => set(e.target.checked)} />;
  if (OPTIONS[k]) return <select value={v} onChange={(e) => set(e.target.value)}>{(k === "orientation" && def === "auto" ? ["auto", ...OPTIONS[k]] : OPTIONS[k]).map((o) => <option key={o}>{o}</option>)}</select>;
  if (k.endsWith("_color") || k === "header_fill") return <div className="row gap"><input type="color" value={v} onChange={(e) => set(e.target.value)} style={{ width: 48, padding: 2 }} /><input value={v} onChange={(e) => set(e.target.value)} style={{ width: 100 }} /></div>;
  if (typeof def === "number") return <input type="number" step="0.5" value={v} onChange={(e) => set(e.target.value === "" ? "" : Number(e.target.value))} />;
  if (["header_lines", "footer_text", "extra_note"].includes(k)) return <textarea rows={2} value={v} onChange={(e) => set(e.target.value)} />;
  return <input value={v ?? ""} onChange={(e) => set(e.target.value)} />;
}

function AssetBox({ name, title }: { name: string; title: string }) {
  const [tick, setTick] = useState(0);
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    fetch(`/api/layouts/assets/${name}`, { headers: { Authorization: `Bearer ${auth.token}` } }).then(async (r) => { if (live) setSrc(r.ok ? URL.createObjectURL(await r.blob()) : null); });
    return () => { live = false; };
  }, [tick]);
  return <div className="asset">
    <b>{title}</b>
    <div className="asset-img">{src ? <img src={src} alt={title} /> : <span className="muted small">Not uploaded</span>}</div>
    {can("settings:write") && <div className="row gap">
      <label className="btn sm">Upload<input hidden type="file" accept="image/png,image/jpeg" onChange={async (e) => { const f = e.target.files?.[0]; if (!f) return; const fd = new FormData(); fd.append("file", f); if (await run(() => api.form(`/api/layouts/assets/${name}`, fd), "Uploaded")) setTick(tick + 1); }} /></label>
      {src && <Btn small kind="ghost" onClick={async () => { if (await run(() => api.del(`/api/layouts/assets/${name}`), "Removed")) setTick(tick + 1); }}>Remove</Btn>}
    </div>}
  </div>;
}

export default function LayoutsEditor() {
  const { data, reload } = useLoad<any>("/api/layouts");
  const [doc, setDoc] = useState("invoice");
  const [state, setState] = useState<{ doc: string; layout: any } | null>(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => { if (data) { setState({ doc, layout: data.layouts[doc] }); setDirty(false); } }, [data, doc]);
  if (!data || !state || state.doc !== doc) return null;
  const draft = state.layout;
  const setDraft = (layout: any) => setState({ doc, layout });
  const defs = data.defaults[doc];
  const set = (k: string, v: any) => { setDraft({ ...draft, [k]: v }); setDirty(true); };
  const keys = Object.keys(defs);
  const used = new Set<string>();
  const grouped = GROUPS.map(([g, test]) => [g, keys.filter((k) => !used.has(k) && test(k) && used.add(k))] as const).filter(([, ks]) => ks.length);
  const docs = Object.entries(data.documents) as [string, string][];
  const save = async () => { const r = await run(() => api.put(`/api/layouts/${doc}`, clean(draft)), "Layout saved – new prints use it"); if (r) reload(); };
  return <div>
    <p className="muted small">Change how printed documents look. Use <b>Preview</b> to see a PDF with your changes (it uses your latest real document, or a sample) before saving. Wording required by GST law – such as the reverse-charge statement – is always printed.</p>
    <Tabs tabs={docs.map(([, v]) => v)} value={data.documents[doc]} onChange={(v) => { if (dirty && !confirm("Discard unsaved changes?")) return; setDoc(docs.find(([, x]) => x === v)![0]); }} />
    <div className="row gap wrap" style={{ marginBottom: 10 }}>
      <Btn onClick={() => previewPdf(doc, draft)}>Preview PDF</Btn>
      {can("settings:write") && <><Btn kind="primary" disabled={!dirty} onClick={save}>Save layout</Btn>
        <Btn kind="ghost" onClick={async () => { if (confirm("Reset this layout to the default?") && await run(() => api.post(`/api/layouts/${doc}/reset`), "Reset to default")) reload(); }}>Reset to default</Btn></>}
      {dirty && <span className="badge warn">Unsaved changes</span>}
    </div>
    {doc !== "thermal" && doc !== "report" && <Card title="Signature & stamp images"><div className="row gap wrap"><AssetBox name="signature" title="Authorised signatory's signature" /><AssetBox name="stamp" title="Company stamp / seal" /></div>
      <p className="muted small">Used on invoices and LRs when the matching option is ticked. A PNG with a transparent background looks best.</p></Card>}
    {grouped.map(([g, ks]) => <Card key={g} title={g}>
      <div className={g === "Columns" || g === "Copies" ? "" : "form-grid"}>
        {ks.map((k) => <Field key={k} label={LABELS[k] || label(k)} wide={["columns", "titles", "copies", "signature_labels", "hide_freight_on_copies", "header_lines", "footer_text", "extra_note"].includes(k)}>
          <Input k={k} v={draft[k]} def={defs[k]} set={(v) => set(k, v)} layout={draft} />
        </Field>)}
      </div>
    </Card>)}
  </div>;
}
