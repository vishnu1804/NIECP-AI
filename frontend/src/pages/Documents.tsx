/** Document centre (spec §9, §10): upload, validate, versions, expiry. */
import React, { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import { Badge, Button, Card, CardHeader, Disclaimer, EmptyState, Field, Input, Modal, Select, Spinner, StatusBadge, Tabs } from "../components/ui";

const CATEGORIES = ["IDENTITY", "BUSINESS", "LAND", "FINANCIAL", "TECHNICAL", "ENVIRONMENTAL", "SAFETY", "LABOUR", "GOVERNMENT_CERTIFICATE", "PROJECT_REPORT", "OTHER"];

export default function Documents() {
  const { projectId } = useParams();
  const [data, setData] = useState<any>(null);
  const [tab, setTab] = useState("all");
  const [q, setQ] = useState("");
  const [uploading, setUploading] = useState(false);
  const [detail, setDetail] = useState<any>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [form, setForm] = useState({ title: "", category: "OTHER" });

  const load = async () => setData(await api<any>(`/projects/${projectId}/documents${q ? `?q=${encodeURIComponent(q)}` : ""}`));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [projectId]);

  const upload = async (file: File) => {
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("title", form.title || file.name);
      fd.append("category", form.category);
      await api(`/projects/${projectId}/documents`, "POST", fd);
      await load();
    } catch (e: any) {
      alert(e?.message || "Upload failed.");
    } finally {
      setUploading(false);
      setForm({ title: "", category: "OTHER" });
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const rows = (data?.documents || []).filter((d: any) => {
    if (tab === "expired") return d.status === "EXPIRED";
    if (tab === "attention") return d.validation?.counts?.warning > 0 || d.validation?.counts?.error > 0;
    return true;
  });

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-white">Document centre</h1>
          <p className="text-[12.5px] text-slate-500">Upload once — classification, field extraction and profile comparison run automatically.</p>
        </div>
        <label className="cursor-pointer">
          <input ref={fileRef} type="file" className="hidden" accept=".pdf,.jpg,.jpeg,.png,.webp,.doc,.docx,.xls,.xlsx,.csv,.txt,.xml,.zip"
            onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          <span className="inline-flex items-center gap-2 rounded-xl bg-brand-500 px-4 py-2 text-sm font-medium text-white shadow hover:bg-brand-600">
            {uploading ? <Spinner /> : "⬆"} Upload document
          </span>
        </label>
      </div>

      <Card className="p-4">
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Default title for next upload"><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Leave blank to use the filename" /></Field>
          <Field label="Default category">
            <Select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              {CATEGORIES.map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
            </Select>
          </Field>
        </div>
        <p className="mt-2 text-[11px] text-slate-600">
          Files stay in your project's secure storage. Processing is transparent: if text cannot be extracted (e.g. a photo of a document without OCR available), the document is flagged rather than silently accepted.
        </p>
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <Tabs tabs={[{ key: "all", label: "All", count: data?.documents?.length }, { key: "attention", label: "Needs attention" }, { key: "expired", label: "Expired" }]} active={tab} onChange={setTab} />
        <Input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load()} placeholder="Search documents…" className="max-w-56" />
      </div>

      {rows.length === 0 ? (
        <EmptyState icon="📄" title="No documents here yet" hint="Upload incorporation certificates, land documents, consents — the AI classifies and cross-checks each one." />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {rows.map((d: any) => (
            <Card key={d.id} className="p-4" onClick={() => setDetail(d)}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    {d.is_demo ? <Badge tone="violet">DEMO</Badge> : null}
                    <h3 className="truncate text-[13.5px] font-semibold text-slate-100">{d.title}</h3>
                  </div>
                  <div className="mt-0.5 text-[11px] text-slate-500">
                    {d.category?.replace(/_/g, " ")} · {d.ai_document_type || "type not determined"}
                  </div>
                </div>
                <StatusBadge value={d.status} />
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {d.expiry_date ? <Badge tone={new Date(d.expiry_date) < new Date() ? "red" : "amber"}>expires {d.expiry_date}</Badge> : null}
                {d.validation?.counts?.warning ? <Badge tone="amber">{d.validation.counts.warning} warning(s)</Badge> : null}
                {d.validation?.counts?.error ? <Badge tone="red">{d.validation.counts.error} issue(s)</Badge> : null}
                {d.validation?.counts?.pass ? <Badge tone="green">{d.validation.counts.pass} check(s) passed</Badge> : null}
                {d.has_file ? null : <Badge tone="slate">metadata only</Badge>}
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal open={!!detail} onClose={() => setDetail(null)} title={detail?.title || ""} wide>
        {detail ? (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <StatusBadge value={detail.status} />
              <Badge tone="slate">{detail.category?.replace(/_/g, " ")}</Badge>
              {detail.ai_classification_confidence ? <Badge tone="blue">{Math.round(detail.ai_classification_confidence * 100)}% type confidence</Badge> : null}
            </div>

            <div className="grid grid-cols-2 gap-3 text-[12.5px]">
              <div><span className="text-slate-500">File:</span> {detail.original_filename}</div>
              <div><span className="text-slate-500">Size:</span> {detail.size_bytes ? `${(detail.size_bytes / 1024).toFixed(0)} KB` : "—"}</div>
              <div><span className="text-slate-500">Expiry:</span> {detail.expiry_date || "not recorded"}</div>
              <div><span className="text-slate-500">Version:</span> v{detail.current_version}</div>
            </div>

            {detail.has_file ? (
              <a href={`/api/v1/projects/${projectId}/documents/${detail.id}/download`} target="_blank" rel="noopener noreferrer">
                <Button size="sm" variant="outline">Download</Button>
              </a>
            ) : (
              <Disclaimer tone="blue">This is a metadata record (demo seed). Upload a real file to run validation.</Disclaimer>
            )}

            <div>
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">AI validation findings</h4>
              <div className="space-y-1.5">
                {(detail.validation?.findings || []).map((f: any, i: number) => (
                  <div key={i} className="rounded-lg border border-white/8 bg-white/4 px-3 py-2">
                    <div className="flex items-center justify-between">
                      <span className="text-[13px] font-medium text-slate-200">{f.title}</span>
                      <StatusBadge value={f.severity === "PASS" ? "COMPLETED" : f.severity} label={f.severity} />
                    </div>
                    {f.detail ? <p className="mt-0.5 text-[12px] leading-relaxed text-slate-500">{f.detail}</p> : null}
                  </div>
                ))}
              </div>
              {detail.validation?.disclaimer ? <div className="mt-2"><Disclaimer tone="violet">{detail.validation.disclaimer}</Disclaimer></div> : null}
            </div>

            {detail.text_preview ? (
              <div>
                <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Extracted text (preview)</h4>
                <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded-lg border border-white/8 bg-ink-900 p-3 text-[11px] text-slate-400">{detail.text_preview}</pre>
              </div>
            ) : null}

            <div className="flex gap-2 border-t border-white/10 pt-3">
              <Button size="sm" variant="outline" onClick={async () => {
                await api(`/projects/${projectId}/documents/${detail.id}/validate`, "POST", {});
                await load();
                setDetail(null);
              }}>Re-run validation</Button>
              <Button size="sm" variant="danger" onClick={async () => {
                if (!confirm("Delete this document? This is recorded in the audit log.")) return;
                await api(`/projects/${projectId}/documents/${detail.id}`, "DELETE");
                setDetail(null);
                await load();
              }}>Delete</Button>
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
