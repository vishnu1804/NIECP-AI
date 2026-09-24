/** Regulatory change radar (spec §25). */
import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Badge, Card, Disclaimer, EmptyState, Spinner, StatusBadge } from "../components/ui";

const TYPE_LABEL: Record<string, string> = {
  NEW_REGULATION: "New regulation", CHANGED_REQUIREMENT: "Changed requirement", NEW_SCHEME: "New scheme",
  DEADLINE_CHANGE: "Deadline change", PORTAL_CHANGE: "Portal change", FORM_CHANGE: "Form change", RENEWAL_CHANGE: "Renewal change",
};

export default function ChangeRadar() {
  const [rows, setRows] = useState<any[] | null>(null);

  useEffect(() => { api<any>("/change-radar").then((r) => setRows(r.changes)); }, []);

  if (!rows) return <div className="flex justify-center py-20"><Spinner className="h-6 w-6" /></div>;

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div>
        <h1 className="text-xl font-bold text-white">Regulatory change radar</h1>
        <p className="text-[12.5px] text-slate-500">Verified changes from official sources. Unverified reports are never presented as regulation.</p>
      </div>

      <Disclaimer tone="amber">
        In this deployment, radar entries come from operator review of official sources (gazette, ministry portals).
        Anything unverified is labelled — and demo entries are marked DEMO.
      </Disclaimer>

      {rows.length === 0 ? (
        <EmptyState icon="📡" title="No changes on record" />
      ) : (
        <div className="space-y-3">
          {rows.map((c) => (
            <Card key={c.id} className="p-5">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <h3 className="text-[14px] font-semibold text-slate-100">
                  {c.is_demo ? <Badge tone="violet" className="mr-2">DEMO</Badge> : null}
                  {c.title}
                </h3>
                <div className="flex gap-1.5">
                  <Badge tone="blue">{TYPE_LABEL[c.change_type] || c.change_type}</Badge>
                  <StatusBadge value={c.verification_status === "VERIFIED_OFFICIAL" ? "VERIFIED_GOV_SOURCE" : "REQUIRES_VERIFICATION"}
                    label={c.verification_status?.replace(/_/g, " ")} />
                </div>
              </div>
              <div className="mt-3 space-y-2 text-[12.5px] leading-relaxed">
                <ChangeBlock icon="❗" label="What changed" text={c.what_changed} />
                {c.who_may_be_affected ? <ChangeBlock icon="👥" label="Who may be affected" text={c.who_may_be_affected} /> : null}
                {c.why_it_matters ? <ChangeBlock icon="🧭" label="Why it matters" text={c.why_it_matters} /> : null}
                {c.recommended_review ? <ChangeBlock icon="✅" label="Recommended review" text={c.recommended_review} /> : null}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                {c.publisher ? <Badge tone="slate">{c.publisher}</Badge> : null}
                {c.detected_at ? <span>detected {new Date(c.detected_at).toLocaleDateString()}</span> : null}
                {c.source_url ? <a href={c.source_url} target="_blank" rel="noopener noreferrer" className="text-brand-300 hover:underline">View source ↗</a> : null}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function ChangeBlock({ icon, label, text }: { icon: string; label: string; text: string }) {
  return (
    <div className="flex gap-2.5 rounded-lg border border-white/8 bg-white/4 px-3 py-2">
      <span aria-hidden>{icon}</span>
      <div>
        <div className="text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">{label}</div>
        <div className="text-slate-300">{text}</div>
      </div>
    </div>
  );
}
