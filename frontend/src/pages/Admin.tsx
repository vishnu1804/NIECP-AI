/** Admin panel (spec §42, §43, §18): overview, users, integrations health,
 * audit log, AI usage, demo data purge. */
import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { Badge, Button, Card, CardHeader, Disclaimer, Spinner, StatusBadge, Tabs } from "../components/ui";

export default function Admin() {
  const { user } = useApp();
  const [tab, setTab] = useState("overview");
  const [overview, setOverview] = useState<any>(null);
  const [users, setUsers] = useState<any[]>([]);
  const [audit, setAudit] = useState<any[]>([]);
  const [integrations, setIntegrations] = useState<any[]>([]);
  const [aiUsage, setAiUsage] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const [ov, us, au, ig, ai] = await Promise.all([
      api<any>("/admin/overview"),
      api<any>("/admin/users"),
      api<any>("/admin/audit?limit=60"),
      api<any>("/integrations"),
      api<any>("/admin/ai-usage"),
    ]);
    setOverview(ov); setUsers(us.users); setAudit(au.events); setIntegrations(ig.integrations); setAiUsage(ai);
  };
  useEffect(() => { load(); }, []);

  if (!user || !["SYSTEM_ADMIN", "ORGANIZATION_ADMIN"].includes(user.platform_role)) {
    return <Disclaimer tone="amber">Admin access required.</Disclaimer>;
  }
  if (!overview) return <div className="flex justify-center py-20"><Spinner className="h-6 w-6" /></div>;

  const runHealth = async (code: string) => {
    setBusy(true);
    try { await api(`/integrations/${code}/health-check`, "POST", {}); await load(); } finally { setBusy(false); }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white">Admin panel</h1>
        <Badge tone="violet">{user.platform_role.replace(/_/g, " ")}</Badge>
      </div>

      <Tabs
        tabs={[{ key: "overview", label: "Overview" }, { key: "users", label: "Users" }, { key: "integrations", label: "Integrations & API health" }, { key: "audit", label: "Audit log" }, { key: "ai", label: "AI usage" }]}
        active={tab}
        onChange={setTab}
      />

      {tab === "overview" ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {Object.entries(overview.counts).map(([k, v]) => (
              <Card key={k} className="p-4">
                <div className="text-[11px] uppercase tracking-wide text-slate-500">{k.replace(/_/g, " ")}</div>
                <div className="mt-1 text-2xl font-bold text-white">{String(v)}</div>
              </Card>
            ))}
          </div>
          <Card>
            <CardHeader title="Knowledge corpus (RAG)" />
            <div className="flex flex-wrap gap-3 p-5">
              {Object.entries(overview.knowledge_corpus).map(([k, v]) => <Badge key={k} tone="blue">{k.replace(/_/g, " ")}: {String(v)}</Badge>)}
            </div>
          </Card>
          {overview.production_blockers?.length ? (
            <Disclaimer tone="amber"><span className="font-semibold">Production readiness blockers:</span> {overview.production_blockers.join(" · ")}</Disclaimer>
          ) : <Disclaimer tone="green">No production-readiness blockers detected in configuration.</Disclaimer>}
          <Card>
            <CardHeader title="Demo data" subtitle="Demo content is always labelled and can be removed without touching real data." />
            <div className="p-5">
              <Button variant="danger" size="sm" onClick={async () => {
                if (!confirm("Delete ALL demo-labelled data? Real user data is untouched.")) return;
                const r = await api<any>("/admin/demo-data", "DELETE");
                alert(`Removed ${r.removed} demo records.`);
                await load();
              }}>Purge all demo data</Button>
            </div>
          </Card>
        </div>
      ) : null}

      {tab === "users" ? (
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-[12.5px]">
            <thead className="border-b border-white/10 text-[10.5px] uppercase tracking-wider text-slate-500">
              <tr><th className="px-4 py-3">User</th><th className="px-4 py-3">Role</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Last login</th><th className="px-4 py-3">Actions</th></tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-white/6">
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-slate-200">{u.full_name} {u.is_demo ? <Badge tone="violet">DEMO</Badge> : null}</div>
                    <div className="text-[11px] text-slate-500">{u.email}</div>
                  </td>
                  <td className="px-4 py-2.5"><Badge tone="slate">{u.platform_role.replace(/_/g, " ")}</Badge></td>
                  <td className="px-4 py-2.5"><StatusBadge value={u.status} /></td>
                  <td className="px-4 py-2.5 text-slate-500">{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "never"}</td>
                  <td className="px-4 py-2.5">
                    {user.platform_role === "SYSTEM_ADMIN" ? (
                      <select className="rounded-lg border border-white/12 bg-ink-900 px-2 py-1 text-[11px]"
                        value={u.status}
                        onChange={async (e) => { await api(`/admin/users/${u.id}`, "PATCH", { status: e.target.value }); await load(); }}>
                        {["PENDING_VERIFICATION", "ACTIVE", "SUSPENDED", "DELETED"].map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
                      </select>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ) : null}

      {tab === "integrations" ? (
        <div className="space-y-3">
          <Disclaimer tone="amber">
            Never convert API failure into fake success: CONNECTED requires real credentials AND a successful authenticated call. Without provider approval, integrations stay in MANUAL_MODE with the official portal link.
          </Disclaimer>
          {integrations.map((i) => (
            <Card key={i.code} className="p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="text-[14px] font-semibold text-slate-100">{i.name}</h3>
                    <StatusBadge value={i.status} />
                  </div>
                  <div className="mt-0.5 text-[11.5px] text-slate-500">{i.provider}</div>
                  {i.notice ? <p className="mt-1.5 text-[12px] text-amber-300/80">{i.notice}</p> : null}
                  <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500">
                    <span>creds: {i.credentials_configured ? "configured (server-side only)" : "not configured"}</span>
                    {i.health?.last_http_status ? <span>· last HTTP {i.health.last_http_status}</span> : null}
                    {i.health?.last_error_message ? <span className="text-rose-300/80">· {i.health.last_error_message.slice(0, 80)}</span> : null}
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => runHealth(i.code)}>Health check</Button>
                  {i.official_portal_url ? <a href={i.official_portal_url} target="_blank" rel="noopener noreferrer"><Button size="sm" variant="ghost">Portal ↗</Button></a> : null}
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : null}

      {tab === "audit" ? (
        <Card className="max-h-[70vh] overflow-y-auto">
          <table className="w-full text-left text-[11.5px]">
            <thead className="sticky top-0 border-b border-white/10 bg-ink-850 text-[10px] uppercase tracking-wider text-slate-500">
              <tr><th className="px-3 py-2.5">When</th><th className="px-3 py-2.5">User</th><th className="px-3 py-2.5">Action</th><th className="px-3 py-2.5">Resource</th><th className="px-3 py-2.5">Result</th><th className="px-3 py-2.5">Agent</th></tr>
            </thead>
            <tbody>
              {audit.map((a) => (
                <tr key={a.id} className="border-b border-white/5">
                  <td className="whitespace-nowrap px-3 py-2 text-slate-500">{new Date(a.created_at).toLocaleString()}</td>
                  <td className="px-3 py-2 text-slate-300">{a.user_email || "—"}</td>
                  <td className="px-3 py-2">
                    <span className="font-mono text-slate-200">{a.action}</span>
                    {a.is_security_event ? <Badge tone="red" className="ml-1.5">security</Badge> : null}
                  </td>
                  <td className="px-3 py-2 text-slate-500">{a.resource_type}{a.resource_id ? `#${a.resource_id}` : ""}</td>
                  <td className="px-3 py-2"><StatusBadge value={a.result} /></td>
                  <td className="px-3 py-2 text-slate-500">{a.agent?.replace(/_/g, " ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ) : null}

      {tab === "ai" ? (
        <div className="space-y-4">
          <Card>
            <CardHeader title="LLM configuration" />
            <div className="p-5 text-[13px] text-slate-300">
              <p className="leading-relaxed text-slate-400">{aiUsage?.llm_status?.note}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge tone={aiUsage?.llm_status?.configured ? "green" : "slate"}>provider: {aiUsage?.llm_status?.provider}</Badge>
                {aiUsage?.llm_status?.model ? <Badge tone="slate">model: {aiUsage.llm_status.model}</Badge> : null}
                <Badge tone="slate">external phrasing used: {aiUsage?.external_llm_used ?? 0}/{aiUsage?.assistant_messages ?? 0}</Badge>
              </div>
            </div>
          </Card>
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader title="By agent" />
              <div className="flex flex-wrap gap-2 p-5">
                {Object.entries(aiUsage?.by_agent || {}).map(([k, v]) => <Badge key={k} tone="violet">{k.replace(/_/g, " ")}: {String(v)}</Badge>)}
              </div>
            </Card>
            <Card>
              <CardHeader title="By intent" />
              <div className="flex flex-wrap gap-2 p-5">
                {Object.entries(aiUsage?.by_intent || {}).map(([k, v]) => <Badge key={k} tone="blue">{k.replace(/_/g, " ")}: {String(v)}</Badge>)}
              </div>
            </Card>
          </div>
        </div>
      ) : null}
    </div>
  );
}
