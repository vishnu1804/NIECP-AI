/** Compliance calendar (spec §20): month grid + upcoming list + renewals. */
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import { Badge, Button, Card, CardHeader, Disclaimer, Spinner, StatusBadge } from "../components/ui";

const KIND_ICON: Record<string, string> = { renewal: "🔁", task: "✅", query: "💬", inspection: "🔍", document_expiry: "⏰" };
const KIND_TONE: Record<string, any> = { renewal: "red", task: "blue", query: "amber", inspection: "violet", document_expiry: "amber" };

export default function CalendarPage() {
  const { projectId } = useParams();
  const today = new Date();
  const [ym, setYm] = useState({ year: today.getFullYear(), month: today.getMonth() + 1 });
  const [data, setData] = useState<any>(null);
  const [renewals, setRenewals] = useState<any[]>([]);

  const load = async () => {
    setData(await api<any>(`/projects/${projectId}/calendar?year=${ym.year}&month=${ym.month}`));
    setRenewals((await api<any>(`/projects/${projectId}/renewals`)).renewals);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [projectId, ym]);

  if (!data) return <div className="flex justify-center py-20"><Spinner className="h-6 w-6" /></div>;

  const monthName = new Date(ym.year, ym.month - 1, 1).toLocaleString("en", { month: "long", year: "numeric" });
  const first = new Date(ym.year, ym.month - 1, 1);
  const startDow = (first.getDay() + 6) % 7; // Monday-first
  const daysInMonth = new Date(ym.year, ym.month, 0).getDate();
  const byDay: Record<number, any[]> = {};
  for (const e of data.events) {
    const d = new Date(e.date).getDate();
    (byDay[d] = byDay[d] || []).push(e);
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-white">Compliance calendar</h1>
          <p className="text-[12.5px] text-slate-500">Renewals, expiries, inspections, deadlines and queries.</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setYm(({ year, month }) => month === 1 ? { year: year - 1, month: 12 } : { year, month: month - 1 })}>←</Button>
          <span className="min-w-36 text-center text-[13.5px] font-semibold text-slate-200">{monthName}</span>
          <Button variant="outline" size="sm" onClick={() => setYm(({ year, month }) => month === 12 ? { year: year + 1, month: 1 } : { year, month: month + 1 })}>→</Button>
        </div>
      </div>

      {/* grid */}
      <Card className="overflow-hidden">
        <div className="grid grid-cols-7 border-b border-white/8 text-center text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">
          {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => <div key={d} className="py-2">{d}</div>)}
        </div>
        <div className="grid grid-cols-7">
          {Array.from({ length: startDow }).map((_, i) => <div key={`e${i}`} className="min-h-20 border-b border-r border-white/5" />)}
          {Array.from({ length: daysInMonth }).map((_, i) => {
            const day = i + 1;
            const isToday = ym.year === today.getFullYear() && ym.month === today.getMonth() + 1 && day === today.getDate();
            const events = byDay[day] || [];
            return (
              <div key={day} className={`min-h-20 border-b border-r border-white/5 p-1.5 ${isToday ? "bg-brand-500/10" : ""}`}>
                <div className={`text-[11px] font-semibold ${isToday ? "text-brand-300" : "text-slate-500"}`}>{day}</div>
                <div className="space-y-1">
                  {events.slice(0, 3).map((e: any, j: number) => (
                    <div key={j} className={`truncate rounded px-1 py-0.5 text-[9.5px] font-medium ${e.kind === "renewal" ? "bg-rose-500/20 text-rose-200" : e.kind === "query" ? "bg-amber-500/20 text-amber-200" : "bg-sky-500/15 text-sky-200"}`} title={e.title}>
                      {KIND_ICON[e.kind]} {e.title}
                    </div>
                  ))}
                  {events.length > 3 ? <div className="text-[9px] text-slate-500">+{events.length - 3} more</div> : null}
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      {/* next 7 days */}
      <Card>
        <CardHeader title="Next 7 days" />
        <div className="space-y-1.5 p-4">
          {data.next_7_days.length === 0 ? <p className="text-[13px] text-slate-500">Nothing due in the next 7 days.</p> : data.next_7_days.map((i: any, k: number) => (
            <div key={k} className="flex items-center justify-between rounded-lg border border-white/8 bg-white/4 px-3 py-2">
              <span className="text-[13px] text-slate-200">{KIND_ICON[i.kind]} {i.title}</span>
              <Badge tone={i.kind === "query" ? "amber" : "slate"}>{i.due_date}</Badge>
            </div>
          ))}
        </div>
      </Card>

      {/* renewals */}
      <Card>
        <CardHeader title="Renewal tracker" subtitle="Reminder engine: 90 / 60 / 30 / 7 days before each due date (configurable in settings)." />
        <div className="space-y-2 p-4">
          {renewals.length === 0 ? <p className="text-[13px] text-slate-500">No renewals tracked yet. When you record an approval outcome with a validity date, a renewal appears here automatically.</p> : renewals.map((r) => (
            <div key={r.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/8 bg-white/4 px-3.5 py-2.5">
              <div className="flex items-center gap-2">
                {r.is_demo ? <Badge tone="violet">DEMO</Badge> : null}
                <span className="text-[13.5px] text-slate-100">{r.title}</span>
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={r.days_remaining < 0 ? "red" : r.days_remaining < 30 ? "amber" : "slate"}>
                  {r.days_remaining < 0 ? `${-r.days_remaining}d overdue` : `${r.days_remaining}d left`}
                </Badge>
                <StatusBadge value={r.status} />
                {r.status !== "RENEWED" ? (
                  <Button size="sm" variant="outline" onClick={async () => { await api(`/projects/${projectId}/renewals/${r.id}/renew`, "POST", {}); await load(); }}>Mark renewed</Button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
