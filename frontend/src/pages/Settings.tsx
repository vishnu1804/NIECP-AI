/** Settings (spec §29, §30): language, Easy Mode, theme, voice, reminders,
 * sessions, password. */
import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { LANGUAGES, useI18n } from "../lib/i18n";
import { Badge, Button, Card, CardHeader, Disclaimer, Field, Input, Spinner } from "../components/ui";
import { Link } from "react-router-dom";

export default function Settings() {
  const { user, prefs, refreshUser } = useApp();
  const { lang, setLang } = useI18n();
  const [sessions, setSessions] = useState<any[]>([]);
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    api<any>("/auth/me/sessions").then((r) => setSessions(r.sessions));
  }, []);

  const patchPrefs = async (patch: any) => {
    await api("/auth/me/preferences", "PATCH", patch);
    await refreshUser();
  };

  if (!user) return null;

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-xl font-bold text-white">Settings</h1>

      <Card className="border-brand-400/25">
        <div className="flex flex-wrap items-center justify-between gap-3 p-5">
          <div>
            <p className="text-[13.5px] font-semibold text-slate-100">Government integrations</p>
            <p className="text-[12px] text-slate-500">UDYAM dataset · MCA · Pincode · DigiLocker · NSWS · Tamil Nadu SWS — authorization status, test connection and fallbacks.</p>
          </div>
          <Link to="/settings/integrations"><Button variant="outline">Manage →</Button></Link>
        </div>
      </Card>

      <Card>
        <CardHeader title="Language & mode" subtitle="Interface language, Easy Mode for first-time and low-literacy users." />
        <div className="space-y-4 p-5">
          <Field label="Language">
            <div className="flex gap-2">
              {LANGUAGES.map((l) => (
                <button key={l.code} onClick={() => { setLang(l.code); patchPrefs({ language: l.code }); }}
                  className={`rounded-xl px-4 py-2 text-[13px] font-medium ${lang === l.code ? "bg-brand-500 text-white" : "border border-white/12 text-slate-300 hover:bg-white/8"}`}>
                  {l.native}
                </button>
              ))}
            </div>
          </Field>
          <label className="flex items-start gap-3 rounded-xl border border-teal-glow/25 bg-teal-glow/8 px-4 py-3">
            <input type="checkbox" checked={!!prefs?.easy_mode} onChange={(e) => patchPrefs({ easy_mode: e.target.checked })} className="mt-0.5 h-4 w-4 accent-teal-400" />
            <div>
              <div className="text-[13.5px] font-semibold text-teal-200">Easy Mode</div>
              <div className="text-[12px] leading-relaxed text-slate-400">Simple questions (“Does your factory produce smoke, wastewater or special waste?”), large buttons and voice guidance.</div>
            </div>
          </label>
        </div>
      </Card>

      <Card>
        <CardHeader title="Reminders" subtitle="Renewal and expiry reminder lead times (days before due date)." />
        <div className="flex flex-wrap items-center gap-2 p-5">
          {[7, 15, 30, 60, 90].map((d) => {
            const on = prefs?.reminder_days?.includes(d);
            return (
              <button key={d}
                onClick={async () => {
                  const cur = prefs?.reminder_days || [90, 60, 30, 7];
                  const next = on ? cur.filter((x) => x !== d) : [...cur, d].sort((a, b) => b - a);
                  await patchPrefs({ reminder_days: next });
                }}
                className={`rounded-full px-3.5 py-1.5 text-[12.5px] font-medium ${on ? "bg-brand-500 text-white" : "border border-white/12 text-slate-400"}`}>
                {d} days {on ? "✓" : ""}
              </button>
            );
          })}
        </div>
      </Card>

      <Card>
        <CardHeader title="Password & sessions" />
        <div className="space-y-4 p-5">
          <form className="grid gap-3 md:grid-cols-2" onSubmit={async (e) => {
            e.preventDefault();
            try {
              await api("/auth/me/password", "POST", pw);
              setPw({ current_password: "", new_password: "" });
              setMsg("Password changed. Other sessions were signed out.");
            } catch (e: any) {
              setMsg(e?.message);
            }
          }}>
            <Field label="Current password"><Input type="password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} autoComplete="current-password" /></Field>
            <Field label="New password"><Input type="password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} autoComplete="new-password" /></Field>
            <div className="md:col-span-2"><Button type="submit" size="sm">Change password</Button></div>
          </form>
          {msg ? <Disclaimer tone="blue">{msg}</Disclaimer> : null}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[12px] font-semibold uppercase tracking-wide text-slate-500">Active sessions ({sessions.length})</span>
              <Button size="sm" variant="ghost" onClick={async () => { await api("/auth/me/sessions/revoke-all", "POST", {}); setSessions([]); }}>Sign out everywhere</Button>
            </div>
            <div className="space-y-1.5">
              {sessions.map((s) => (
                <div key={s.id} className="flex items-center justify-between rounded-lg border border-white/8 bg-white/4 px-3 py-2 text-[11.5px] text-slate-400">
                  <span className="truncate">{s.user_agent?.slice(0, 60) || "Unknown device"}</span>
                  <span>{s.last_used_at ? new Date(s.last_used_at).toLocaleString() : "—"}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader title="Account" />
        <div className="space-y-2 p-5 text-[13px] text-slate-300">
          <div className="flex justify-between"><span className="text-slate-500">Email</span><span>{user.email} {user.email_verified ? <Badge tone="green">verified</Badge> : <Badge tone="amber">unverified</Badge>}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Platform role</span><Badge tone="violet">{user.platform_role.replace(/_/g, " ")}</Badge></div>
          <div className="flex justify-between"><span className="text-slate-500">Voice assistant</span>
            <label className="flex items-center gap-2 text-[12.5px]">
              <input type="checkbox" checked={!!prefs?.voice_enabled} onChange={(e) => patchPrefs({ voice_enabled: e.target.checked })} className="h-4 w-4 accent-brand-500" />
              enabled
            </label>
          </div>
        </div>
      </Card>
    </div>
  );
}
