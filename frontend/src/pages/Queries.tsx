/** Government queries (spec §23). */
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import { Badge, Button, Card, CardHeader, Disclaimer, EmptyState, Field, Input, Modal, Spinner, StatusBadge, Tabs, Textarea } from "../components/ui";

export default function Queries() {
  const { projectId } = useParams();
  const [queries, setQueries] = useState<any[]>([]);
  const [creating, setCreating] = useState(false);
  const [detail, setDetail] = useState<any>(null);
  const [form, setForm] = useState({ authority: "", reference_number: "", query_text: "", deadline: "", date_received: new Date().toISOString().slice(0, 10) });
  const [response, setResponse] = useState({ text: "", confirm: false });
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    setQueries((await api<any>(`/projects/${projectId}/queries`)).queries);
    setLoading(false);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [projectId]);

  const create = async () => {
    await api(`/projects/${projectId}/queries`, "POST", form);
    setCreating(false);
    await load();
  };

  const overdue = (q: any) => q.deadline && q.status !== "CLOSED" && new Date(q.deadline) < new Date();
  const openCount = queries.filter((q) => q.status !== "CLOSED" && q.status !== "RESPONDED").length;

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Government queries</h1>
          <p className="text-[12.5px] text-slate-500">Record queries, get a structured response plan, and record your filed response.</p>
        </div>
        <Button onClick={() => setCreating(true)}>+ Record query</Button>
      </div>

      {loading ? <Spinner /> : queries.length === 0 ? (
        <EmptyState icon="💬" title="No queries on record" hint="When an authority asks for information — deficiency memo, show-cause notice, clarification request — record it here. NIECP-AI breaks it into pointable asks and maps likely documents." />
      ) : (
        <div className="space-y-3">
          {queries.map((q) => (
            <Card key={q.id} className="p-4" onClick={() => { setDetail(q); setResponse({ text: q.response_text || "", confirm: false }); }}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    {q.is_demo ? <Badge tone="violet">DEMO</Badge> : null}
                    <span className="text-[13.5px] font-semibold text-slate-100">{q.reference_number || q.authority || "Government query"}</span>
                    <Badge tone="slate">{q.authority}</Badge>
                  </div>
                  <p className="mt-1 line-clamp-2 text-[12.5px] leading-relaxed text-slate-400">{q.query_text}</p>
                  <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                    {q.deadline ? <Badge tone={overdue(q) ? "red" : "amber"}>deadline {q.deadline}</Badge> : <Badge tone="slate">no deadline recorded</Badge>}
                    {q.required_documents?.length ? <Badge tone="blue">{q.required_documents.length} document(s) asked</Badge> : null}
                  </div>
                </div>
                <StatusBadge value={q.status} />
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal open={creating} onClose={() => setCreating(false)} title="Record a government query" wide>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Authority"><Input value={form.authority} onChange={(e) => setForm({ ...form, authority: e.target.value })} placeholder="e.g. TNPCB" /></Field>
            <Field label="Reference number"><Input value={form.reference_number} onChange={(e) => setForm({ ...form, reference_number: e.target.value })} /></Field>
            <Field label="Date received"><Input type="date" value={form.date_received} onChange={(e) => setForm({ ...form, date_received: e.target.value })} /></Field>
            <Field label="Deadline" hint="Leave blank if none stated — never assume one."><Input type="date" value={form.deadline} onChange={(e) => setForm({ ...form, deadline: e.target.value })} /></Field>
          </div>
          <Field label="Query text" required hint="Paste the exact text — the decomposition works on the original wording.">
            <Textarea value={form.query_text} onChange={(e) => setForm({ ...form, query_text: e.target.value })} className="min-h-28" />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCreating(false)}>Cancel</Button>
            <Button disabled={form.query_text.trim().length < 5} onClick={create}>Save & analyse</Button>
          </div>
        </div>
      </Modal>

      <Modal open={!!detail} onClose={() => setDetail(null)} title={detail?.reference_number || "Query"} wide>
        {detail ? (
          <div className="space-y-4">
            <div className="flex gap-2"><StatusBadge value={detail.status} />{detail.deadline ? <Badge tone="amber">deadline {detail.deadline}</Badge> : null}</div>
            <div className="rounded-xl border border-white/8 bg-white/4 p-3.5 text-[13px] leading-relaxed text-slate-300">{detail.query_text}</div>
            {detail.translator?.plain_language_explanation || detail.ai_explanation ? (
              <div className="rounded-xl border border-brand-400/20 bg-brand-500/8 p-3.5">
                <h4 className="text-[11px] font-semibold uppercase tracking-wider text-brand-200">AI translation of this query</h4>
                <p className="mt-1.5 text-[13px] leading-relaxed text-slate-300">{detail.translator?.plain_language_explanation || detail.ai_explanation}</p>
                {detail.translator?.what_is_missing?.length ? (
                  <div className="mt-2">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">What is missing</p>
                    <ul className="mt-1 list-inside list-disc text-[12.5px] text-slate-300">
                      {detail.translator.what_is_missing.map((m: string, i: number) => <li key={i}>{m}</li>)}
                    </ul>
                  </div>
                ) : null}
                {detail.translator?.what_is_needed?.length ? (
                  <div className="mt-2">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">What is needed (mapped to your project)</p>
                    <ul className="mt-1 space-y-0.5 text-[12.5px] text-slate-300">
                      {detail.translator.what_is_needed.map((n: any, i: number) => (
                        <li key={i}>📄 <span className="font-medium">{n.document}</span> <span className="text-slate-500">— {n.match_reason}</span></li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {detail.translator?.recommended_action ? (
                  <p className="mt-2 text-[12.5px] text-teal-200">Recommended action: {detail.translator.recommended_action}</p>
                ) : null}
                {detail.translator?.response_preparation?.draft_outline?.length ? (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-[11.5px] text-brand-300">Response draft outline</summary>
                    <div className="mt-1.5 space-y-1">
                      {detail.translator.response_preparation.draft_outline.map((d: any, i: number) => (
                        <div key={i} className="rounded-md border border-white/10 bg-ink-900/50 px-2.5 py-1.5 text-[12px] text-slate-300">
                          <span className="font-semibold text-slate-200">Point {d.point}:</span> {d.original_ask}
                          {d.enclosure && !d.enclosure.startsWith("[") ? <span className="text-slate-500"> — enclose: {d.enclosure}</span> : null}
                        </div>
                      ))}
                    </div>
                  </details>
                ) : null}
                <p className="mt-2 text-[10.5px] text-slate-500">{detail.translator?.disclaimer || "AI-generated explanation — verify against the official communication."}{detail.translator?.note ? ` · ${detail.translator.note}` : ""}</p>
                <Button size="sm" variant="ghost" onClick={async () => {
                  try {
                    const r = await api<any>(`/projects/${projectId}/queries/${detail.id}/translate`, "POST", {});
                    setDetail({ ...detail, translator: r.translation, ai_explanation: r.translation.plain_language_explanation });
                    await load();
                  } catch (e: any) { alert(e?.message); }
                }}>✨ Re-run translation</Button>
              </div>
            ) : null}
            {detail.ai_suggested_steps?.length ? (
              <div>
                <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Suggested preparation steps</h4>
                <ol className="list-inside list-decimal space-y-1 text-[12.5px] text-slate-400">
                  {detail.ai_suggested_steps.map((s: string, i: number) => <li key={i}>{s}</li>)}
                </ol>
              </div>
            ) : null}

            <div className="border-t border-white/10 pt-3">
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Your response</h4>
              <Textarea value={response.text} onChange={(e) => setResponse({ ...response, text: e.target.value })} className="min-h-32" placeholder="Summarise the response you filed (or plan to file), point by point…" />
              <label className="mt-2 flex items-start gap-2 text-[11.5px] text-slate-400">
                <input type="checkbox" checked={response.confirm} onChange={(e) => setResponse({ ...response, confirm: e.target.checked })} className="mt-0.5 h-3.5 w-3.5 accent-brand-500" />
                I confirm this response was filed with the authority through their specified channel. NIECP-AI does not transmit responses.
              </label>
              <div className="mt-2 flex gap-2">
                <Button size="sm" disabled={!response.confirm || !response.text.trim()} onClick={async () => {
                  const r = await api<any>(`/projects/${projectId}/queries/${detail.id}`, "PATCH", { response_text: response.text, response_confirmation: true, status: "RESPONDED" });
                  setDetail(r.query); await load();
                }}>Record response</Button>
                <Button size="sm" variant="outline" onClick={async () => {
                  const r = await api<any>(`/projects/${projectId}/queries/${detail.id}`, "PATCH", { status: "CLOSED" });
                  setDetail(r.query); await load();
                }}>Mark closed</Button>
              </div>
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
