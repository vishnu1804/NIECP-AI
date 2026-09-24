/** Government data enrichment (integration upgrade §3–§5, §7):
 *  UDYAM/MSME dataset search (data.gov.in; DEMO-labelled until provisioned),
 *  user-selected match → project reference + digital-twin enrichment,
 *  PIN code → state/district validation, and the consent ledger. */
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import { Badge, Button, Card, CardHeader, Disclaimer, Field, Input, Spinner } from "./ui";

const VERIFICATION_TONE: Record<string, any> = {
  GOVERNMENT_DATASET_MATCH: "blue",
  DEMO: "amber",
  NOT_VERIFIED: "slate",
  REQUIRES_VERIFICATION: "amber",
  MCA_DATA_MATCH: "blue",
};

export default function GovDataEnrichment({ onChanged }: { onChanged?: () => void }) {
  const { projectId } = useParams();
  const [refs, setRefs] = useState<any[]>([]);
  const [consents, setConsents] = useState<any[]>([]);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<any>(null);
  const [picked, setPicked] = useState<any>(null);
  const [confirm, setConfirm] = useState(false);
  const [pin, setPin] = useState("");
  const [pinResult, setPinResult] = useState<any>(null);
  const [applyPin, setApplyPin] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  // MCA public dataset search (Company Master Data — NOT a live verification)
  const [mcaQuery, setMcaQuery] = useState("");
  const [mcaResult, setMcaResult] = useState<any>(null);
  const [mcaBusy, setMcaBusy] = useState(false);
  // Environment & industry context (§5–§7, §20)
  const [envCity, setEnvCity] = useState("");
  const [envResult, setEnvResult] = useState<Record<string, any>>({});
  const [envBusy, setEnvBusy] = useState<string | null>(null);
  const [twin, setTwin] = useState<any>(null);

  const load = async () => {
    api<any>(`/projects/${projectId}/gov-references`).then((r) => setRefs(r.references || [])).catch(() => {});
    api<any>(`/gov/consent?project_id=${projectId}`).then((r) => setConsents(r.consents || [])).catch(() => {});
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [projectId]);

  const search = async () => {
    setSearching(true); setResults(null); setPicked(null); setMsg(null);
    try {
      const r = await api<any>(`/gov/udyaam/search`, "POST", { query, state_code: null, project_id: Number(projectId) });
      setResults(r);
    } catch (e: any) { setMsg(e?.message || "Search failed."); }
    setSearching(false);
  };

  const selectRecord = async () => {
    if (!picked || !confirm) return;
    try {
      const r = await api<any>(`/gov/udyaam/select`, "POST", { project_id: Number(projectId), record: picked, confirmation: true });
      setMsg(r.reference?.verification_label || "Reference stored.");
      setResults(null); setPicked(null); setConfirm(false);
      await load();
      onChanged?.();
    } catch (e: any) { setMsg(e?.message || "Could not store the reference."); }
  };

  const lookupPin = async (apply: boolean) => {
    setMsg(null);
    try {
      const r = await api<any>(`/gov/pincode-lookup`, "POST", { pincode: pin, project_id: Number(projectId), apply_to_profile: apply });
      setPinResult(r);
      if (apply) { onChanged?.(); }
    } catch (e: any) { setMsg(e?.message || "Lookup failed."); }
  };

  const revoke = async (id: number) => {
    try { await api(`/gov/consent/${id}/revoke`, "POST", {}); await load(); } catch { /* noop */ }
  };

  const mcaSearch = async () => {
    setMcaBusy(true); setMcaResult(null);
    try {
      const r = await api<any>("/gov/mca/search", "POST", { query: mcaQuery, project_id: Number(projectId) });
      setMcaResult(r);
    } catch (e: any) { setMsg(e?.message || "MCA dataset search failed."); }
    setMcaBusy(false);
  };

  const envLookup = async (kind: "air" | "water" | "asi", save: boolean) => {
    setEnvBusy(kind + String(save)); setMsg(null);
    try {
      const body: any = { project_id: Number(projectId), save_to_project: save };
      if (kind === "air") { body.city = envCity || undefined; }
      if (kind === "water") { body.location = envCity || undefined; }
      if (kind === "asi") { body.industry = envCity || undefined; }
      const path = kind === "air" ? "/gov/cpcb/air-quality" : kind === "water" ? "/gov/cpcb/surface-water" : "/gov/asi/industry-stats";
      const r = await api<any>(path, "POST", body);
      setEnvResult((t) => ({ ...t, [kind]: r }));
      if (save) { onChanged?.(); loadTwin(); }
    } catch (e: any) { setMsg(e?.message || "Lookup failed."); }
    setEnvBusy(null);
  };

  const loadTwin = async () => {
    try { setTwin(await api<any>(`/projects/${projectId}/gov/enrichment`)); } catch { /* noop */ }
  };
  useEffect(() => { loadTwin(); /* eslint-disable-next-line */ }, [projectId]);

  const envCityPlaceholder = "City / location / industry to look up";
  return (
    <Card>
      <CardHeader
        title="Government data services"
        subtitle="Dataset matches you select enrich the regulatory digital twin. A dataset match is supporting information — not a verification and not a legal conclusion."
      />
      <div className="space-y-5 p-5">
        {msg ? <Disclaimer tone="blue">{msg}</Disclaimer> : null}

        {/* ── UDYAM dataset search ── */}
        <div>
          <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">UDYAM / MSME dataset search · Source: data.gov.in · Ministry of MSME</h4>
          <div className="flex gap-2">
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Your enterprise name or activity (e.g. electronics)" />
            <Button disabled={query.trim().length < 2 || searching} onClick={search}>{searching ? <Spinner /> : "Search dataset"}</Button>
          </div>
          {results ? (
            <div className="mt-3 space-y-2">
              {results.mode === "DEMO" ? (
                <Disclaimer tone="amber">🟡 {results.message}</Disclaimer>
              ) : (
                <Disclaimer tone="blue">Source: data.gov.in — GOVERNMENT_DATASET_MATCH. Select your organization to store the reference.</Disclaimer>
              )}
              {(results.data?.records || []).map((rec: any, i: number) => (
                <button key={i} onClick={() => { setPicked(rec); setConfirm(false); }}
                  className={`block w-full rounded-xl border px-3.5 py-2.5 text-left transition-colors ${picked === rec ? "border-brand-400/60 bg-brand-500/10" : "border-white/10 bg-white/4 hover:border-brand-400/30"}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[13px] font-medium text-slate-100">{rec.enterprise_name}</span>
                    {results.mode === "DEMO" ? <Badge tone="amber">DEMO</Badge> : <Badge tone="blue">DATASET MATCH</Badge>}
                  </div>
                  <div className="mt-0.5 text-[11.5px] text-slate-500">
                    {rec.state} · {rec.district} · {rec.nic_activity}{rec.registration_date ? ` · registered ${rec.registration_date}` : ""}
                    {rec.udyam_reference ? <> · <span className="font-mono">{rec.udyam_reference}</span></> : null}
                  </div>
                </button>
              ))}
              {(results.data?.records || []).length === 0 ? <p className="text-[12px] text-slate-500">No matching records.</p> : null}
              {picked ? (
                <div className="rounded-xl border border-brand-400/25 bg-brand-500/8 p-3">
                  <p className="text-[12.5px] text-slate-200">Selected: <span className="font-semibold">{picked.enterprise_name}</span></p>
                  <label className="mt-2 flex items-start gap-2 text-[11.5px] text-slate-400">
                    <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} className="mt-0.5 h-3.5 w-3.5 accent-brand-500" />
                    I confirm this record belongs to my organization and NIECP-AI may store it as a reference and use the state/district/activity as supporting inputs to the regulatory analysis.
                  </label>
                  <Button size="sm" className="mt-2" disabled={!confirm} onClick={selectRecord}>Store reference & enrich profile</Button>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        {/* ── PIN code validation ── */}
        <div className="border-t border-white/10 pt-4">
          <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Location validation · Source: India Post (data.gov.in)</h4>
          <div className="flex flex-wrap gap-2">
            <Input value={pin} onChange={(e) => setPin(e.target.value)} placeholder="6-digit PIN code" className="max-w-44" inputMode="numeric" maxLength={6} />
            <Button variant="outline" disabled={pin.length !== 6} onClick={() => lookupPin(false)}>Validate</Button>
            {pinResult?.ok ? (
              <Button variant="ghost" disabled={pin.length !== 6} onClick={() => lookupPin(true)}>Apply to profile</Button>
            ) : null}
          </div>
          {pinResult ? (
            pinResult.ok ? (
              <div className="mt-2 rounded-xl border border-white/10 bg-white/4 p-3 text-[12.5px] text-slate-300">
                <div className="flex items-center gap-2">
                  <Badge tone={VERIFICATION_TONE[pinResult.verification_status] || "slate"}>{pinResult.verification_status?.replace(/_/g, " ")}</Badge>
                  <span>{pinResult.data.postal_circle} · mode: {pinResult.mode}</span>
                </div>
                {pinResult.data.district ? <p className="mt-1">District: {pinResult.data.district}</p> : <p className="mt-1 text-slate-500">District is not part of the offline index — enter it in the profile fields above (never guessed).</p>}
                <p className="mt-1 text-[11px] text-slate-500">{pinResult.message}</p>
              </div>
            ) : (
              <p className="mt-2 text-[12px] text-amber-300/80">{pinResult.message}</p>
            )
          ) : null}
        </div>

        {/* ── stored references ── */}
        {refs.length ? (
          <div className="border-t border-white/10 pt-4">
            <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Stored government references ({refs.length})</h4>
            <div className="space-y-1.5">
              {refs.map((r) => (
                <div key={r.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/8 bg-white/4 px-3 py-2 text-[12px]">
                  <div className="min-w-0">
                    <span className="font-medium text-slate-200">{r.display_name}</span>
                    <span className="ml-2 text-slate-500">{r.external_id}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {r.is_demo ? <Badge tone="amber">DEMO</Badge> : null}
                    <Badge tone={VERIFICATION_TONE[r.verification_status] || "slate"}>{r.verification_status?.replace(/_/g, " ")}</Badge>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {/* ── consent ledger ── */}
        {consents.length ? (
          <div className="border-t border-white/10 pt-4">
            <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Consent records</h4>
            <div className="space-y-1.5">
              {consents.map((c) => (
                <div key={c.consent_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/8 bg-white/4 px-3 py-2 text-[12px]">
                  <div className="min-w-0">
                    <span className="font-medium text-slate-200">{c.service}</span>
                    <span className="ml-2 text-slate-500">{c.purpose}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge tone={c.status === "GRANTED" ? "green" : c.status === "REVOKED" ? "red" : "slate"}>{c.status}</Badge>
                    {c.status === "GRANTED" ? <Button size="sm" variant="ghost" onClick={() => revoke(c.consent_id)}>Revoke</Button> : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {/* ── MCA Company Master Data (public dataset) ── */}
        <div>
          <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">MCA Company Master Data · Source: data.gov.in (public dataset — not a live MCA verification)</h4>
          <div className="flex gap-2">
            <Input value={mcaQuery} onChange={(e) => setMcaQuery(e.target.value)} placeholder="Company name as registered with the RoC" />
            <Button disabled={mcaQuery.trim().length < 2 || mcaBusy} onClick={mcaSearch}>{mcaBusy ? <Spinner /> : "Search MCA dataset"}</Button>
          </div>
          {mcaResult ? (
            <div className="mt-3 space-y-2">
              {mcaResult.ok ? (
                <>
                  <Disclaimer tone="blue">{mcaResult.data?.match_warning || "MCA Company Master Data — dataset match, not a live verification."}</Disclaimer>
                  {(mcaResult.data?.records || []).slice(0, 5).map((rec: any, i: number) => (
                    <div key={i} className="rounded-xl border border-white/8 bg-white/4 p-3 text-[12px] text-slate-300">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-slate-100">{rec.company_name || rec.name || "—"}</span>
                        <Badge tone="blue">DATASET</Badge>
                        {rec.company_status ? <Badge tone="slate">{String(rec.company_status)}</Badge> : null}
                      </div>
                      <p className="mt-1 text-[11px] text-slate-500">{[rec.cin, rec.roc, rec.company_category, rec.company_class, rec.registration_date].filter(Boolean).join(" · ") || "—"}</p>
                      <p className="mt-1 text-[10.5px] text-slate-600">Retrieved: {mcaResult.meta?.retrieved_at?.slice(0, 16).replace("T", " ") || "—"} · Source: {mcaResult.meta?.dataset}</p>
                    </div>
                  ))}
                </>
              ) : (
                <Disclaimer tone="amber">{mcaResult.message || "MCA Company Master Data is not provisioned in this deployment — record the CIN from the official MCA portal."}</Disclaimer>
              )}
            </div>
          ) : null}
        </div>

        {/* ── Environment & industry context (§5–§7, §20) ── */}
        <div>
          <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Environment &amp; industry context · CPCB air (live) · CPCB water (historical) · ASI statistics — CONTEXT ONLY, never an approval decision</h4>
          <div className="flex flex-wrap gap-2">
            <Input className="max-w-[240px]" value={envCity} onChange={(e) => setEnvCity(e.target.value)} placeholder={envCityPlaceholder} />
            <Button size="sm" variant="outline" disabled={envBusy !== null} onClick={() => envLookup("air", false)}>{envBusy === "airfalse" ? <Spinner /> : "Air quality (context)"}</Button>
            <Button size="sm" variant="outline" disabled={envBusy !== null} onClick={() => envLookup("water", false)}>{envBusy === "waterfalse" ? <Spinner /> : "Water quality (historical)"}</Button>
            <Button size="sm" variant="outline" disabled={envBusy !== null} onClick={() => envLookup("asi", false)}>{envBusy === "asifalse" ? <Spinner /> : "Industry statistics"}</Button>
          </div>
          {(["air", "water", "asi"] as const).map((kind) => envResult[kind] ? (
            <div key={kind} className="mt-2 rounded-xl border border-white/8 bg-white/4 p-3 text-[11.5px]">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={kind === "air" ? "blue" : kind === "water" ? "amber" : "slate"}>{envResult[kind].context_label?.replace(/_/g, " ")}</Badge>
                {envResult[kind].ok
                  ? <span className="text-slate-400">{envResult[kind].data?.count ?? 0} record(s) · {envResult[kind].meta?.dataset}</span>
                  : <span className="text-amber-300/80">{envResult[kind].message || "Not provisioned in this deployment"}</span>}
              </div>
              {envResult[kind].ok && (envResult[kind].data?.records || []).length ? (
                <div className="mt-2 space-y-1">
                  {envResult[kind].data.records.slice(0, 4).map((rec: any, i: number) => (
                    <p key={i} className="text-slate-400">{Object.entries(rec).slice(0, 6).map(([k, v]) => `${k}: ${String(v)}`).join(" · ")}</p>
                  ))}
                  {envResult[kind].meta?.last_updated ? <p className="text-[10.5px] text-slate-600">Dataset last updated: {String(envResult[kind].meta.last_updated)}</p> : null}
                </div>
              ) : null}
              {envResult[kind].ok ? (
                <Button size="sm" variant="ghost" disabled={envBusy !== null} onClick={() => envLookup(kind, true)}>
                  {envBusy === kind + "true" ? <Spinner /> : "Save to digital twin (with provenance)"}
                </Button>
              ) : null}
              <p className="mt-1 text-[10.5px] text-slate-600">{envResult[kind].usage_rule}</p>
            </div>
          ) : null)}
        </div>

        {/* ── Regulatory Digital Twin blocks (§14) ── */}
        {twin ? (
          <div>
            <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Regulatory digital twin — government enrichment with provenance</h4>
            <div className="grid gap-2 md:grid-cols-2">
              {Object.entries(twin.blocks || {}).map(([block, entries]: [string, any]) => (
                <div key={block} className="rounded-xl border border-white/8 bg-white/4 p-3">
                  <div className="text-[10.5px] font-bold uppercase tracking-[0.12em] text-slate-500">{block}</div>
                  {(entries as any[]).length === 0 ? <p className="mt-1 text-[11.5px] text-slate-600">No enriched values yet.</p> : (
                    <div className="mt-1 space-y-1">
                      {(entries as any[]).slice(0, 6).map((e, i) => (
                        <div key={i} className="flex flex-wrap items-center justify-between gap-2 text-[11.5px]">
                          <span className="text-slate-400">{e.label || block}</span>
                          <span className="flex items-center gap-1.5">
                            <span className="text-slate-200">{e.value === null || e.value === undefined || e.value === "" ? "—" : String(e.value).slice(0, 40)}</span>
                            <Badge tone={VERIFICATION_TONE[e.verification_state] || "slate"}>{String(e.verification_state || "").replace(/_/g, " ")}</Badge>
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
            <p className="mt-2 text-[10.5px] text-slate-600">{twin.disclaimer}</p>
          </div>
        ) : null}

        <Disclaimer tone="violet">
          NIECP-AI accesses government data only after your explicit consent, and marks provenance on everything it stores. Retrieved/selected data feeds the regulatory analysis as supporting input — the deterministic rule engine (not the dataset) decides applicability.
        </Disclaimer>
      </div>
    </Card>
  );
}
