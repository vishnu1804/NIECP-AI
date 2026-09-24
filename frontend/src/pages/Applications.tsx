/** Applications + Get Approval workflow (spec §14, §15) with the Government
 * Integration Manager channels (Master Upgrade Prompt §22, §24): DEMO /
 * OFFICIAL_REDIRECT / MANUAL execution, demo workflow simulation panel with
 * query translation, and full provenance on every status. */
import React, { useEffect, useRef, useState } from "react";
import { useSearchParams, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { Badge, Button, Card, Disclaimer, EmptyState, Field, Input, Modal, ProvenanceRow, Select, Spinner, StatusBadge, Textarea } from "../components/ui";

const STATUS_FLOW = ["DRAFT", "READY_TO_APPLY", "USER_CONFIRMED", "SUBMITTED", "UNDER_REVIEW", "QUERY_RAISED", "USER_RESPONDED", "INSPECTION", "APPROVED", "REJECTED", "WITHDRAWN", "EXPIRED", "RENEWAL_DUE", "CANCELLED"];

const MODE_BADGE: Record<string, { tone: any; label: string }> = {
  DEMO: { tone: "amber", label: "🟡 DEMO" },
  OFFICIAL_REDIRECT: { tone: "blue", label: "🔗 OFFICIAL PORTAL" },
  MANUAL: { tone: "slate", label: "✍️ MANUAL" },
  LIVE: { tone: "green", label: "🟢 LIVE API" },
};

function ModeBadge({ mode }: { mode?: string | null }) {
  if (!mode) return null;
  const b = MODE_BADGE[mode] || { tone: "slate", label: mode };
  return <Badge tone={b.tone}>{b.label}</Badge>;
}

export default function Applications() {
  const { projectId } = useParams();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<any>(null);
  const [detail, setDetail] = useState<any>(null);
  const [demoView, setDemoView] = useState<any>(null);
  const [creating, setCreating] = useState(!!params.get("new"));
  const [newForm, setNewForm] = useState({ title: "", approval_template_code: params.get("new") || "", authority: "" });
  const [catalogue, setCatalogue] = useState<any>({ approvals: [] });
  const [busy, setBusy] = useState(false);
  const [refForm, setRefForm] = useState({ official_reference: "", confirm: false });
  const [demoConsent, setDemoConsent] = useState(false);
  const [options, setOptions] = useState<any>(null);
  const [responseForm, setResponseForm] = useState<{ [qid: number]: { text: string; confirm: boolean } }>({});
  const [pkg, setPkg] = useState<any>(null);
  const [handoff, setHandoff] = useState<any>(null);
  const pollRef = useRef<any>(null);

  const load = async () => setData(await api<any>(`/projects/${projectId}/applications`));

  const loadPackage = async () => {
    try { setPkg(await api<any>(`/projects/${projectId}/application-package`)); } catch { setPkg(null); }
  };
  const runHandoff = async () => {
    try { setHandoff(await api(`/projects/${projectId}/maitri-handoff`, "POST", {})); loadPackage(); } catch (e: any) { setHandoff({ ok: false, message: e?.message || "Handoff failed." }); }
  };

  const loadOptions = async (id: number) => {
    try { setOptions(await api<any>(`/projects/${projectId}/applications/${id}/execution-options`)); } catch { setOptions(null); }
  };

  const openDetail = async (a: any) => {
    setDetail(a);
    setRefForm({ official_reference: a.official_reference || "", confirm: false });
    setDemoConsent(false);
    setDemoView(null);
    loadOptions(a.id);
    if (a.is_demo) refreshDemo(a.id);
    else if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };

  const refreshDemo = async (id?: number) => {
    const appId = id ?? detail?.id;
    if (!appId) return;
    try {
      const v = await api<any>(`/demo/government/applications/${appId}`);
      setDemoView(v);
      if (["SUBMITTED", "UNDER_REVIEW", "USER_RESPONDED"].includes(v.status)) {
        if (!pollRef.current) {
          pollRef.current = setInterval(() => refreshDemo(appId), 5000);
        }
      } else if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    } catch { /* demo unavailable */ }
  };

  useEffect(() => {
    load(); loadPackage();
    api(`/projects/${projectId}/approvals`).then((r) => setCatalogue(r)).catch(() => {});
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
    // eslint-disable-next-line
  }, [projectId]);

  useEffect(() => {
    if (detail && !detail.is_demo) return;
    if (detail) openDetail(detail); // refresh detail from list data after load()
    // eslint-disable-next-line
  }, [data]);

  const create = async () => {
    setBusy(true);
    try {
      const r = await api<any>(`/projects/${projectId}/applications`, "POST", newForm);
      setCreating(false);
      setParams({});
      await load();
      openDetail(r.application);
    } catch (e: any) {
      alert(e?.message || "Could not create the application.");
    } finally {
      setBusy(false);
    }
  };

  const prepare = async (id: number) => {
    const r = await api<any>(`/projects/${projectId}/applications/${id}/prepare`, "POST", {});
    setDetail(r.application);
    await load();
    loadOptions(id);
  };

  const confirm = async (id: number) => {
    const r = await api<any>(`/projects/${projectId}/applications/${id}/confirm`, "POST", {});
    setDetail(r.application);
    await load();
    loadOptions(id);
  };

  const setStatus = async (id: number, status: string) => {
    try {
      const r = await api<any>(`/projects/${projectId}/applications/${id}/status`, "POST", {
        status,
        self_reported_confirmation: true,
        reason: `Status updated to ${status} by user (self-reported)`,
      });
      setDetail(r.application);
      await load();
    } catch (e: any) {
      alert(e?.message);
    }
  };

  const downloadPacket = async (id: number) => {
    try {
      const r = await fetch(`/api/v1/projects/${projectId}/applications/${id}/manual-packet?format=text`, {
        headers: { Authorization: `Bearer ${localStorage.getItem("niecp.access") || ""}` },
      });
      if (!r.ok) throw new Error("Could not generate the packet.");
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `application-${id}-packet.txt`; a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) { alert(e?.message); }
  };

  const runDemo = async (id: number) => {
    try {
      const r = await api<any>(`/demo/government/applications`, "POST", { project_id: Number(projectId), application_id: id, demo_confirmation: true });
      await load();
      await openDetail({ ...detail, is_demo: true, official_reference: r.application_reference });
      refreshDemo(id);
    } catch (e: any) {
      alert(e?.message);
    }
  };

  const openRedirect = async (id: number) => {
    try {
      const r = await api<any>(`/projects/${projectId}/applications/${id}/redirect`, "POST", {});
      window.open(r.redirect.portal_url, "_blank", "noopener");
    } catch (e: any) {
      alert(e?.message);
    }
  };

  const demoRespond = async (qid: number) => {
    const form = responseForm[qid];
    if (!form?.text?.trim()) return;
    try {
      await api<any>(`/demo/government/applications/${detail.id}/response`, "POST", { query_id: qid, response_text: form.text, confirm_response_submission: form.confirm });
      setResponseForm({ ...responseForm, [qid]: { text: "", confirm: false } });
      await load();
      refreshDemo();
    } catch (e: any) {
      alert(e?.message);
    }
  };

  const translateQuery = async (qid: number) => {
    try {
      const r = await api<any>(`/projects/${projectId}/queries/${qid}/translate`, "POST", {});
      setDemoView((v: any) => v ? {
        ...v,
        queries: v.queries.map((q: any) => q.id === qid ? { ...q, translator: r.translation } : q),
      } : v);
    } catch (e: any) {
      alert(e?.message);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Applications</h1>
          <p className="text-[12.5px] text-slate-500">Prepare here, then execute through the official portal (by you), the labelled demo environment, or manual record-keeping. NIECP-AI never submits to a government authority.</p>
        </div>
        <Button onClick={() => setCreating(true)}>+ New application</Button>
      </div>

      {/* Application package + MAITRI handoff (MVP §M/§N) */}
      {pkg ? (
        <Card className="p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-[13.5px] font-semibold text-white">Application package & MAITRI handoff</div>
              <div className="text-[11.5px] text-slate-500">
                {pkg.approvals.length} applicable approval(s) · {pkg.missing_items.length} missing item(s) · {pkg.validation_findings.length} validation finding(s) · readiness {pkg.readiness?.overall ?? "—"}% (submission readiness, not approval probability)
              </div>
            </div>
            {pkg.official_submission?.state_route ? (
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={runHandoff}>Prepare MAITRI handoff</Button>
                <a href={pkg.official_submission.state_route.url} target="_blank" rel="noopener noreferrer"><Button size="sm">Open official MAITRI portal ↗</Button></a>
              </div>
            ) : (
              <span className="text-[11px] text-slate-500">State route: use the portal directory for {String(pkg.project?.state_code || "your state")}</span>
            )}
          </div>
          {handoff ? (
            <div className={`mt-2 rounded-lg border p-2.5 text-[11.5px] ${handoff.ok ? "border-emerald-400/25 bg-emerald-400/8 text-emerald-100" : "border-amber-400/25 bg-amber-400/8 text-amber-100"}`}>
              <span className="font-semibold">{handoff.status?.replace(/_/g, " ")} — </span>{handoff.notice || handoff.message}
              {handoff.package_summary ? <> · approvals {handoff.package_summary.approvals} · missing {handoff.package_summary.missing_items} · readiness {handoff.package_summary.readiness ?? "—"}%</> : null}
            </div>
          ) : null}
          <p className="mt-2 text-[10.5px] text-slate-600">REAL: package contents from your project records · MANUAL: you file on the official portal · NOT CLAIMED: submission, officer response, submission ID, approval status.</p>
        </Card>
      ) : null}

      {!data ? <Spinner /> : data.applications.length === 0 ? (
        <EmptyState icon="📮" title="No applications yet" hint="Open an approval that applies and choose “Prepare application” to start the Get Approval workflow." />
      ) : (
        <div className="space-y-3">
          {data.applications.map((a: any) => (
            <Card key={a.id} className="p-4" onClick={() => openDetail(a)}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <ModeBadge mode={a.integration_mode} />
                    <h3 className="truncate text-[14px] font-semibold text-slate-100">{a.title}</h3>
                  </div>
                  <div className="mt-0.5 text-[12px] text-slate-500">
                    {a.authority}
                    {a.official_reference ? <> · ref <span className={`font-mono ${a.is_demo ? "text-amber-300/90" : "text-slate-400"}`}>{a.official_reference}</span>{a.is_demo ? " (synthetic)" : null}</> : null}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {a.lifecycle ? <Badge tone="blue">{String(a.lifecycle.stage).replace(/_/g, " ")}</Badge> : null}
                  {a.lifecycle?.sla_status && a.lifecycle.sla_status !== "NOT_STARTED" ? (
                    <Badge tone={a.lifecycle.sla_status === "BREACHED" ? "red" : a.lifecycle.sla_status === "APPROACHING" ? "amber" : a.lifecycle.sla_status === "PAUSED" ? "slate" : "green"}>
                      SLA: {String(a.lifecycle.sla_status).replace(/_/g, " ")}{a.lifecycle.simulated ? " · SIM" : ""}
                    </Badge>
                  ) : null}
                  {a.readiness_score != null ? <Badge tone={a.readiness_score >= 80 ? "green" : "amber"}>{a.readiness_score}% ready</Badge> : null}
                  <StatusBadge value={a.status} />
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* create modal */}
      <Modal open={creating} onClose={() => { setCreating(false); setParams({}); }} title="New application">
        <div className="space-y-4">
          <Field label="Which approval?" hint="From your project's approval map.">
            <Select value={newForm.approval_template_code} onChange={(e) => {
              const code = e.target.value;
              const found = (catalogue.approvals || []).find((a: any) => a.template_code === code);
              setNewForm({ ...newForm, approval_template_code: code, title: found ? found.name : newForm.title, authority: found?.authority || "" });
            }}>
              <option value="">Select an approval…</option>
              {(catalogue.approvals || []).filter((a: any) => a.applicability !== "NOT_APPLICABLE").map((a: any) => (
                <option key={a.template_code} value={a.template_code}>{a.name}</option>
              ))}
            </Select>
          </Field>
          <Field label="Title"><Input value={newForm.title} onChange={(e) => setNewForm({ ...newForm, title: e.target.value })} /></Field>
          <Field label="Authority"><Input value={newForm.authority} onChange={(e) => setNewForm({ ...newForm, authority: e.target.value })} /></Field>
          <Disclaimer tone="blue">After creating, NIECP-AI builds a preparation package from your profile and documents. Execution options are shown honestly: the official portal (you file), the labelled demo environment, or manual record-keeping.</Disclaimer>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => { setCreating(false); setParams({}); }}>Cancel</Button>
            <Button disabled={!newForm.approval_template_code || busy} onClick={create}>{busy ? <Spinner /> : null}Create</Button>
          </div>
        </div>
      </Modal>

      {/* detail modal — Get Approval steps + execution channels */}
      <Modal open={!!detail} onClose={() => { setDetail(null); if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } }} title={detail?.title || ""} wide>
        {detail ? (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <StatusBadge value={detail.status} />
              <ModeBadge mode={detail.integration_mode} />
              <Badge tone="slate">channel: {detail.submission_channel?.replace(/_/g, " ")}</Badge>
              {detail.official_reference ? <Badge tone={detail.is_demo ? "amber" : "slate"}><span className="font-mono">{detail.official_reference}</span>{detail.is_demo ? " · synthetic" : ""}</Badge> : null}
              {detail.readiness_score != null ? <Badge tone={detail.readiness_score >= 80 ? "green" : "amber"}>{detail.readiness_score}% ready</Badge> : null}
            </div>

            {/* ── execution channels (spec §24) ── */}
            {!detail.is_demo && options ? (
              <div className="rounded-xl border border-white/8 bg-white/4 p-3.5">
                <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">How will you file this application?</h4>
                <div className="flex flex-wrap gap-2">
                  {options.channels.OFFICIAL_REDIRECT.available ? (
                    <Button size="sm" onClick={() => openRedirect(detail.id)}>🌐 Open official government portal ↗</Button>
                  ) : null}
                  {options.channels.DEMO.available ? (
                    <Button size="sm" variant="outline" disabled={!detail.prepared_at || !detail.user_confirmed_at}
                      onClick={() => setDemoConsent(true)}>
                      🟡 Run demo application
                    </Button>
                  ) : null}
                  <Button size="sm" variant="ghost" onClick={() => downloadPacket(detail.id)}>⬇️ Download manual packet</Button>
                </div>
                {options.channels.DEMO.available && !detail.prepared_at ? <p className="mt-2 text-[11.5px] text-slate-500">Prepare the package and confirm it before running the demo.</p> : null}
                {options.channels.OFFICIAL_REDIRECT.available ? (
                  <p className="mt-2 text-[11.5px] text-slate-500">{options.channels.OFFICIAL_REDIRECT.notice}</p>
                ) : (
                  <p className="mt-2 text-[11.5px] text-amber-300/80">{options.channels.OFFICIAL_REDIRECT.reason}</p>
                )}
                {options.readiness?.blockers?.length ? (
                  <p className="mt-2 text-[11.5px] text-amber-300/80">Readiness warnings ({options.readiness.blockers.length}): {options.readiness.blockers.slice(0, 3).join(" · ")}{options.readiness.blockers.length > 3 ? "…" : ""}</p>
                ) : null}
                <p className="mt-2 text-[11px] text-slate-600">{options.declaration}</p>
              </div>
            ) : null}

            {/* demo consent gate (§48) */}
            {demoConsent && !detail.is_demo ? (
              <div className="rounded-xl border border-amber-400/30 bg-amber-400/8 p-3.5">
                <h4 className="text-[12.5px] font-semibold text-amber-200">🟡 DEMO — SYNTHETIC DATA</h4>
                <p className="mt-1 text-[12px] text-amber-100/80">You are about to submit this application to the NIECP demonstration environment using synthetic data. Demonstration workflow only — not connected to a live government system. Nothing is sent to any government authority.</p>
                <div className="mt-3 flex gap-2">
                  <Button size="sm" variant="danger" onClick={() => { setDemoConsent(false); runDemo(detail.id); }}>RUN DEMO</Button>
                  <Button size="sm" variant="ghost" onClick={() => setDemoConsent(false)}>CANCEL</Button>
                </div>
              </div>
            ) : null}

            {/* ── demo workflow simulation (§7, §8, §22) ── */}
            {demoView ? (
              <div className="rounded-xl border border-amber-400/25 bg-amber-400/6 p-3.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h4 className="text-[12.5px] font-semibold text-amber-200">🟡 DEMO WORKFLOW SIMULATION · <span className="font-mono">{demoView.application_reference}</span></h4>
                  <div className="flex gap-2">
                    <Button size="sm" variant="ghost" onClick={() => refreshDemo()}>↻ Refresh status</Button>
                    {demoView.status === "USER_RESPONDED" ? (
                      <Button size="sm" variant="ghost" title="Demo control — advance the simulation" onClick={async () => { await api<any>(`/demo/government/applications/${demoView.application_id}/advance`, "POST", {}); refreshDemo(); }}>⏩ Advance (demo control)</Button>
                    ) : null}
                  </div>
                </div>
                <p className="mt-1 text-[11px] text-amber-100/60">{demoView.notice}</p>
                <p className="mt-1 text-[11px] text-slate-500">Demo environment: {demoView.demo?.environment} · data: {demoView.demo?.data_source} · government API: {demoView.demo?.government_api}</p>

                {/* demo timeline */}
                <div className="mt-3 space-y-1">
                  {demoView.timeline?.slice().reverse().map((h: any, i: number) => (
                    <div key={i} className="flex items-center gap-2 text-[11.5px] text-slate-400">
                      <StatusBadge value={h.status} />
                      <span className="text-slate-500">{h.reason}</span>
                      {h.at ? <span className="text-slate-600">· {new Date(h.at).toLocaleTimeString()}</span> : null}
                    </div>
                  ))}
                </div>

                {/* synthetic queries + translator */}
                {demoView.queries?.filter((q: any) => q.status !== "RESPONDED").map((q: any) => (
                  <div key={q.id} className="mt-3 rounded-lg border border-white/10 bg-ink-900/60 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[11px] font-semibold text-slate-400">{q.reference}</span>
                      <Badge tone="amber">QUERY_RAISED</Badge>
                    </div>
                    <p className="mt-1 whitespace-pre-wrap text-[12px] text-slate-300">{q.query_text}</p>
                    {q.translator ? (
                      <div className="mt-2 rounded-md border border-brand-400/20 bg-brand-500/8 p-2.5 text-[11.5px]">
                        <p className="font-semibold text-brand-200">AI translation (verify against the official communication):</p>
                        <p className="mt-1 text-slate-300">{q.translator.plain_language_explanation}</p>
                        {q.translator.what_is_needed?.length ? (
                          <p className="mt-1 text-slate-400">Needed: {q.translator.what_is_needed.map((n: any) => n.document).join(" · ")}</p>
                        ) : null}
                        <p className="mt-1 text-[10.5px] text-slate-500">{q.translator.disclaimer}</p>
                      </div>
                    ) : (
                      <Button size="sm" variant="ghost" onClick={() => translateQuery(q.id)}>✨ Explain this query (AI)</Button>
                    )}
                    <Textarea className="mt-2" rows={3} placeholder="Point-by-point response…" value={responseForm[q.id]?.text || ""} onChange={(e) => setResponseForm({ ...responseForm, [q.id]: { text: e.target.value, confirm: responseForm[q.id]?.confirm || false } })} />
                    <label className="mt-1.5 flex items-start gap-2 text-[11px] text-slate-400">
                      <input type="checkbox" checked={responseForm[q.id]?.confirm || false} onChange={(e) => setResponseForm({ ...responseForm, [q.id]: { text: responseForm[q.id]?.text || "", confirm: e.target.checked } })} className="mt-0.5 h-3.5 w-3.5 accent-brand-500" />
                      File this response in the demo environment (synthetic).
                    </label>
                    <Button size="sm" className="mt-2" disabled={!responseForm[q.id]?.confirm || !responseForm[q.id]?.text?.trim()} onClick={() => demoRespond(q.id)}>Submit response</Button>
                  </div>
                ))}

                {/* synthetic decision */}
                {demoView.status === "APPROVED" ? (
                  <div className="mt-3 rounded-lg border border-emerald-400/25 bg-emerald-400/8 p-3">
                    <p className="text-[12px] font-semibold text-emerald-200">Synthetic approval · valid until {demoView.valid_until}</p>
                    <ul className="mt-1 list-disc pl-4 text-[11.5px] text-slate-300">
                      {(demoView.demo_approval_conditions || []).map((c: string, i: number) => <li key={i}>{c}</li>)}
                    </ul>
                    <p className="mt-1 text-[10.5px] text-slate-500">A renewal task was created and the compliance calendar tracks it — all within the demo environment.</p>
                  </div>
                ) : null}
              </div>
            ) : null}

            {/* workflow stepper (manual / self-reported recording) */}
            <div>
              <div className="flex flex-wrap gap-1.5">
                {STATUS_FLOW.map((s) => (
                  <button key={s} onClick={() => setStatus(detail.id, s)}
                    className={`rounded-lg px-2 py-1 text-[10.5px] font-medium transition-colors ${s === detail.status ? "bg-brand-500 text-white" : "border border-white/10 text-slate-500 hover:text-slate-300"}`}
                    title="Record this status (self-reported)">
                    {s.replace(/_/g, " ")}
                  </button>
                ))}
              </div>
              <Disclaimer tone="violet">Status buttons record what the authority actually communicated with you (portal, letter, email). NIECP-AI never invents government status — every change is audit-logged as user-reported.</Disclaimer>
            </div>

            <div className="rounded-xl border border-white/8 bg-white/4 p-3.5">
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Timeline</h4>
              {detail.history?.map((h: any, i: number) => (
                <ProvenanceRow key={i} label={new Date(h.at).toLocaleString()} value={<span className="flex items-center gap-2"><StatusBadge value={h.status} /> <span className="text-[11px] text-slate-500">{h.source_status?.replace(/_/g, " ")}</span></span>} />
              ))}
            </div>

            {detail.preparation_summary?.requirements ? (
              <div>
                <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Preparation package</h4>
                <div className="space-y-1">
                  {detail.preparation_summary.requirements.map((r: any, i: number) => (
                    <div key={i} className="flex items-center gap-2 rounded-lg border border-white/8 bg-white/4 px-3 py-1.5 text-[12.5px]">
                      <span>{r.satisfied ? "✅" : "⬜"}</span>
                      <span className={r.satisfied ? "text-slate-500 line-through" : "text-slate-200"}>{r.title}</span>
                    </div>
                  ))}
                </div>
                {detail.preparation_summary.profile_facts_missing?.length ? (
                  <p className="mt-2 text-[11.5px] text-amber-300/80">Profile facts that would strengthen this application: {detail.preparation_summary.profile_facts_missing.join(", ")}</p>
                ) : null}
              </div>
            ) : null}

            {/* official reference */}
            <div className="rounded-xl border border-white/8 bg-white/4 p-3.5">
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Official reference (from the authority)</h4>
              <div className="flex gap-2">
                <Input value={refForm.official_reference} onChange={(e) => setRefForm({ ...refForm, official_reference: e.target.value })} placeholder="Acknowledgement / application number from the portal" />
              </div>
              <label className="mt-2 flex items-start gap-2 text-[11.5px] text-slate-400">
                <input type="checkbox" checked={refForm.confirm} onChange={(e) => setRefForm({ ...refForm, confirm: e.target.checked })} className="mt-0.5 h-3.5 w-3.5 accent-brand-500" />
                I confirm this reference comes from the authority (portal acknowledgement, letter or communication) — not generated by NIECP-AI.
              </label>
              <Button size="sm" className="mt-2" variant="outline" disabled={!refForm.confirm || !refForm.official_reference.trim()}
                onClick={async () => {
                  const r = await api<any>(`/projects/${projectId}/applications/${detail.id}`, "PATCH", { official_reference: refForm.official_reference, official_reference_confirmation: true });
                  setDetail(r.application); await load();
                }}>
                Record reference
              </Button>
            </div>

            <div className="flex flex-wrap gap-2 border-t border-white/10 pt-3">
              {detail.prepared_at ? null : <Button size="sm" onClick={() => prepare(detail.id)}>🧰 Prepare package</Button>}
              {detail.prepared_at && !detail.user_confirmed_at ? <Button size="sm" variant="outline" onClick={() => confirm(detail.id)}>✋ Review & confirm</Button> : null}
              {detail.official_portal_url && !detail.is_demo ? (
                <a href={detail.official_portal_url} target="_blank" rel="noopener noreferrer"><Button size="sm">Open official portal ↗</Button></a>
              ) : null}
            </div>
            {detail.confirmation_text ? <Disclaimer tone="blue"><span className="font-semibold">Your confirmation on record:</span> {detail.confirmation_text}</Disclaimer> : null}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
