/** Projects list + create (spec §32). */
import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { Badge, Button, Card, EmptyState, Field, Input, Modal, Progress, Spinner, StatusBadge, Textarea } from "../components/ui";

export default function Projects() {
  const { projects, refreshProjects, setActiveProjectId } = useApp();
  const [params] = useSearchParams();
  const [open, setOpen] = useState(params.get("new") === "1");
  const [form, setForm] = useState({ name: "", description: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const navigate = useNavigate();

  const create = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api<any>("/projects", "POST", form);
      await refreshProjects();
      setActiveProjectId(r.project.id);
      setOpen(false);
      setForm({ name: "", description: "" });
      navigate(`/projects/${r.project.id}/profile`);
    } catch (e: any) {
      setErr(e?.message || "Could not create project.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Projects</h1>
          <p className="text-[12.5px] text-slate-500">Each project keeps its own profile, approvals, documents, applications, compliance and AI context.</p>
        </div>
        <Button onClick={() => setOpen(true)}>+ New project</Button>
      </div>

      {projects.length === 0 ? (
        <EmptyState icon="🏗️" title="No projects yet" hint="A project can be a factory, a warehouse, a solar plant — anything that needs approvals." action={<Button onClick={() => setOpen(true)}>Create your first project</Button>} />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {projects.map((p) => (
            <Card key={p.id} className="p-5" onClick={() => { setActiveProjectId(p.id); navigate(`/projects/${p.id}`); }}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="truncate text-[15px] font-semibold text-slate-100">{p.name}</h3>
                    {p.is_demo ? <Badge tone="violet">DEMO</Badge> : null}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11.5px] text-slate-500">
                    <StatusBadge value={p.stage} />
                    {p.industry ? <span>{p.industry.replace(/_/g, " ")}</span> : null}
                    {p.state ? <span>· {p.state}</span> : null}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-xl font-bold text-teal-glow">{p.readiness_overall ?? "—"}</div>
                  <div className="text-[10px] uppercase tracking-wide text-slate-600">ready %</div>
                </div>
              </div>
              <div className="mt-3"><Progress value={p.readiness_overall ?? 0} height="h-1.5" label={p.name} /></div>
              <div className="mt-3 flex gap-3 text-[11px] text-slate-500">
                <span>🗂️ {p.counts?.approvals_applies ?? 0} approvals</span>
                <span>📄 {p.counts?.documents ?? 0} docs</span>
                <span>📮 {p.counts?.applications ?? 0} applications</span>
                <span>✅ {p.counts?.open_tasks ?? 0} tasks</span>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title="Create a project">
        <div className="space-y-4">
          <Field label="Project name" required>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Food processing unit — Erode" autoFocus />
          </Field>
          <Field label="Description (optional)">
            <Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          {err ? <p className="text-xs text-rose-300">{err}</p> : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            <Button disabled={form.name.trim().length < 2 || busy} onClick={create}>{busy ? <Spinner /> : null}Create & set up profile</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
