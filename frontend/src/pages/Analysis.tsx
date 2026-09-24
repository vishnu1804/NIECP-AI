/** AI analysis + readiness dashboard (spec §6, §8). */
import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { Badge, Button, Card, CardHeader, Disclaimer, Progress, Spinner, StatusBadge } from "../components/ui";

export default function Analysis() {
  const { projectId } = useParams();
  const [readiness, setReadiness] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [showDetail, setShowDetail] = useState<string | null>(null);
  const navigate = useNavigate();

  const load = async () => {
    setReadiness(await api<any>(`/projects/${projectId}/readiness`));
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [projectId]);

  const run = async () => {
    setBusy(true);
    try {
      setResult(await api<any>(`/projects/${projectId}/analysis`, "POST", {}));
      await load();
    } catch (e: any) {
      alert(e?.message || "Analysis failed — is the industry set on the profile?");
    } finally {
      setBusy(false);
    }
  };

  const comp = readiness?.components || [];
  const byKey = (k: string) => comp.find((c: any) => c.key === k);

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-white">AI Project Analysis & Readiness</h1>
          <p className="text-[12.5px] text-slate-500">Deterministic rule engine over your Master Project Profile. Every result shows its reasoning.</p>
        </div>
        <Button onClick={run} disabled={busy}>{busy ? <Spinner /> : "⚡"} Run / refresh analysis</Button>
      </div>

      {/* overall */}
      <Card className="p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Overall preparation</div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-4xl font-extrabold text-white">{readiness?.overall ?? "—"}</span>
              <span className="text-lg text-slate-500">%</span>
            </div>
          </div>
          <div className="grid flex-1 gap-3 sm:grid-cols-3">
            {(comp || []).slice(0, 6).map((c: any) => (
              <div key={c.key}>
                <div className="mb-1 flex justify-between text-[11.5px]">
                  <span className="text-slate-400">{c.label}</span>
                  <span className="font-semibold text-slate-200">{c.score}%</span>
                </div>
                <Progress value={c.score} height="h-1.5" tone={c.score >= 70 ? "green" : c.score >= 40 ? "brand" : "amber"} label={c.label} />
              </div>
            ))}
          </div>
        </div>
        <div className="mt-4"><Disclaimer tone="violet">{readiness?.disclaimer}</Disclaimer></div>
      </Card>

      {/* component explanations */}
      <div className="grid gap-4 lg:grid-cols-2">
        {comp.map((c: any) => (
          <Card key={c.key}>
            <CardHeader
              title={<span className="flex items-center gap-2">{c.label} <Badge tone={c.score >= 70 ? "green" : c.score >= 40 ? "blue" : "amber"}>{c.score}%</Badge></span>}
              right={<button className="text-xs text-slate-500 hover:text-brand-300" onClick={() => setShowDetail(showDetail === c.key ? null : c.key)}>{showDetail === c.key ? "Hide" : "Why?"}</button>}
            />
            <div className="p-4">
              <p className="text-[12.5px] leading-relaxed text-slate-400">{c.explanation}</p>
              {showDetail === c.key ? (
                <div className="mt-3 space-y-2 border-t border-white/8 pt-3">
                  {c.missing?.length ? (
                    <div>
                      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Missing ({c.missing.length})</div>
                      <div className="flex flex-wrap gap-1.5">
                        {c.missing.slice(0, 20).map((m: any, i: number) => <Badge key={i} tone="amber">{m.label || m.title}</Badge>)}
                      </div>
                    </div>
                  ) : null}
                  {c.unevaluable?.length ? (
                    <div>
                      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Cannot evaluate yet</div>
                      <ul className="space-y-1 text-[12px] text-slate-400">
                        {c.unevaluable.slice(0, 8).map((u: string, i: number) => <li key={i}>• {u}</li>)}
                      </ul>
                    </div>
                  ) : null}
                  {c.blocked?.length ? (
                    <div>
                      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Blocked approvals</div>
                      {c.blocked.map((b: any, i: number) => <div key={i} className="text-[12.5px] text-slate-300">{b.approval} — <StatusBadge value={b.state} /></div>)}
                    </div>
                  ) : null}
                  {c.key === "documents" && c.missing?.length ? (
                    <Button size="sm" variant="outline" onClick={() => navigate(`/projects/${projectId}/documents`)}>Open document centre →</Button>
                  ) : null}
                </div>
              ) : null}
            </div>
          </Card>
        ))}
      </div>

      {result ? (
        <Card>
          <CardHeader title="Latest analysis" subtitle={result.summary ? `${result.summary.applies} apply · ${result.summary.conditional} conditional · ${result.summary.not_applicable} not applicable` : ""} />
          <div className="p-4"><Disclaimer tone="amber">{result.disclaimer}</Disclaimer></div>
        </Card>
      ) : null}
    </div>
  );
}
