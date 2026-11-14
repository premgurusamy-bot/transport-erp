// Generic list + create/edit screen for master-data style resources (backed by the generic CRUD API).
import { useState } from "react";
import { get, patch, post } from "../api";
import { Btn, Card, Col, Field, Form, Modal, Table, toast, useData } from "./ui";

export function ResourcePage({ title, path, cols, fields, canWrite = true, note, editFields }: {
  title: string; path: string; cols: Col[]; fields: Field[]; canWrite?: boolean; note?: string; editFields?: Field[];
}) {
  const [q, setQ] = useState("");
  const { data, reload } = useData(() => get(`${path}${q ? `?q=${encodeURIComponent(q)}` : ""}`), [path, q]);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<any>(null);
  return (
    <Card title={title} note={note} actions={<>
      <input aria-label="Search" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} className="search" />
      {canWrite && <Btn onClick={() => setCreating(true)}>+ New</Btn>}
    </>}>
      <Table rows={data} cols={cols} onRow={canWrite ? setEditing : undefined} />
      {creating && (
        <Modal title={`New ${title}`} onClose={() => setCreating(false)}>
          <Form fields={fields} onSubmit={async (v) => { await post(path, v); toast("Saved"); setCreating(false); reload(); }} />
        </Modal>
      )}
      {editing && (
        <Modal title={`Edit ${title}`} onClose={() => setEditing(null)}>
          <Form fields={(editFields || fields).filter((f) => f.name !== "code")} initial={editing}
                onSubmit={async (v) => { await patch(`${path}/${editing.id}`, v); toast("Updated (audited)"); setEditing(null); reload(); }} />
        </Modal>
      )}
    </Card>
  );
}

export function useLookup() {
  return useData(() => get("/masters/lookup"), []);
}

export const opts = (xs: { id: string; label: string }[] | undefined) => (xs || []).map((x) => ({ value: x.id, label: x.label }));
export const enumOpts = (...xs: string[]) => xs.map((x) => ({ value: x, label: x.replace(/_/g, " ") }));
