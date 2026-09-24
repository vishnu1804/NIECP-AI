/** Government portal directory (spec §17) + Government Integration Registry
 * cards (Master Upgrade Prompt §23): NSWS, TN SWS, API Setu, NIECP Demo. */
import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Badge, Button, Card, Disclaimer, Input, Select, Spinner, StatusBadge } from "../components/ui";

const AUTH_TONE: Record<string, any> = { AUTHORIZED: "green", PENDING: "amber", NOT_AUTHORIZED: "slate", EXPIRED: "red" };

function RegistryCards() {
  const [reg, setReg] = useState<any>(null);
  useEffect(() => { api<any>("/integration-registry").then(setReg).catch(() => setReg({ registry: [] })); }, []);
  if (!reg) return null;
  return (
    <div className="space-y-3">
      <h2 className="text-[15px] font-bold text-white">Government integration registry</h2>
      <Disclaimer tone="violet">{reg.declaration}</Disclaimer>
      <div className="grid gap-3 md:grid-cols-2">
        {reg.registry.map((e: any) => (
          <Card key={e.provider_code} className={`p-4 ${e.is_demo ? "border-amber-400/25" : ""}`}>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  {e.is_demo ? <Badge tone="amber">🟡 DEMO</Badge> : null}
                  <h3 className="truncate text-[14px] font-semibold text-slate-100">{e.provider_name}</h3>
                </div>
                <div className="mt-0.5 text-[11.5px] text-slate-500">{e.service_name}</div>
              </div>
              <Badge tone={AUTH_TONE[e.authorization_status] || "slate"}>{e.authorization_status?.replace(/_/g, " ")}</Badge>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11.5px] text-slate-400">
              <span>Environment: <span className="text-slate-300">{e.environment}</span></span>
              <span>Live API: <span className={e.live ? "text-emerald-300" : "text-slate-300"}>{e.live ? "CONNECTED" : "NOT CONNECTED"}</span></span>
              <span>Jurisdiction: <span className="text-slate-300">{e.jurisdiction?.replace("STATE:", "") || "—"}</span></span>
              <span>Fallback: <span className="text-slate-300">{e.fallback_mode?.replace(/_/g, " ")}</span></span>
            </div>
            {e.supported_operations?.length ? (
              <p className="mt-2 text-[11px] text-slate-500">Capabilities: {e.supported_operations.join(", ")}</p>
            ) : (
              <p className="mt-2 text-[11px] text-slate-500">Supported API operations: none (authorization {e.authorization_status?.toLowerCase()})</p>
            )}
            <p className="mt-1 text-[11px] text-slate-600">{e.notes}</p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              {e.official_portal_url ? (
                <a href={e.official_portal_url} target="_blank" rel="noopener noreferrer">
                  <Button size="sm" variant="outline">Open official portal ↗</Button>
                </a>
              ) : null}
              {e.is_demo ? <Button size="sm" variant="ghost" onClick={() => (window.location.hash = "#/applications")} title="Start a demo application from your project's Applications page">Run demo →</Button> : null}
              <span className="text-[10.5px] text-slate-600">
                source: {e.source_type?.replace(/_/g, " ")}{e.last_verified_at ? ` · verified ${new Date(e.last_verified_at).toLocaleDateString()}` : " · not verified"}
              </span>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

export default function GovPortals() {
  const [data, setData] = useState<any>(null);
  const [q, setQ] = useState("");
  const [level, setLevel] = useState("");
  const [state, setState] = useState("");

  useEffect(() => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (level) p.set("level", level);
    if (state) p.set("state_code", state);
    api<any>(`/government-portals?${p}`).then(setData);
  }, [q, level, state]);

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div>
        <h1 className="text-xl font-bold text-white">Government portal directory</h1>
        <p className="text-[12.5px] text-slate-500">Official portals, with verification status and last-verified date. NIECP-AI opens them for you — it never impersonates them.</p>
      </div>

      <RegistryCards />

      <Disclaimer tone="blue">Links open the official government website in a new tab. NIECP-AI is not affiliated with these portals.</Disclaimer>

      <div className="flex flex-wrap gap-3">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search portals, departments, services…" className="max-w-sm" />
        <Select value={level} onChange={(e) => setLevel(e.target.value)} className="max-w-40">
          <option value="">All levels</option>
          <option value="CENTRAL">Central</option>
          <option value="STATE">State</option>
        </Select>
        <Select value={state} onChange={(e) => setState(e.target.value)} className="max-w-44">
          <option value="">All states</option>
          {(data?.states || []).map((s: any) => <option key={s.code} value={s.code}>{s.name}</option>)}
        </Select>
      </div>

      {!data ? <Spinner /> : (
        <div className="grid gap-3 md:grid-cols-2">
          {data.portals.map((p: any) => (
            <Card key={p.id} className="p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    {p.is_demo ? <Badge tone="violet">DEMO</Badge> : null}
                    <h3 className="truncate text-[14px] font-semibold text-slate-100">{p.name}</h3>
                  </div>
                  <div className="mt-0.5 text-[11.5px] text-slate-500">{p.department}{p.ministry ? ` · ${p.ministry}` : ""}</div>
                </div>
                <Badge tone={p.level === "CENTRAL" ? "blue" : "violet"}>{p.state_code || p.level}</Badge>
              </div>
              {p.description ? <p className="mt-1.5 line-clamp-2 text-[12.5px] leading-relaxed text-slate-400">{p.description}</p> : null}
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <StatusBadge value={p.verification_status} />
                <Badge tone={p.integration_status === "CONNECTED" ? "green" : "slate"}>
                  integration: {p.integration_status?.replace(/_/g, " ").toLowerCase()}
                </Badge>
                {p.last_verified_at ? <Badge tone="slate">verified {new Date(p.last_verified_at).toLocaleDateString()}</Badge> : null}
              </div>
              <a href={p.official_url} target="_blank" rel="noopener noreferrer" className="mt-3 inline-block text-xs font-medium text-brand-300 hover:underline">
                {p.official_url.replace(/^https?:\/\//, "")} ↗
              </a>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
