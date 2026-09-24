/** Organization analytics (spec §41) — preparation metrics only, never
 * government approval statistics. */
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import { Badge, Card, CardHeader, Disclaimer, Progress, Spinner } from "../components/ui";

export default function Analytics() {
  const { projectId } = useParams();
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    api<any>(`/projects/${projectId}/analytics`).then(setData);
  }, [projectId]);

  if (!data) return <div className="flex justify-center py-20"><Spinner className="h-6 w-6" /></div>;

  const appEntries = Object.entries(data.applications.by_status || {}).filter(([, v]) => (v as number) > 0);
  const maxApp = Math.max(1, ...appEntries.map(([, v]) => v as number));

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div>
        <h1 className="text-xl font-bold text-white">Analytics</h1>
        <p className="text-[12.5px] text-slate-500">Preparation activity within NIECP-AI.</p>
      </div>

      <Disclaimer tone="violet">{data.note}</Disclaimer>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Applications" value={data.applications.total} sub={`${data.applications.submitted} submitted`} />
        <Stat label="User confirmed" value={data.applications.user_confirmed} sub="explicit confirmations" />
        <Stat label="Documents" value={data.documents.total} sub={`${data.documents.processed} processed · ${data.documents.expired} expired`} />
        <Stat label="Compliance tasks" value={data.tasks.total} sub={`${data.tasks.open} open · ${data.tasks.overdue} overdue`} />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader title="Applications by status" />
          <div className="space-y-2.5 p-5">
            {appEntries.length === 0 ? <p className="text-[13px] text-slate-500">No applications yet.</p> : appEntries.map(([k, v]) => (
              <div key={k as string}>
                <div className="mb-1 flex justify-between text-[11.5px]">
                  <span className="text-slate-400">{String(k).replace(/_/g, " ")}</span>
                  <span className="font-semibold text-slate-200">{String(v)}</span>
                </div>
                <Progress value={(100 * (v as number)) / maxApp} height="h-1.5" label={String(k)} />
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <CardHeader title="Document health" />
          <div className="space-y-3 p-5">
            <ProgressRow label="Processed cleanly" value={data.documents.processed} total={Math.max(1, data.documents.total)} tone="green" />
            <ProgressRow label="With findings" value={data.documents.with_findings} total={Math.max(1, data.documents.total)} tone="amber" />
            <ProgressRow label="Expired" value={data.documents.expired} total={Math.max(1, data.documents.total)} tone="red" />
          </div>
        </Card>
      </div>

      {data.readiness?.components ? (
        <Card>
          <CardHeader title="Readiness components" right={<Badge tone="blue">{data.readiness.overall}% overall</Badge>} />
          <div className="grid gap-3 p-5 md:grid-cols-3">
            {data.readiness.components.map((c: any) => (
              <div key={c.key}>
                <div className="mb-1 flex justify-between text-[11.5px]">
                  <span className="text-slate-400">{c.label}</span>
                  <span className="font-semibold text-slate-200">{c.score}%</span>
                </div>
                <Progress value={c.score} height="h-1.5" label={c.label} />
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <Card className="p-4">
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-bold text-white">{value}</div>
      {sub ? <div className="mt-0.5 text-[11px] text-slate-500">{sub}</div> : null}
    </Card>
  );
}

function ProgressRow({ label, value, total, tone }: { label: string; value: number; total: number; tone: any }) {
  const pct = Math.round((100 * value) / total);
  return (
    <div>
      <div className="mb-1 flex justify-between text-[12px]">
        <span className="text-slate-400">{label}</span>
        <span className="font-semibold text-slate-200">{value} ({pct}%)</span>
      </div>
      <Progress value={pct} tone={tone} height="h-1.5" label={label} />
    </div>
  );
}
