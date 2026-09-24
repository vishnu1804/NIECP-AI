/** Project scheme matching (spec §19). */
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import { Badge, Button, Card, CardHeader, Disclaimer, Modal, Spinner, StatusBadge } from "../components/ui";

const VERDICT_LABEL: Record<string, { tone: any; label: string }> = {
  POSSIBLY_RELEVANT: { tone: "green", label: "Criteria matched" },
  NEEDS_MORE_INFO: { tone: "amber", label: "Needs more info" },
  LIKELY_NOT_APPLICABLE: { tone: "slate", label: "Likely not applicable" },
  UNABLE_TO_ASSESS: { tone: "slate", label: "Unable to assess" },
};

export default function ProjectSchemes() {
  const { projectId } = useParams();
  const [matches, setMatches] = useState<any[] | null>(null);
  const [detail, setDetail] = useState<any>(null);

  const load = async () => setMatches((await api<any>(`/projects/${projectId}/schemes`)).matches);
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [projectId]);

  if (!matches) return <div className="flex justify-center py-20"><Spinner className="h-6 w-6" /></div>;

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Schemes & incentives for this project</h1>
          <p className="text-[12.5px] text-slate-500">Your profile checked against each scheme's documented criteria.</p>
        </div>
        <Button variant="outline" size="sm" onClick={load}>↻ Refresh</Button>
      </div>

      <Disclaimer tone="violet">
        NIECP-AI compares your data against published criteria — it never decides eligibility. The administering authority does.
      </Disclaimer>

      <div className="space-y-3">
        {matches.map((m) => {
          const v = VERDICT_LABEL[m.verdict] || VERDICT_LABEL.UNABLE_TO_ASSESS;
          return (
            <Card key={m.code} className="p-4" onClick={() => setDetail(m)}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-[14px] font-semibold text-slate-100">{m.name}</h3>
                    <Badge tone={m.level === "CENTRAL" ? "blue" : "violet"}>{m.level}</Badge>
                  </div>
                  <div className="mt-0.5 text-[12px] text-slate-500">{m.authority}</div>
                  <p className="mt-1.5 line-clamp-2 text-[12.5px] leading-relaxed text-slate-400">{m.why_this_may_apply}</p>
                </div>
                <div className="flex flex-col items-end gap-1.5">
                  <Badge tone={v.tone}>{v.label}</Badge>
                  <span className="text-[11px] text-slate-500">{m.met}/{m.criteria.length} criteria met</span>
                </div>
              </div>
            </Card>
          );
        })}
        {matches.length === 0 ? <p className="py-10 text-center text-[13px] text-slate-500">No schemes match yet — complete more of your profile and refresh.</p> : null}
      </div>

      <Modal open={!!detail} onClose={() => setDetail(null)} title={detail?.name || ""} wide>
        {detail ? (
          <div className="space-y-4">
            <p className="text-[13.5px] leading-relaxed text-slate-300">{detail.short_description}</p>
            <div>
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Criteria check</h4>
              <div className="space-y-1.5">
                {detail.criteria.map((c: any, i: number) => (
                  <div key={i} className="flex items-start gap-2 rounded-lg border border-white/8 bg-white/4 px-3 py-2 text-[12.5px]">
                    <span>{c.state === "MET" ? "✅" : c.state === "NOT_MET" ? "❌" : "❔"}</span>
                    <div>
                      <div className="text-slate-200">{c.human_text}</div>
                      {c.state === "INFO_REQUIRED" && c.missing?.length ? (
                        <div className="mt-0.5 text-[11px] text-amber-300/80">Needs: {c.missing.join(", ")}</div>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            </div>
            {detail.benefits?.length ? (
              <div>
                <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Benefits</h4>
                <ul className="list-inside list-disc space-y-0.5 text-[12.5px] text-slate-400">
                  {detail.benefits.map((b: string, i: number) => <li key={i}>{b}</li>)}
                </ul>
              </div>
            ) : null}
            {detail.required_documents?.length ? (
              <div>
                <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Documents typically needed</h4>
                <div className="flex flex-wrap gap-1.5">{detail.required_documents.map((d: string) => <Badge key={d} tone="slate">{d}</Badge>)}</div>
              </div>
            ) : null}
            {detail.application_process ? <p className="text-[12px] leading-relaxed text-slate-500"><span className="font-semibold text-slate-400">Process:</span> {detail.application_process}</p> : null}
            <div className="flex gap-2 border-t border-white/10 pt-3">
              {detail.official_url ? <a href={detail.official_url} target="_blank" rel="noopener noreferrer"><Button size="sm">Official source ↗</Button></a> : null}
              <StatusBadge value={detail.verification_status} />
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
