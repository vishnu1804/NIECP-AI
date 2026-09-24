/** Inspections (spec §24). */
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import { Badge, Button, Card, Disclaimer, EmptyState, Field, Input, Modal, Spinner, StatusBadge, Textarea } from "../components/ui";

export default function Inspections() {
  const { projectId } = useParams();
  const [rows, setRows] = useState<any[]>([]);
  const [creating, setCreating] = useState(false);
  const [detail, setDetail] = useState<any>(null);
  const [form, setForm] = useState({ department: "", inspection_date: "", inspection_type: "GENERAL", officer_name: "", officer_designation: "", officer_details_officially_provided: false });
  const [findings, setFindings] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    setRows((await api<any>(`/projects/${projectId}/inspections`)).inspections);
    setLoading(false);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [projectId]);

  const create = async () => {
    await api(`/projects/${projectId}/inspections`, "POST", form);
    setCreating(false);
    await load();
  };

  const toggleCheck = async (insp: any, idx: number) => {
    const checklist = insp.checklist.map((c: any, i: number) => (i === idx ? { ...c, done: !c.done } : c));
    const r = await api<any>(`/projects/${projectId}/inspections/${insp.id}`, "PATCH", { checklist });
    setDetail(r.inspection);
    await load();
  };

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Inspections</h1>
          <p className="text-[12.5px] text-slate-500">Record announced visits, prepare from the checklist, and record findings and corrective actions.</p>
        </div>
        <Button onClick={() => setCreating(true)}>+ Record inspection</Button>
      </div>

      {loading ? <Spinner /> : rows.length === 0 ? (
        <EmptyState icon="🔍" title="No inspections recorded" hint="When a department announces a visit, record it — NIECP-AI generates the standard preparation checklist." />
      ) : (
        <div className="space-y-3">
          {rows.map((i) => (
            <Card key={i.id} className="p-4" onClick={() => { setDetail(i); setFindings(i.findings || ""); }}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  {i.is_demo ? <Badge tone="violet">DEMO</Badge> : null}
                  <span className="text-[13.5px] font-semibold text-slate-100">{i.department || "Inspection"}</span>
                  <Badge tone="slate">{i.inspection_type.replace(/_/g, " ")}</Badge>
                </div>
                <div className="flex items-center gap-2">
                  {i.inspection_date ? <Badge tone="blue">{i.inspection_date}</Badge> : null}
                  <StatusBadge value={i.status} />
                </div>
              </div>
              {i.checklist?.length ? (
                <div className="mt-2 text-[11.5px] text-slate-500">
                  Checklist: {i.checklist.filter((c: any) => c.done).length}/{i.checklist.length} prepared
                </div>
              ) : null}
            </Card>
          ))}
        </div>
      )}

      <Modal open={creating} onClose={() => setCreating(false)} title="Record an inspection">
        <div className="space-y-3">
          <Field label="Department"><Input value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} placeholder="e.g. Factories Inspectorate" /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Date"><Input type="date" value={form.inspection_date} onChange={(e) => setForm({ ...form, inspection_date: e.target.value })} /></Field>
            <Field label="Type">
              <Input value={form.inspection_type} onChange={(e) => setForm({ ...form, inspection_type: e.target.value })} placeholder="GENERAL / FACTORY / FIRE / POLLUTION" />
            </Field>
          </div>
          <Disclaimer tone="blue">
            Officer details are only recorded if officially communicated to you. NIECP-AI never invents officer names or designations.
          </Disclaimer>
          <label className="flex items-center gap-2 text-[12.5px] text-slate-300">
            <input type="checkbox" checked={form.officer_details_officially_provided} onChange={(e) => setForm({ ...form, officer_details_officially_provided: e.target.checked })} className="h-4 w-4 accent-brand-500" />
            Officer name/designation was officially provided
          </label>
          {form.officer_details_officially_provided ? (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Officer name"><Input value={form.officer_name} onChange={(e) => setForm({ ...form, officer_name: e.target.value })} /></Field>
              <Field label="Designation"><Input value={form.officer_designation} onChange={(e) => setForm({ ...form, officer_designation: e.target.value })} /></Field>
            </div>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCreating(false)}>Cancel</Button>
            <Button onClick={create}>Create (checklist auto-generated)</Button>
          </div>
        </div>
      </Modal>

      <Modal open={!!detail} onClose={() => setDetail(null)} title={detail?.department || "Inspection"} wide>
        {detail ? (
          <div className="space-y-4">
            <div className="flex gap-2"><StatusBadge value={detail.status} />{detail.inspection_date ? <Badge tone="blue">{detail.inspection_date}</Badge> : null}</div>
            <div>
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Preparation checklist</h4>
              <div className="space-y-1.5">
                {(detail.checklist || []).map((c: any, i: number) => (
                  <label key={i} className="flex items-center gap-3 rounded-lg border border-white/8 bg-white/4 px-3 py-2 text-[13px]">
                    <input type="checkbox" checked={!!c.done} onChange={() => toggleCheck(detail, i)} className="h-4 w-4 accent-brand-500" />
                    <span className={c.done ? "text-slate-500 line-through" : "text-slate-200"}>{c.item}</span>
                  </label>
                ))}
              </div>
            </div>
            <div>
              <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Findings</h4>
              <Textarea value={findings} onChange={(e) => setFindings(e.target.value)} placeholder="Record findings verbatim…" />
              <Button size="sm" className="mt-2" onClick={async () => {
                const status = findings && detail.status === "SCHEDULED" ? "COMPLETED" : detail.status;
                const r = await api<any>(`/projects/${projectId}/inspections/${detail.id}`, "PATCH", { findings, status });
                setDetail(r.inspection); await load();
              }}>Save findings</Button>
            </div>
            <Disclaimer tone="violet">NIECP-AI helps you organise the checklist — it never impersonates an official or predicts outcomes.</Disclaimer>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
