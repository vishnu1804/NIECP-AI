/** Settings → Government Integrations (integration upgrade §21).
 *  One honest card per provider: authorization, environment, mode, last
 *  successful call, documentation, test connection and fallback. Credential
 *  state is shown as booleans only — values never leave the server. */
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { Badge, Button, Card, Disclaimer, Spinner } from "../components/ui";

const AUTH_TONE: Record<string, any> = { AUTHORIZED: "green", PENDING: "amber", PENDING_AUTHORIZATION: "amber", NOT_AUTHORIZED: "slate" };
const ENV_TONE: Record<string, any> = { LIVE: "green", DEMO: "amber", PENDING_AUTHORIZATION: "amber", OFFICIAL_REDIRECT: "blue", OFFLINE_INDEX: "slate" };
// Honest connection vocabulary (never a green CONNECTED without a real authorized success).
const CONN_TONE: Record<string, any> = {
  CONNECTED: "green",
  CONFIGURED: "blue",
  CONFIGURED_BUT_OUTBOUND_DISABLED: "amber",
  PENDING_AUTHORIZATION: "amber",
  OFFICIAL_REDIRECT: "blue",
  MANUAL: "slate",
  DEMO: "amber",
  FAILED: "red",
};

export default function Integrations() {
  const [data, setData] = useState<any>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, any>>({});

  const load = () => api<any>("/gov/services").then(setData).catch(() => setData({ services: [], summary: { declaration: "" } }));
  useEffect(() => { load(); }, []);

  const test = async (code: string) => {
    setTesting(code);
    try {
      const probe = code === "pincode" ? { pincode: "600001" } : code === "udyam_dataset" ? { query: "electronics" } : undefined;
      const r = await api<any>(`/gov/services/${code}/test`, "POST", probe ? { probe } : {});
      setTestResult((t) => ({ ...t, [code]: r }));
      load();
    } catch (e: any) {
      setTestResult((t) => ({ ...t, [code]: { ok: false, message: e?.message || "Test failed." } }));
    }
    setTesting(null);
  };

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Government integrations</h1>
          <p className="text-[12.5px] text-slate-500">
            <Link to="/settings" className="text-brand-300 hover:underline">← Settings</Link> · provider-agnostic status of every government service NIECP-AI can use.
          </p>
        </div>
      </div>

      {!data ? <Spinner /> : (
        <>
          <Disclaimer tone="violet">{data.summary?.declaration}</Disclaimer>
          <div className="space-y-3">
            {data.services.map((c: any) => (
              <Card key={c.code} className={`p-4 ${c.environment === "DEMO" ? "border-amber-400/25" : ""}`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      {c.environment === "DEMO" ? <Badge tone="amber">🟡 DEMO</Badge> : null}
                      <h3 className="text-[14px] font-semibold text-slate-100">{c.provider}</h3>
                    </div>
                    <p className="mt-0.5 text-[12px] text-slate-500">{c.service}</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={AUTH_TONE[c.authorization_status] || "slate"}>{c.authorization_status?.replace(/_/g, " ")}</Badge>
                    <Badge tone={ENV_TONE[c.environment] || "slate"}>env: {c.environment?.replace(/_/g, " ")}</Badge>
                    <Badge tone={CONN_TONE[c.connection_status] || "slate"}>{c.connection_status?.replace(/_/g, " ")}</Badge>
                    {c.last_call_failed ? <Badge tone="red">LAST CALL FAILED</Badge> : null}
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-[11.5px] text-slate-400 md:grid-cols-3">
                  <span>Mode: <span className="text-slate-300">{String(c.mode_label).replace(/_/g, " ")}</span></span>
                  <span>Auth: <span className="text-slate-300">{c.authentication_method}</span></span>
                  <span>Endpoint: <span className="text-slate-300">{c.endpoint_host || "—"}</span> · {c.http_method}</span>
                  <span>Timeout: <span className="text-slate-300">{c.timeout_seconds}s</span> · retries: {c.max_retries}</span>
                  <span>Fallback: <span className="text-slate-300">{String(c.fallback_mode).replace(/_/g, " ")}</span></span>
                  <span>Consent: <span className="text-slate-300">{c.consent_required ? "required" : "not required"}</span></span>
                  <span>Last successful call: <span className="text-slate-300">{c.last_successful_call?.at ? new Date(c.last_successful_call.at).toLocaleString() : "none yet"}</span></span>
                  <span>Last failed call: <span className="text-slate-300">{c.last_failed_call?.at ? `${new Date(c.last_failed_call.at).toLocaleString()}${c.last_failed_call.error_code ? ` · ${c.last_failed_call.error_code}` : ""}` : "none"}</span></span>
                  <span>Last verified: <span className="text-slate-300">{c.last_verified_at ? new Date(c.last_verified_at).toLocaleDateString() : "not verified"}</span></span>
                  <span>Operations: <span className="text-slate-300">{c.supported_operations?.length ? c.supported_operations.join(", ") : "none (authorization pending)"}</span></span>
                  <span className="md:col-span-3">Capabilities: <span className="text-slate-300">{c.data_categories?.length ? c.data_categories.join(" · ") : "—"}</span></span>
                </div>

                <div className="mt-2 flex flex-wrap gap-2 text-[10.5px]">
                  {Object.entries(c.credentials_configured || {}).map(([k, v]) => (
                    <span key={k} className={`rounded-full border px-2 py-0.5 ${(v as any) ? "border-emerald-400/30 text-emerald-300" : "border-white/12 text-slate-500"}`}>
                      {k}: {(v as any) ? "configured (server-side)" : "not provisioned"}
                    </span>
                  ))}
                </div>

                {c.connection_note && c.connection_status !== "CONNECTED" ? <p className="mt-2 text-[11.5px] text-amber-300/80">{c.connection_note}</p> : null}
                {c.notice ? <p className="mt-2 text-[11.5px] text-amber-300/80">{c.notice}</p> : null}
                {c.notes ? <p className="mt-1 text-[11px] text-slate-600">{c.notes}</p> : null}

                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <Button size="sm" variant="outline" disabled={testing === c.code} onClick={() => test(c.code)}>
                    {testing === c.code ? <Spinner /> : "Test connection"}
                  </Button>
                  {c.documentation_url ? (
                    <a href={c.documentation_url} target="_blank" rel="noopener noreferrer" className="text-[11.5px] text-brand-300 hover:underline">Official documentation ↗</a>
                  ) : null}
                  {c.official_portal_url ? (
                    <a href={c.official_portal_url} target="_blank" rel="noopener noreferrer" className="text-[11.5px] text-brand-300 hover:underline">Official portal ↗</a>
                  ) : null}
                </div>

                {testResult[c.code] ? (
                  <div className={`mt-2 rounded-lg border p-2.5 text-[11.5px] ${testResult[c.code].ok ? "border-emerald-400/25 bg-emerald-400/8 text-emerald-100" : "border-amber-400/25 bg-amber-400/8 text-amber-100"}`}>
                    <span className="font-semibold">{testResult[c.code].ok ? "Reachable — " : "Not connected — "}</span>
                    {testResult[c.code].message || (testResult[c.code].ok ? `mode ${testResult[c.code].mode}, verification ${testResult[c.code].verification_status}` : "")}
                    {testResult[c.code].fallback?.official_portal_url ? (
                      <> · <a href={testResult[c.code].fallback.official_portal_url} target="_blank" rel="noopener noreferrer" className="underline">official portal ↗</a></>
                    ) : null}
                  </div>
                ) : null}
              </Card>
            ))}
          </div>
          <Disclaimer tone="blue">
            A service shows CONNECTED only after a real successful authenticated response from the provider. Until then NIECP-AI offers OFFICIAL_REDIRECT (you file on the government portal), MANUAL record-keeping, or the clearly-labelled DEMO environment.
          </Disclaimer>
        </>
      )}
    </div>
  );
}
