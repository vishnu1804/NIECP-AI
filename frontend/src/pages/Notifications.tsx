/** Notifications center (spec §34). */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { Badge, Button, Card, Disclaimer, EmptyState, Spinner } from "../components/ui";

export default function Notifications() {
  const [rows, setRows] = useState<any[] | null>(null);
  const { refreshNotifications } = useApp();
  const navigate = useNavigate();

  const load = async () => setRows((await api<any>("/notifications?limit=100")).notifications);
  useEffect(() => { load(); }, []);

  const open = async (n: any) => {
    if (!n.read) {
      await api("/notifications/read", "POST", { ids: [n.id] });
      refreshNotifications();
    }
    if (n.link) navigate(n.link.replace("{pid}", String(n.project_id || "")));
    else load();
  };

  if (!rows) return <div className="flex justify-center py-20"><Spinner className="h-6 w-6" /></div>;

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Notifications</h1>
          <p className="text-[12.5px] text-slate-500">Renewal reminders, queries, document expiries and system events.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={async () => { await api("/notifications/read", "POST", { all: true }); await load(); refreshNotifications(); }}>Mark all read</Button>
          <Button variant="subtle" size="sm" onClick={async () => { const r = await api<any>("/notifications/test", "POST", {}); alert(`Test notification created. Email status: ${r.email_status}${r.email_error ? ` (${r.email_error})` : ""}`); }}>Send test</Button>
        </div>
      </div>

      <Disclaimer tone="blue">Browser notifications are requested when you first use the voice assistant. Email delivery status is shown honestly per notification — if SMTP is not configured, notifications stay in-app and say so.</Disclaimer>

      {rows.length === 0 ? (
        <EmptyState icon="🔔" title="No notifications" hint="Reminders appear as renewals and deadlines approach." />
      ) : (
        <div className="space-y-2">
          {rows.map((n) => (
            <Card key={n.id} className={`p-4 ${n.read ? "opacity-70" : "border-brand-400/25"}`} onClick={() => open(n)}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-[13.5px] font-medium text-slate-100">{n.title}</span>
                <div className="flex items-center gap-2">
                  <Badge tone={n.severity === "CRITICAL" ? "red" : n.severity === "WARNING" ? "amber" : "slate"}>{n.severity}</Badge>
                  {n.email_status && n.email_status !== "NOT_CONFIGURED" ? <Badge tone={n.email_status === "SENT" ? "green" : "amber"}>email: {n.email_status.toLowerCase()}</Badge> : null}
                </div>
              </div>
              {n.body ? <p className="mt-1 text-[12.5px] leading-relaxed text-slate-400">{n.body}</p> : null}
              <div className="mt-1 text-[10.5px] text-slate-600">{new Date(n.created_at).toLocaleString()}</div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
