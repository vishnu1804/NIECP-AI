/** Approvals: discovery map, dependency graph, approval detail (spec §7, §11). */
import React, { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { Badge, Button, Card, CardHeader, Disclaimer, EmptyState, Modal, ProvenanceRow, SourceBadge, Spinner, StatusBadge, Tabs, confidenceLabel } from "../components/ui";
import ApprovalGraph from "../components/ApprovalGraph";

export default function Approvals() {
  const { projectId } = useParams();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<any>(null);
  const [graph, setGraph] = useState<any>({ nodes: [], edges: [] });
  const [tab, setTab] = useState<"list" | "graph">("graph");
  const [selected, setSelected] = useState<string | null>(params.get("approval"));
  const [detail, setDetail] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("active");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    const [a, g] = await Promise.all([
      api<any>(`/projects/${projectId}/approvals`),
      api<any>(`/projects/${projectId}/graph`),
    ]);
    setData(a);
    setGraph(g);
    setLoading(false);
    if (selected) openDetail(selected);
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [projectId]);

  const openDetail = async (code: string) => {
    setSelected(code);
    setParams(code ? { approval: code } : {});
    try {
      setDetail(await api<any>(`/projects/${projectId}/approvals/${code}`));
    } catch {
      setDetail(null);
    }
  };

  const act = async (action: string, extra: any = {}) => {
    if (!selected) return;
    setBusy(true);
    try {
      await api(`/projects/${projectId}/approvals/${selected}/action`, "POST", { action, ...extra });
      await load();
      await openDetail(selected);
      setGraph(await api<any>(`/projects/${projectId}/graph`));
    } finally {
      setBusy(false);
    }
  };

  const rows = (data?.approvals || []).filter((a: any) => {
    if (filter === "active") return a.applicability === "APPLIES" || a.applicability === "CONDITIONAL";
    if (filter === "applies") return a.applicability === "APPLIES";
    if (filter === "conditional") return a.applicability === "CONDITIONAL";
    if (filter === "critical") return a.is_on_critical_path;
    if (filter === "na") return a.applicability === "NOT_APPLICABLE";
    return true;
  });

  if (loading && !data) return <div className="flex justify-center py-20"><Spinner className="h-6 w-6" /></div>;

  const sel = (data?.approvals || []).find((a: any) => a.template_code === selected);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-white">Approval discovery map</h1>
          <p className="text-[12.5px] text-slate-500">Rule-engine determinations on your profile. Click any node for why it applies, its legal basis and the official portal.</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => api(`/projects/${projectId}/analysis`, "POST", {}).then(load)}>⚡ Re-run analysis</Button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          tabs={[
            { key: "graph", label: "Dependency graph" },
            { key: "list", label: "All approvals", count: data?.approvals?.length },
          ]}
          active={tab}
          onChange={(k) => setTab(k as any)}
        />
        {tab === "list" ? (
          <Tabs
            tabs={[
              { key: "active", label: "Applying" },
              { key: "critical", label: "Critical path" },
              { key: "na", label: "Not applicable" },
              { key: "all", label: "Everything" },
            ]}
            active={filter}
            onChange={setFilter}
          />
        ) : null}
      </div>

      {tab === "graph" ? (
        <Card className="p-4">
          <ApprovalGraph nodes={graph.nodes} edges={graph.edges} onSelect={openDetail} selected={selected} />
          <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-slate-500">
            {[["COMPLETED", "Complete"], ["READY", "Ready"], ["SUBMITTED", "Submitted"], ["WAITING", "Waiting / conditional"], ["BLOCKED", "Blocked"]].map(([k, label]) => (
              <span key={k} className="flex items-center gap-1.5">
                <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: { COMPLETED: "#10b981", READY: "#2dd4bf", SUBMITTED: "#3b82f6", WAITING: "#f59e0b", BLOCKED: "#ef4444" }[k as string] }} />
                {label}
              </span>
            ))}
            <span className="ml-auto flex items-center gap-1.5"><span className="inline-block h-2 w-2 rounded-full bg-teal-glow" />critical path</span>
          </div>
        </Card>
      ) : (
        <div className="space-y-2.5">
          {rows.length === 0 ? (
            <EmptyState icon="🗂️" title="No approvals in this view" hint="Run the analysis from the dashboard to evaluate the catalogue against your profile." />
          ) : rows.map((a: any) => (
            <Card key={a.template_code} className="p-4" onClick={() => openDetail(a.template_code)}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-[14px] font-semibold text-slate-100">{a.name}</h3>
                    {a.is_on_critical_path ? <Badge tone="teal">critical path</Badge> : null}
                  </div>
                  <div className="mt-0.5 text-[12px] text-slate-500">{a.authority}</div>
                  {a.why ? <p className="mt-1.5 line-clamp-2 text-[12px] leading-relaxed text-slate-400">{a.why}</p> : null}
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <StatusBadge value={a.applicability} />
                    <StatusBadge value={a.node_state} />
                    <SourceBadge status={a.source_status} />
                    <Badge tone={confidenceLabel(a.confidence).tone}>{confidenceLabel(a.confidence).label}</Badge>
                    <Badge tone="slate">{a.requirements.filter((r: any) => r.satisfied).length}/{a.requirements.length} docs</Badge>
                  </div>
                </div>
                {a.portal_url ? (
                  <a href={a.portal_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="shrink-0">
                    <Button size="sm" variant="outline">Open official portal ↗</Button>
                  </a>
                ) : null}
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* detail drawer */}
      <Modal open={!!detail} onClose={() => { setDetail(null); setSelected(null); }} title={detail?.name || ""} wide>
        {!detail ? <Spinner /> : (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <StatusBadge value={detail.applicability} />
              <StatusBadge value={detail.node_state} />
              <SourceBadge status={detail.source_status} />
              <Badge tone={confidenceLabel(detail.confidence).tone}>{confidenceLabel(detail.confidence).label}</Badge>
            </div>

            {sel?.user_dismissed ? <Disclaimer tone="amber">You dismissed this approval. Restore it from the actions below if that was a mistake.</Disclaimer> : null}

            <section>
              <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Why this may apply</h4>
              <p className="text-[13.5px] leading-relaxed text-slate-300">{detail.why}</p>
              {detail.matched_facts?.length ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {detail.matched_facts.map((f: any, i: number) => (
                    <Badge key={i} tone="blue" title={`rule input: ${f.field}`}>{f.label}: {String(f.value).slice(0, 30)}</Badge>
                  ))}
                </div>
              ) : null}
            </section>

            <section className="rounded-xl border border-white/8 bg-white/4 p-3.5">
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Authority & process</h4>
              <ProvenanceRow label="Authority" value={detail.authority} />
              <ProvenanceRow label="Jurisdiction" value={detail.jurisdiction?.replace(/_/g, " ")} />
              {detail.catalogue?.process_summary ? <ProvenanceRow label="Process" value={detail.catalogue.process_summary} /> : null}
              {detail.estimated_timeline_days ? <ProvenanceRow label="Typical duration (info)" value={`${detail.estimated_timeline_days} days — verify on portal`} /> : null}
              {detail.catalogue?.fee_information ? <ProvenanceRow label="Fees" value={detail.catalogue.fee_information} /> : null}
              {detail.catalogue?.validity_text ? <ProvenanceRow label="Validity" value={detail.catalogue.validity_text} /> : null}
            </section>

            {detail.legal_basis?.length ? (
              <section>
                <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Legal basis</h4>
                <div className="flex flex-wrap gap-1.5">{detail.legal_basis.map((l: string) => <Badge key={l} tone="green">{l}</Badge>)}</div>
              </section>
            ) : null}

            <section>
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Document checklist</h4>
              <div className="space-y-1.5">
                {detail.requirements.map((r: any) => (
                  <label key={r.id} className="flex items-center gap-3 rounded-lg border border-white/8 bg-white/4 px-3 py-2 text-[13px]">
                    <input type="checkbox" checked={r.satisfied} onChange={() => act("requirement", { requirement_id: r.id, satisfied: !r.satisfied })} className="h-4 w-4 accent-brand-500" />
                    <span className={r.satisfied ? "text-slate-500 line-through" : "text-slate-200"}>{r.title}</span>
                  </label>
                ))}
              </div>
            </section>

            {detail.missing_information?.length ? (
              <Disclaimer tone="amber">
                More information would firm this up: {detail.missing_information.map((m: any) => m.label).join(", ")}.
              </Disclaimer>
            ) : null}

            <Disclaimer tone="violet">{detail.verification_note || "Confirm the current form, fee, threshold and delegated authority on the official portal before relying on this entry."}</Disclaimer>

            <div className="flex flex-wrap gap-2 border-t border-white/10 pt-3">
              {detail.portal_url ? <a href={detail.portal_url} target="_blank" rel="noopener noreferrer"><Button size="sm">Open official portal ↗</Button></a> : null}
              <Button size="sm" variant="outline" onClick={() => navigateToApplication(detail.template_code)}>Prepare application</Button>
              {!sel?.user_dismissed ? (
                <Button size="sm" variant="ghost" onClick={() => act("dismiss")}>Dismiss (not relevant)</Button>
              ) : (
                <Button size="sm" variant="ghost" onClick={() => act("restore")}>Restore</Button>
              )}
              {detail.user_notes || true ? (
                <Button size="sm" variant="ghost" onClick={() => { const note = prompt("Notes for this approval:", detail.user_notes || ""); if (note !== null) act("note", { note }); }}>Notes</Button>
              ) : null}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );

  function navigateToApplication(code: string) {
    window.location.hash = `/projects/${projectId}/applications?new=${code}`;
  }
}
