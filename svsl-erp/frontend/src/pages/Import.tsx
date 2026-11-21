import React, { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, auth } from "../lib/api";
import { Badge, Btn, Card, Field, Page, Table, download, run, toast, useLoad } from "../components/ui";

type Target = { title: string; perm: string; match: string | null; kind: string; allowed: boolean; fields: { key: string; label: string; required: boolean; type: string; options?: string[]; ref?: string; secret?: boolean }[] };

async function postDownload(url: string, body: any, name: string) {
  const r = await fetch(url, { method: "POST", headers: { Authorization: `Bearer ${auth.token}`, "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) return toast.err("Download failed");
  const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = name; a.click();
}

export default function ImportPage() {
  const [sp] = useSearchParams();
  const targets = useLoad<Record<string, Target>>("/api/import/targets");
  const templates = useLoad<any[]>("/api/import/templates");
  const [target, setTarget] = useState(sp.get("target") || "");
  const [file, setFile] = useState<any>(null);
  const [sheet, setSheet] = useState("");
  const [headerRow, setHeaderRow] = useState(1);
  const [prev, setPrev] = useState<any>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [constants, setConstants] = useState<Record<string, string>>({});
  const [mode, setMode] = useState("create");
  const [result, setResult] = useState<any>(null);
  const [onlyProblems, setOnlyProblems] = useState(true);
  const [skipInvalid, setSkipInvalid] = useState(false);
  const [tplName, setTplName] = useState("");
  const t = target && targets.data ? targets.data[target] : null;

  const loadPreview = async (fid = file?.file_id, sh = sheet, hr = headerRow, keepMapping = false) => {
    if (!fid || !target) return;
    const p: any = await run(() => api.post("/api/import/preview", { file_id: fid, sheet: sh, header_row: hr, target }));
    if (!p) return;
    setPrev(p);
    setResult(null);
    if (!keepMapping) setMapping(Object.fromEntries(Object.entries(p.suggested || {}).filter(([, h]) => p.headers.includes(h))) as any);
  };
  useEffect(() => { if (file) loadPreview(); }, [target]);

  const onFile = async (f: File) => {
    const fd = new FormData(); fd.append("file", f);
    const up: any = await run(() => api.form("/api/import/upload", fd));
    if (!up) return;
    setFile(up);
    const s = up.sheets.find((x: any) => x.rows > 0) || up.sheets[0];
    setSheet(s.name); setHeaderRow(s.header_row);
    loadPreview(up.file_id, s.name, s.header_row);
  };

  const applyTemplate = (tpl: any) => {
    setTarget(tpl.target); setMapping(tpl.mapping || {}); setConstants(tpl.constants || {}); setMode(tpl.mode || "create"); setHeaderRow(tpl.header_row || 1); setTplName(tpl.name);
    if (file) loadPreview(file.file_id, sheet, tpl.header_row || 1, true).then(() => setMapping(tpl.mapping || {}));
  };
  const req = () => ({ file_id: file.file_id, sheet, header_row: headerRow, target, mapping, constants, mode, skip_invalid: skipInvalid });
  const sample = useMemo(() => (prev?.rows || [])[0] || {}, [prev]);
  const missing = t ? t.fields.filter((f) => f.required && !mapping[f.key] && !constants[f.key]).map((f) => f.label) : [];

  return <Page title="Import from Excel">
    <p className="muted">Bring data you maintain in Excel into the ERP – <b>your own column headings are fine</b>. Match each ERP field to one of your columns, check, then import. Nothing is saved until every row is valid (or you choose to skip the bad rows), and every imported record is in the audit trail.</p>
    <Card title="1. What are you importing?">
      <div className="row gap wrap">
        <Field label="Import into"><select value={target} onChange={(e) => { setTarget(e.target.value); setConstants({}); setResult(null); }}>
          <option value="">— choose —</option>
          {targets.data && Object.entries(targets.data).sort((a, b) => a[1].title.localeCompare(b[1].title)).map(([k, v]) => <option key={k} value={k} disabled={!v.allowed}>{v.title}{v.allowed ? "" : " (no permission)"}</option>)}
        </select></Field>
        {(templates.data || []).length > 0 && <Field label="Use a saved mapping"><select value="" onChange={(e) => { const tpl = templates.data![Number(e.target.value)]; if (tpl) applyTemplate(tpl); }}>
          <option value="">—</option>{templates.data!.map((tp, i) => <option key={i} value={i}>{tp.name} ({targets.data?.[tp.target]?.title || tp.target})</option>)}</select></Field>}
        {target && <Btn small kind="ghost" onClick={() => download(`/api/import/template/${target}`)}>Blank Excel with ERP headings</Btn>}
      </div>
      {target && <Field label="Your Excel or CSV file"><input type="file" accept=".xlsx,.xlsm,.csv" onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} /></Field>}
    </Card>

    {file && prev && t && <>
      <Card title="2. Check the sheet">
        <div className="row gap wrap">
          {file.sheets.length > 1 && <Field label="Sheet"><select value={sheet} onChange={(e) => { setSheet(e.target.value); const s = file.sheets.find((x: any) => x.name === e.target.value); setHeaderRow(s.header_row); loadPreview(file.file_id, e.target.value, s.header_row); }}>{file.sheets.map((s: any) => <option key={s.name} value={s.name}>{s.name} ({s.rows} rows)</option>)}</select></Field>}
          <Field label="Headings are in row" help="Rows above it (titles) are ignored"><input type="number" min={1} style={{ width: 90 }} value={headerRow} onChange={(e) => setHeaderRow(Number(e.target.value))} onBlur={() => loadPreview(file.file_id, sheet, headerRow)} /></Field>
          <span className="muted small">{prev.total} data rows found</span>
        </div>
        <Table dense cols={[{ key: "_row", label: "Row" }, ...prev.headers.map((h: string) => ({ key: h, label: h }))]} rows={prev.rows.slice(0, 5)} />
      </Card>

      <Card title="3. Match your columns to ERP fields" actions={<span className="muted small">{Object.keys(mapping).length} matched automatically or by you</span>}>
        <div className="table-wrap"><table className="tbl dense edit"><thead><tr><th>ERP field</th><th>Your column</th><th>…or same value for every row</th><th>First row gives</th></tr></thead><tbody>
          {t.fields.filter((f) => !f.secret).map((f) => <tr key={f.key} className={f.required && !mapping[f.key] && !constants[f.key] ? "need" : ""}>
            <td>{f.label}{f.required && <b className="req">*</b>}{f.options?.length ? <div className="tiny muted">{f.options.join(" / ")}</div> : null}{f.ref && <div className="tiny muted">matched by name or code</div>}</td>
            <td><select value={mapping[f.key] || ""} onChange={(e) => { const m = { ...mapping }; if (e.target.value) m[f.key] = e.target.value; else delete m[f.key]; setMapping(m); setResult(null); }}>
              <option value="">— not in my file —</option>{prev.headers.map((h: string) => <option key={h} value={h}>{h}</option>)}</select></td>
            <td><input value={constants[f.key] || ""} disabled={!!mapping[f.key]} placeholder={f.type === "date" ? "DD-MM-YYYY" : ""} onChange={(e) => { setConstants({ ...constants, [f.key]: e.target.value }); setResult(null); }} /></td>
            <td className="muted small">{mapping[f.key] ? String(sample[mapping[f.key]] ?? "") : constants[f.key] || ""}</td>
          </tr>)}
        </tbody></table></div>
        <div className="row gap wrap">
          {t.kind === "crud" && <Field label="If a record already exists"><select value={mode} onChange={(e) => { setMode(e.target.value); setResult(null); }}>
            <option value="create">Add new only (skip existing)</option><option value="upsert">Add new and update existing</option><option value="update">Update existing only</option></select></Field>}
          {t.match && <span className="muted small">Existing records are matched by <b>{t.fields.find((f) => f.key === t.match)?.label}</b>.</span>}
          <div className="grow" />
          <input placeholder="Name this mapping to reuse it" value={tplName} onChange={(e) => setTplName(e.target.value)} />
          <Btn small onClick={async () => { if (await run(() => api.post("/api/import/templates", { name: tplName, target, mapping, constants, header_row: headerRow, mode }), "Mapping saved")) templates.reload(); }}>Save mapping</Btn>
        </div>
        {missing.length > 0 && mode === "create" && <div className="warn-box">Still to match: {missing.join(", ")}</div>}
      </Card>

      <Card title="4. Check and import">
        <div className="row gap wrap">
          <Btn onClick={async () => setResult(await run(() => api.post("/api/import/validate", req())))}>Check all rows</Btn>
          <label className="row gap small"><input type="checkbox" checked={skipInvalid} onChange={(e) => setSkipInvalid(e.target.checked)} /> Skip rows with errors and import the rest</label>
          <Btn kind="primary" disabled={!result || (result.summary.errors > 0 && !skipInvalid)} onClick={async () => {
            if (!confirm(`Import ${result.summary.created + result.summary.updated} record(s) into ${t.title}?`)) return;
            const r: any = await run(() => api.post("/api/import/run", req()));
            if (r) { setResult(r); r.committed ? toast.ok(`Imported: ${r.summary.created} added, ${r.summary.updated} updated`) : toast.err(r.message); }
          }}>Import</Btn>
        </div>
        {result && <>
          <div className="row gap wrap" style={{ margin: "10px 0" }}>
            {result.committed && <Badge v="Imported" />}
            <span>Rows: <b>{result.summary.total}</b></span><span className="good">To add: <b>{result.summary.created}</b></span><span>To update: <b>{result.summary.updated}</b></span>
            <span className="muted">Skipped: <b>{result.summary.skipped}</b></span><span className={result.summary.errors ? "bad" : ""}>Errors: <b>{result.summary.errors}</b></span>
            <label className="row gap small"><input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} /> show only problems</label>
            {(result.summary.errors > 0 || result.summary.skipped > 0) && <Btn small onClick={() => postDownload("/api/import/errors.xlsx", { results: result.results }, "import-problems.xlsx")}>Download problems (Excel)</Btn>}
          </div>
          {result.message && <div className="warn-box">{result.message}</div>}
          <Table dense cols={[{ key: "row", label: "Excel row" }, { key: "key", label: "Record" }, { key: "status", label: "Result", render: (r) => <Badge v={r.status === "error" ? "Failed" : r.status === "created" ? (result.committed ? "Added" : "Will add") : r.status === "updated" ? (result.committed ? "Updated" : "Will update") : "Skipped"} /> }, { key: "message", label: "Details" }]}
            rows={onlyProblems ? result.results.filter((r: any) => r.status === "error" || r.status === "skipped") : result.results} empty={onlyProblems ? "No problems – every row is fine" : "No rows"} />
        </>}
      </Card>
    </>}
  </Page>;
}
