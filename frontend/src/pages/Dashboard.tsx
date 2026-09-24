/** Dashboard (spec §31): readiness, next-best-action, counters, recent
 * activity — all live from the API. */
import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { Badge, Button, Card, CardHeader, Disclaimer, EmptyState, Progress, Spinner, StatusBadge } from "../components/ui";

const PRIORITY_ICON: Record<string, string> = { QUERY: "💬", RENEWAL: "🔁", DOCUMENT_EXPIRED: "⏰", VALIDATION: "🔎", PROFILE: "🧩", BLOCKED: "⛔", DOCUMENT: "📄", APPLY: "🚀", ANALYSIS: "⚡", TASK: "✔️" };

export default function Dashboard() {
  const { activeProject, setActiveProjectId, projects, user } = useApp();
  const navigate = useNavigate();
  const [project, setProject] = useState<any>(null);
  const [readiness, setReadiness] = useState<any>(null);
  const [actions, setActions] = useState<any[]>([]);
  const [apps, setApps] = useState<any[]>([]);
  const [notifications, setNotifications] = useState<any[]>([]);
  const [cc, setCC] = useState<any>(null);
  const [msmeSum, setMsmeSum] = useState<any>(null);
  const [bn, setBn] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        if (!activeProject) {
          setProject(null);
          return;
        }
        const [p, rd, na, ap, nf, ccd, msd, bnd] = await Promise.all([
          api<any>(`/projects/${activeProject.id}`),
          api<any>(`/projects/${activeProject.id}/readiness`),
          api<any>(`/projects/${activeProject.id}/next-actions`),
          api<any>(`/projects/${activeProject.id}/applications`).catch(() => ({ applications: [] })),
          api<any>("/notifications?limit=6").catch(() => ({ notifications: [] })),
          api<any>(`/projects/${activeProject.id}/command-center`).catch(() => null),
          api<any>(`/projects/${activeProject.id}/msme/intelligence`).catch(() => null),
          api<any>(`/projects/${activeProject.id}/bottlenecks`).catch(() => null),
        ]);
        if (cancelled) return;
        setProject(p);
        setReadiness(rd);
        setActions(na.actions || []);
        setApps((ap.applications || []).slice(0, 5));
        setNotifications((nf.notifications || []).slice(0, 5));
        setCC(ccd);
        setMsmeSum(msd);
        setBn(bnd);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [activeProject?.id, activeProject?.readiness_overall]);

  if (!user) return null;

  if (projects.length === 0) {
    return (
      <EmptyState
        icon="🏗️"
        title="Create your first project"
        hint="Tell NIECP-AI what you want to build — the guided onboarding takes about 3 minutes and adapts its questions to your industry."
        action={<Button size="lg" onClick={() => navigate("/projects?new=1")}>Start a project →</Button>}
      />
    );
  }

  if (loading && !project) return <div className="flex justify-center py-20"><Spinner className="h-6 w-6" /></div>;

  const c = project?.counts || {};
  const comp = readiness?.components || [];
  const compOf = (key: string) => comp.find((x: any) => x.key === key);

  return (
    <div className="space-y-5">
      {/* header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-white">
            {project?.is_demo ? <Badge tone="violet" className="mr-2">DEMO</Badge> : null}
            {project?.name}
          </h1>
          <p className="mt-0.5 text-[12.5px] text-slate-500">
            {project?.industry || "industry not set"} · {project?.state || "state not set"} · <StatusBadge value={project?.stage} />
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => navigate(`/projects/${activeProject!.id}/analysis`)}>⚡ {comp ? "Readiness" : "Analyse"}</Button>
          <Button size="sm" onClick={() => navigate(`/projects/${activeProject!.id}/approvals`)}>Open approvals</Button>
        </div>
      </div>

      {project && !project.last_ai_analysis_at ? (
        <Disclaimer tone="blue">
          The AI analysis has not run yet for this project. Run it to generate the approval map, document checklist and readiness score.{" "}
          <button className="font-semibold text-brand-300 hover:underline" onClick={() => navigate(`/projects/${project.id}/analysis`)}>Run analysis →</button>
        </Disclaimer>
      ) : null}

      {/* command center strip (integration upgrade §20) */}
      {cc ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {[
            { label: "PROJECT READINESS", value: `${cc.readiness?.overall ?? "—"}%`, tone: "text-teal-300" },
            { label: "APPROVALS IDENTIFIED", value: cc.approvals_identified ?? 0, tone: "text-white" },
            { label: "DOCUMENTS READY", value: cc.documents_ready ?? "0/0", tone: "text-white" },
            { label: "CRITICAL BLOCKERS", value: cc.critical_blockers ?? 0, tone: (cc.critical_blockers ?? 0) > 0 ? "text-rose-300" : "text-emerald-300" },
            { label: "INTEGRATIONS", value: `${cc.integrations?.active ?? 0} active · ${cc.integrations?.pending ?? 0} pending`, tone: "text-white", small: true },
            { label: "APPLICATIONS", value: `${cc.applications?.open ?? 0} open · ${cc.applications?.approved ?? 0} approved`, tone: "text-white", small: true },
          ].map((k) => (
            <Card key={k.label} className="p-3.5">
              <div className="text-[9.5px] font-bold uppercase tracking-[0.12em] text-slate-500">{k.label}</div>
              <div className={`mt-1 ${k.small ? "text-[13px]" : "text-xl"} font-bold ${k.tone}`}>{k.value}</div>
            </Card>
          ))}
        </div>
      ) : null}
      {cc?.critical_blockers ? (
        <Disclaimer tone="amber">
          Critical blockers: {cc.blocker_titles?.join(" · ")}. {actions[0] ? `Next best action: ${actions[0].title}.` : ""}
        </Disclaimer>
      ) : null}

      {/* Operations intelligence — bottlenecks (MVP §R/§V screen 5, project view) */}
      {bn?.bottlenecks?.length ? (
        <Card className="p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="text-lg">🚧</span>
              <div>
                <div className="text-[13.5px] font-semibold text-white">Bottlenecks</div>
                <div className="text-[11.5px] text-slate-500">Causal analysis from approval states, dependencies, queries, SLA and missing documents — no AI risk score.</div>
              </div>
            </div>
            <Badge tone={bn.summary?.high ? "red" : "slate"}>{bn.summary?.high ?? 0} high severity</Badge>
          </div>
          <div className="mt-3 space-y-2">
            {bn.bottlenecks.slice(0, 3).map((b: any, i: number) => (
              <div key={i} className="rounded-xl border border-white/8 bg-white/4 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13px] font-semibold text-slate-100">{b.bottleneck}</span>
                  <Badge tone={b.severity === "HIGH" ? "red" : b.severity === "MEDIUM" ? "amber" : "slate"}>{b.severity}</Badge>
                  <span className="text-[11px] text-slate-500">{b.authority}</span>
                </div>
                <p className="mt-1 text-[11.5px] text-slate-400">{b.causes.join(" · ")}</p>
                <p className="text-[11.5px] text-amber-300/80">Downstream impact: {b.downstream_impact.length ? b.downstream_impact.join(", ") : "none"} — {b.project_impact}</p>
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {/* MSME Regulatory Intelligence (MSME upgrade §15) */}
      {msmeSum ? (
        <Card className="p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="text-lg">📊</span>
              <div>
                <div className="text-[13.5px] font-semibold text-white">MSME Regulatory Intelligence</div>
                <div className="text-[11.5px] text-slate-500">From business profile → regulatory intelligence → applicable requirements → dependencies → documents → smart action → official government channel.</div>
              </div>
            </div>
            <Button size="sm" variant="outline" onClick={() => navigate(`/projects/${activeProject!.id}/msme`)}>Open MSME Intelligence →</Button>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2.5 md:grid-cols-4 xl:grid-cols-8">
            {[
              { label: "MSME STATUS", value: msmeSum.business_classification?.potential_class || "INFO REQ.", tone: "text-teal-300" },
              { label: "SECTIONS SHOWN", value: msmeSum.applicable_msme_provisions?.length ?? 0, tone: "text-white" },
              { label: "COMPLIANCE ALERTS", value: msmeSum.compliance_risks?.length ?? 0, tone: (msmeSum.compliance_risks?.length ?? 0) > 0 ? "text-amber-300" : "text-emerald-300" },
              { label: "PAYMENT PROTECTION", value: "§§15-18", tone: "text-white" },
              { label: "GOVT SUPPORT", value: "§§10-12", tone: "text-white" },
              { label: "MAITRI SERVICES", value: msmeSum.maharashtra_approvals?.relevant ? (msmeSum.maharashtra_approvals.services?.length ?? 0) : "—", tone: "text-white" },
              { label: "APPROVAL DEPENDENCIES", value: msmeSum.smart_action_guide?.length ?? 0, tone: "text-white" },
              { label: "SMART ACTIONS", value: msmeSum.smart_action_guide?.length ?? 0, tone: "text-white" },
            ].map((k) => (
              <Card key={k.label} className="p-3" onClick={() => navigate(`/projects/${activeProject!.id}/msme`)}>
                <div className="text-[9px] font-bold uppercase tracking-[0.12em] text-slate-500">{k.label}</div>
                <div className={`mt-1 text-[15px] font-bold ${k.tone}`}>{k.value}</div>
              </Card>
            ))}
          </div>
          <p className="mt-2 text-[10.5px] text-slate-600">Authored MSMED Act digests — informational regulatory intelligence, not legal advice and not official verification. Verify at official sources.</p>
        </Card>
      ) : null}

      {/* counters */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        {[
          { label: "Approvals applying", value: c.approvals_applies ?? 0, to: `/projects/${activeProject!.id}/approvals`, icon: "🗂️" },
          { label: "Need info", value: c.approvals_conditional ?? 0, to: `/projects/${activeProject!.id}/approvals`, icon: "❔" },
          { label: "Documents", value: c.documents ?? 0, to: `/projects/${activeProject!.id}/documents`, icon: "📄" },
          { label: "Applications", value: c.applications ?? 0, to: `/projects/${activeProject!.id}/applications`, icon: "📮" },
          { label: "Open tasks", value: c.open_tasks ?? 0, to: `/projects/${activeProject!.id}/compliance`, icon: "✅" },
          { label: "Overall prep", value: `${readiness?.overall ?? "—"}%`, to: `/projects/${activeProject!.id}/analysis`, icon: "🎯" },
        ].map((k) => (
          <Card key={k.label} className="p-4" onClick={() => navigate(k.to)}>
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{k.label}</span>
              <span aria-hidden>{k.icon}</span>
            </div>
            <div className="mt-1 text-2xl font-bold text-white">{k.value}</div>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* next best actions */}
        <Card className="lg:col-span-2">
          <CardHeader
            title="Smart Action Guide"
            subtitle="Generated from your actual project state — queries, renewals, documents, blocked approvals."
          />
          <div className="space-y-2 p-4">
            {actions.length === 0 ? (
              <p className="px-1 py-4 text-[13px] text-slate-500">Nothing pending right now. Keep your profile current — new actions appear as your project state changes.</p>
            ) : (
              actions.map((a, i) => (
                <button
                  key={i}
                  onClick={() => a.link && navigate(a.link)}
                  className="flex w-full items-start gap-3 rounded-xl border border-white/8 bg-white/4 px-3.5 py-3 text-left transition-colors hover:border-brand-400/40"
                >
                  <span className="mt-0.5 text-lg" aria-hidden>{PRIORITY_ICON[a.type] || "•"}</span>
                  <div className="min-w-0 flex-1">
                    <div className="text-[13.5px] font-medium text-slate-100">{a.title}</div>
                    <div className="mt-0.5 text-[12px] leading-relaxed text-slate-500">{a.detail}</div>
                  </div>
                  <span className="mt-1 text-slate-600">›</span>
                </button>
              ))
            )}
          </div>
        </Card>

        {/* readiness */}
        <Card>
          <CardHeader title="Application readiness" subtitle="Preparation measure — not a probability of approval." />
          <div className="space-y-3.5 p-4">
            {compOf("profile") ? <Meter label="Profile" value={compOf("profile").score} />
            : <p className="text-[13px] text-slate-500">Run the analysis to compute readiness.</p>}
            {compOf("documents") ? <Meter label="Documents" value={compOf("documents").score} />
            : <p className="text-[13px] text-slate-500">Run the analysis to compute readiness.</p>}
            {compOf("prerequisites") ? <Meter label="Prerequisites" value={compOf("prerequisites").score} />
            : <p className="text-[13px] text-slate-500">Run the analysis to compute readiness.</p>}
            <div className="border-t border-white/8 pt-3">
              <div className="mb-1.5 flex items-baseline justify-between">
                <span className="text-[13px] font-semibold text-slate-200">Overall preparation</span>
                <span className="text-lg font-bold text-teal-glow">{readiness?.overall ?? "—"}%</span>
              </div>
              <Progress value={readiness?.overall ?? 0} />
            </div>
            <Link to={`/projects/${activeProject!.id}/analysis`} className="block text-center text-xs text-brand-300 hover:underline">How is this calculated? →</Link>
          </div>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* applications */}
        <Card>
          <CardHeader title="Recent applications" right={<Link to={`/projects/${activeProject!.id}/applications`} className="text-xs text-brand-300 hover:underline">View all</Link>} />
          <div className="p-4">
            {apps.length === 0 ? (
              <p className="text-[13px] text-slate-500">No applications yet. When an approval is ready, prepare one from its approval card.</p>
            ) : (
              <div className="space-y-2">
                {apps.map((a) => (
                  <div key={a.id} className="flex items-center justify-between rounded-xl border border-white/8 bg-white/4 px-3.5 py-2.5">
                    <div className="min-w-0">
                      <div className="truncate text-[13px] font-medium text-slate-200">
                        {a.is_demo ? <Badge tone="violet" className="mr-1.5">DEMO</Badge> : null}{a.title}
                      </div>
                      <div className="text-[11px] text-slate-500">{a.authority}</div>
                    </div>
                    <StatusBadge value={a.status} />
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>

        {/* notifications */}
        <Card>
          <CardHeader title="Recent activity" right={<Link to="/notifications" className="text-xs text-brand-300 hover:underline">All notifications</Link>} />
          <div className="p-4">
            {notifications.length === 0 ? (
              <p className="text-[13px] text-slate-500">No notifications yet.</p>
            ) : (
              <div className="space-y-2">
                {notifications.map((n) => (
                  <div key={n.id} className="rounded-xl border border-white/8 bg-white/4 px-3.5 py-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-[13px] font-medium text-slate-200">{n.title}</span>
                      <Badge tone={n.severity === "CRITICAL" ? "red" : n.severity === "WARNING" ? "amber" : "slate"}>{n.severity}</Badge>
                    </div>
                    {n.body ? <div className="mt-0.5 line-clamp-2 text-[11.5px] leading-relaxed text-slate-500">{n.body}</div> : null}
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

function Meter({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-[12.5px]">
        <span className="text-slate-300">{label}</span>
        <span className="font-semibold text-slate-100">{value}%</span>
      </div>
      <Progress value={value} tone={value >= 70 ? "green" : value >= 40 ? "brand" : "amber"} height="h-1.5" label={label} />
    </div>
  );
}
