/** Compliance tasks (spec §21). */
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import { Badge, Button, Card, EmptyState, Field, Input, Modal, Select, Spinner, StatusBadge, Tabs, Textarea } from "../components/ui";

export default function Compliance() {
  const { projectId } = useParams();
  const [tasks, setTasks] = useState<any[]>([]);
  const [tab, setTab] = useState("OPEN");
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ title: "", description: "", priority: "MEDIUM", due_date: "" });
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    const r = await api<any>(`/projects/${projectId}/compliance`);
    setTasks(r.tasks);
    setLoading(false);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [projectId]);

  const create = async () => {
    await api(`/projects/${projectId}/compliance`, "POST", form);
    setCreating(false);
    setForm({ title: "", description: "", priority: "MEDIUM", due_date: "" });
    await load();
  };

  const setTaskStatus = async (id: number, status: string) => {
    await api(`/projects/${projectId}/compliance/${id}`, "PATCH", { status });
    await load();
  };

  const filtered = tasks.filter((t) => (tab === "ALL" ? true : tab === "DONE" ? t.status === "DONE" : t.status !== "DONE"));
  const overdue = (t: any) => t.due_date && t.status !== "DONE" && new Date(t.due_date) < new Date();

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Compliance tasks</h1>
          <p className="text-[12.5px] text-slate-500">Generated from your approvals, documents and calendar — or add your own.</p>
        </div>
        <Button onClick={() => setCreating(true)}>+ Add task</Button>
      </div>

      <Tabs tabs={[{ key: "OPEN", label: "Open", count: tasks.filter((t) => t.status !== "DONE").length }, { key: "DONE", label: "Done", count: tasks.filter((t) => t.status === "DONE").length }, { key: "ALL", label: "All" }]} active={tab} onChange={setTab} />

      {loading ? <Spinner /> : filtered.length === 0 ? (
        <EmptyState icon="✅" title="No tasks here" hint="Tasks appear from the approval analysis, document findings and calendar." />
      ) : (
        <div className="space-y-2">
          {filtered.map((t) => (
            <Card key={t.id} className="flex items-center gap-3 p-3.5">
              <button
                onClick={() => setTaskStatus(t.id, t.status === "DONE" ? "OPEN" : "DONE")}
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs ${t.status === "DONE" ? "border-emerald-500 bg-emerald-500 text-white" : "border-white/25 text-transparent hover:border-brand-400"}`}
                aria-label={t.status === "DONE" ? "Mark open" : "Mark done"}
              >✓</button>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  {t.is_demo ? <Badge tone="violet">DEMO</Badge> : null}
                  <span className={`text-[13.5px] font-medium ${t.status === "DONE" ? "text-slate-500 line-through" : "text-slate-100"}`}>{t.title}</span>
                  <Badge tone={t.priority === "CRITICAL" ? "red" : t.priority === "HIGH" ? "amber" : "slate"}>{t.priority}</Badge>
                  {overdue(t) ? <Badge tone="red">overdue</Badge> : null}
                </div>
                {t.description ? <p className="mt-0.5 line-clamp-1 text-[12px] text-slate-500">{t.description}</p> : null}
              </div>
              {t.due_date ? <Badge tone={overdue(t) ? "red" : "slate"}>due {t.due_date}</Badge> : null}
              <StatusBadge value={t.status} />
            </Card>
          ))}
        </div>
      )}

      <Modal open={creating} onClose={() => setCreating(false)} title="Add compliance task">
        <div className="space-y-3">
          <Field label="Title" required><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} autoFocus /></Field>
          <Field label="Description"><Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Priority">
              <Select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                {["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((p) => <option key={p}>{p}</option>)}
              </Select>
            </Field>
            <Field label="Due date"><Input type="date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} /></Field>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCreating(false)}>Cancel</Button>
            <Button disabled={!form.title.trim()} onClick={create}>Add task</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
