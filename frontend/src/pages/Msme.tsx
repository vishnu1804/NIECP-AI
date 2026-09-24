/** MSME Regulatory Intelligence (MSME upgrade §1–§15).
 *  Deterministic MSMED Act intelligence over the project profile: versioned
 *  §7 classification, §8 registration check, conditional provisions, alerts,
 *  Payment Protection (§§15-18), MAITRI services (OFFICIAL_REDIRECT), Smart
 *  Action Guide and the law-version table. Follows the existing design
 *  language (cards, badges, disclaimers). */
import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { Badge, Button, Card, CardHeader, Disclaimer, Field, Input, Select, Spinner } from "../components/ui";

const ICONS: Record<string, string> = { "✓": "✅", "⚠": "⚠️", "⏳": "⏳", "ℹ": "ℹ️", "❌": "❌" };

function ProvisionsCard({ provisions }: { provisions: any[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const toneOf = (a: string) => (a === "APPLICABLE" ? "green" : a === "CONDITIONAL" ? "amber" : a === "NOT_APPLICABLE" ? "slate" : "blue");
  return (
    <Card>
      <CardHeader title="Applicable MSME provisions" subtitle="MSMED Act, 2006 — evaluated against your project profile. Nothing applies automatically; conditions are shown. Authored digests — verify at the official sources." />
      <div className="space-y-1.5 p-4">
        {provisions.map((p) => (
          <div key={p.section} className="rounded-xl border border-white/8 bg-white/4">
            <button className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left" onClick={() => setOpen(open === p.section ? null : p.section)}>
              <span className="text-[14px]">{ICONS[p.status_icon] || "•"}</span>
              <span className="font-mono text-[11px] text-slate-500">§{p.section}</span>
              <span className="flex-1 text-[13px] font-medium text-slate-100">{p.title}</span>
              <Badge tone={toneOf(p.applicability)}>{p.applicability}</Badge>
              <span className="text-slate-600">{open === p.section ? "▾" : "›"}</span>
            </button>
            {open === p.section ? (
              <div className="space-y-2 border-t border-white/8 px-3.5 py-3 text-[12px] leading-relaxed">
                <p className="text-slate-300">{p.summary}</p>
                <p><span className="font-semibold text-slate-400">Why shown:</span> <span className="text-slate-300">{p.why}</span></p>
                {p.required_inputs?.length ? <p><span className="font-semibold text-slate-400">Inputs:</span> <span className="text-slate-300">{p.required_inputs.join(" · ")}</span></p> : null}
                {p.required_documents?.length ? <p><span className="font-semibold text-slate-400">Documents:</span> <span className="text-slate-300">{p.required_documents.join(" · ")}</span></p> : null}
                <p><span className="font-semibold text-slate-400">Recommended action:</span> <span className="text-teal-200">{p.recommended_action}</span></p>
                <p><span className="font-semibold text-slate-400">Authority:</span> <span className="text-slate-300">{p.authority}</span></p>
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <Badge tone="violet">{p.label}</Badge>
                  <a href={p.official_source} target="_blank" rel="noopener noreferrer" className="text-[11.5px] text-brand-300 hover:underline">Official source ↗</a>
                  <a href={`#/msme-explain?section=${p.section}`} className="text-[11.5px] text-slate-500">Explain for my project (ask NIECP-AI)</a>
                </div>
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </Card>
  );
}

function PaymentProtection({ projectId }: { projectId: string }) {
  const [form, setForm] = useState({ supplier_enterprise_class: "MICRO", invoice_date: "", supply_date: "", amount: "", buyer_type: "", payment_terms_days: "", payment_date: "" });
  const [result, setResult] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setErr(null); setResult(null);
    try {
      const r = await api<any>(`/projects/${projectId}/msme/payment-assessment`, "POST", {
        supplier_enterprise_class: form.supplier_enterprise_class,
        invoice_date: form.invoice_date,
        supply_date: form.supply_date || null,
        amount: Number(form.amount),
        buyer_type: form.buyer_type || null,
        payment_terms_days: form.payment_terms_days ? Number(form.payment_terms_days) : null,
        payment_date: form.payment_date || null,
      });
      setResult(r);
    } catch (e: any) { setErr(e?.message || "Assessment failed."); }
  };
  const ok = form.invoice_date && Number(form.amount) > 0;
  return (
    <Card>
      <CardHeader title="MSME Payment Protection" subtitle="Delay and statutory-interest assessment for Micro/Small suppliers (MSMED §§15-18). Informational regulatory assessment — not legal advice." />
      <div className="space-y-3 p-4">
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Supplier class">
            <Select value={form.supplier_enterprise_class} onChange={(e) => setForm({ ...form, supplier_enterprise_class: e.target.value })}>
              {["MICRO", "SMALL", "MEDIUM", "LARGE"].map((c) => <option key={c} value={c}>{c}</option>)}
            </Select>
          </Field>
          <Field label="Invoice date" required><Input type="date" value={form.invoice_date} onChange={(e) => setForm({ ...form, invoice_date: e.target.value })} /></Field>
          <Field label="Supply / acceptance date" hint="Leave blank to use the invoice date"><Input type="date" value={form.supply_date} onChange={(e) => setForm({ ...form, supply_date: e.target.value })} /></Field>
          <Field label="Invoice amount (₹)" required><Input type="number" min="1" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></Field>
          <Field label="Agreed payment period (days)" hint="Blank = statutory default of 45 days (verify current text)"><Input type="number" min="1" max="365" value={form.payment_terms_days} onChange={(e) => setForm({ ...form, payment_terms_days: e.target.value })} /></Field>
          <Field label="Payment date" hint="Leave blank if unpaid"><Input type="date" value={form.payment_date} onChange={(e) => setForm({ ...form, payment_date: e.target.value })} /></Field>
        </div>
        <Field label="Buyer type" hint="e.g. Private limited company, Proprietorship, PSU"><Input value={form.buyer_type} onChange={(e) => setForm({ ...form, buyer_type: e.target.value })} /></Field>
        <Button disabled={!ok} onClick={run}>Run assessment</Button>
        {err ? <Disclaimer tone="amber">{err}</Disclaimer> : null}
        {result?.ok ? (
          <div className="space-y-2.5">
            <div className={`rounded-xl border p-3.5 ${result.delayed_payment_flag ? "border-rose-400/30 bg-rose-400/8" : "border-emerald-400/25 bg-emerald-400/8"}`}>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={result.delayed_payment_flag ? "red" : "green"}>{result.flag_label}</Badge>
                <Badge tone="slate">supplier: {result.supplier_class_declared}</Badge>
              </div>
              <p className="mt-2 text-[12px] text-slate-300">{result.msmed_note}</p>
              <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[12px] text-slate-300 md:grid-cols-4">
                <span>Due date: <span className="font-semibold">{result.timeline.due_date}</span></span>
                <span>Days past due: <span className="font-semibold">{result.timeline.days_past_due}</span></span>
                <span>Principal: ₹{result.amounts.principal.toLocaleString("en-IN")}</span>
                <span>Interest (indicative): ₹{result.interest_estimate.amount.toLocaleString("en-IN")}</span>
              </div>
              <p className="mt-1.5 text-[11px] text-slate-500">{result.timeline.basis}</p>
            </div>
            <div className="rounded-xl border border-white/8 bg-white/4 p-3 text-[12px] text-slate-300">
              <p className="font-semibold text-slate-200">Applicable sections</p>
              <p className="mt-1">{result.applicable_sections.map((s: string) => `§${s}`).join(" · ")}</p>
              <p className="mt-2 font-semibold text-slate-200">Recommended path</p>
              <ol className="mt-1 list-inside list-decimal space-y-0.5 text-slate-300">
                {result.recommended_path.map((s: string, i: number) => <li key={i}>{s}</li>)}
              </ol>
              <div className="mt-2 flex flex-wrap gap-3">
                <a href={result.official_routes.samadhaan} target="_blank" rel="noopener noreferrer" className="text-[11.5px] text-brand-300 hover:underline">Samadhaan portal (official) ↗</a>
                <a href={result.official_routes.sources.act} target="_blank" rel="noopener noreferrer" className="text-[11.5px] text-brand-300 hover:underline">Act text (India Code) ↗</a>
              </div>
              <p className="mt-2 text-[10.5px] text-slate-500">{result.interest_estimate.formula} · {result.interest_estimate.status} · {result.disclaimer}</p>
            </div>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

export default function Msme() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = async () => {
    try { setData(await api<any>(`/projects/${projectId}/msme/intelligence`)); }
    catch (e: any) { setErr(e?.message || "Could not load MSME intelligence."); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [projectId]);

  if (err) return <div className="mx-auto max-w-4xl"><Disclaimer tone="amber">{err}</Disclaimer></div>;
  if (!data) return <div className="flex justify-center py-20"><Spinner className="h-6 w-6" /></div>;

  const cls = data.business_classification || {};
  const twin = data.msme_status || {};
  const alerts = data.compliance_risks || [];
  const guide = data.smart_action_guide || [];
  const maitri = data.maharashtra_approvals || {};

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div>
        <h1 className="text-xl font-bold text-white">MSME Regulatory Intelligence</h1>
        <p className="text-[12.5px] text-slate-500">From business profile → regulatory intelligence → applicable requirements → dependencies → documents → smart action → official government channel.</p>
      </div>

      <Disclaimer tone="violet">
        Regulatory intelligence from an authored digest of the MSMED Act, 2006 with versioned classification criteria. Not legal advice, not an official classification or verification — verify every conclusion at the official sources.
      </Disclaimer>

      {/* classification + registration */}
      <div className="grid gap-3 md:grid-cols-2">
        <Card className="p-4">
          <div className="text-[10.5px] font-bold uppercase tracking-[0.12em] text-slate-500">MSME status (potential classification)</div>
          <div className="mt-1 flex items-center gap-2">
            <span className="text-2xl">{ICONS[cls.status_icon] || "⚠"}</span>
            <span className="text-2xl font-bold text-white">{cls.potential_class || "INFORMATION REQUIRED"}</span>
          </div>
          <p className="mt-1 text-[11.5px] text-slate-400">{cls.declaration}</p>
          {cls.missing_inputs?.length ? (
            <p className="mt-1 text-[11.5px] text-amber-300/80">Missing: {cls.missing_inputs.join(" · ")} — <button className="text-brand-300 hover:underline" onClick={() => navigate(`/projects/${projectId}/profile`)}>complete in profile</button></p>
          ) : null}
          {cls.inputs_used ? <p className="mt-1 text-[11px] text-slate-500">Inputs: machinery investment ₹{cls.inputs_used.machinery_investment_cr} Cr · turnover ₹{cls.inputs_used.annual_turnover_cr} Cr · law version {cls.law_version}</p> : null}
        </Card>
        <Card className="p-4">
          <div className="text-[10.5px] font-bold uppercase tracking-[0.12em] text-slate-500">Registration status (§8 Udyam)</div>
          <div className="mt-1 flex items-center gap-2">
            <span className="text-2xl">{ICONS[twin?.registration?.status_icon] || "⚠"}</span>
            <span className="text-[15px] font-bold text-white">{twin?.registration?.status || "—"}</span>
          </div>
          <p className="mt-1 text-[11.5px] text-slate-400">{twin?.registration?.note}</p>
          <p className="mt-1 text-[11.5px] text-teal-200">{twin?.registration?.recommended_action}</p>
          <a href={twin?.registration?.official_source || "https://udyamregistration.gov.in/"} target="_blank" rel="noopener noreferrer" className="mt-1 inline-block text-[11.5px] text-brand-300 hover:underline">Official Udyam portal ↗</a>
        </Card>
      </div>

      {/* digital twin additions */}
      <Card>
        <CardHeader title="Regulatory digital twin — MSME block" subtitle="Business profile data with provenance labels. ✓ verified only where an official source actually verifies it." />
        <div className="space-y-1 p-4">
          {(twin.entries || []).map((e: any, i: number) => (
            <div key={i} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/8 bg-white/4 px-3 py-2 text-[12.5px]">
              <span className="flex items-center gap-2 text-slate-300"><span>{ICONS[e.icon] || "•"}</span> {e.item}</span>
              <span className="flex items-center gap-2">
                <span className="font-medium text-slate-100">{e.value === null || e.value === undefined || e.value === "" ? "—" : String(e.value)}</span>
                <Badge tone="slate">{e.label}</Badge>
              </span>
            </div>
          ))}
          <Disclaimer tone="amber">{twin.law_warning}</Disclaimer>
        </div>
      </Card>

      {/* alerts */}
      <Card>
        <CardHeader title="MSME compliance alerts" subtitle="Computed from your project data — each shows why it fired, the section, the evidence and the next action." />
        <div className="space-y-2 p-4">
          {alerts.length === 0 ? <p className="text-[12.5px] text-slate-500">No alerts for the current profile state.</p> : alerts.map((a: any, i: number) => (
            <div key={i} className="rounded-xl border border-white/8 bg-white/4 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span>{ICONS[a.icon] || "•"}</span>
                <span className="text-[13px] font-semibold text-slate-100">{a.alert}</span>
                <Badge tone={a.severity === "WARNING" ? "amber" : "slate"}>§{a.section}</Badge>
                <Badge tone="violet">{a.label}</Badge>
              </div>
              <p className="mt-1.5 text-[12px] text-slate-400"><span className="font-semibold text-slate-500">Why:</span> {a.why}</p>
              <p className="text-[12px] text-slate-400"><span className="font-semibold text-slate-500">Evidence:</span> {a.evidence}</p>
              <p className="text-[12px] text-teal-200"><span className="font-semibold text-slate-500">Next action:</span> {a.recommended_action}</p>
              <a href={a.official_source} target="_blank" rel="noopener noreferrer" className="mt-1 inline-block text-[11.5px] text-brand-300 hover:underline">Official source ↗</a>
            </div>
          ))}
        </div>
      </Card>

      <ProvisionsCard provisions={data.applicable_msme_provisions || []} />

      {/* MAITRI */}
      {maitri.relevant ? (
        <Card>
          <CardHeader title="Maharashtra MAITRI services" subtitle="Official state facilitation layer — OFFICIAL PORTAL route only, NIECP-AI never automates submission." />
          <div className="space-y-2 p-4">
            {maitri.services.map((s: any) => (
              <div key={s.code} className="rounded-xl border border-white/8 bg-white/4 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13px] font-semibold text-slate-100">{s.name}</span>
                  <Badge tone="blue">{s.verification_status.replace(/_/g, " ")}</Badge>
                </div>
                <p className="mt-1 text-[11.5px] text-slate-500">{s.department}{s.sub_department ? ` · ${s.sub_department}` : ""}</p>
                {s.tat_days ? (
                  <p className="text-[11px] text-slate-400">Official TAT: {s.tat_days} days</p>
                ) : (
                  <p className="text-[11px] text-slate-600">{s.tat_note || "Turnaround time not officially documented in NIECP-AI's sources — confirm on the MAITRI portal."}</p>
                )}
                <p className="mt-1 text-[12px] text-slate-300"><span className="font-semibold text-slate-400">Why it may apply:</span> {s.why}</p>
                <p className="text-[12px] text-slate-400"><span className="font-semibold text-slate-400">Required info:</span> {s.required_info.join(" · ")}</p>
                <p className="text-[12px] text-slate-400"><span className="font-semibold text-slate-400">Dependency:</span> {s.dependency}</p>
                {(s.approval_links || []).length ? (
                  <div className="mt-2 rounded-lg border border-white/8 bg-white/3 p-2.5">
                    <p className="text-[11px] font-semibold text-slate-400">Linked approvals (authored routing — confirm on the portal)</p>
                    {(s.approval_links).slice(0, 3).map((al: any, i: number) => (
                      <p key={i} className="text-[11px] text-slate-500">• {al.approval} — {al.authority} <Badge tone="amber">{String(al.verification_status).replace(/_/g, " ")}</Badge></p>
                    ))}
                  </div>
                ) : null}
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  <a href={s.official_channel} target="_blank" rel="noopener noreferrer"><Button size="sm" variant="outline">Apply on official portal ↗</Button></a>
                  <Button size="sm" variant="ghost" onClick={() => navigate(`/projects/${projectId}/applications`)}>Track status (self-reported) →</Button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      <PaymentProtection projectId={String(projectId)} />

      {/* smart action guide */}
      <Card>
        <CardHeader title="Smart Action Guide" subtitle="Generated dynamically from your project profile and regulatory state." />
        <div className="space-y-1.5 p-4">
          {guide.map((g: any) => (
            <button key={g.step} onClick={() => g.link && navigate(g.link.replace("{pid}", String(projectId)))}
              className="flex w-full items-start gap-3 rounded-xl border border-white/8 bg-white/4 px-3.5 py-2.5 text-left transition-colors hover:border-brand-400/40">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-500/25 text-[11px] font-bold text-brand-200">{g.step}</span>
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium text-slate-100">{g.action}</div>
                <div className="mt-0.5 text-[11.5px] text-slate-500">{g.why}</div>
              </div>
              <span className="mt-1 text-slate-600">›</span>
            </button>
          ))}
        </div>
      </Card>

      {/* law versions */}
      <Card>
        <CardHeader title="Law version control (§7 classification)" subtitle={`Applying version ${data.law_versions?.current_applied} — classification thresholds are amendment-driven and versioned.`} />
        <div className="space-y-1.5 p-4">
          <Disclaimer tone="amber">{data.law_versions?.warning}</Disclaimer>
          {(data.law_versions?.versions || []).map((v: any) => (
            <div key={v.version} className="rounded-lg border border-white/8 bg-white/4 px-3 py-2 text-[12px]">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-slate-400">{v.version}</span>
                <Badge tone={v.status === "PENDING_VERIFICATION" ? "amber" : "slate"}>{v.status.replace(/_/g, " ")}</Badge>
                <span className="text-slate-500">effective {v.effective_date}</span>
                <a href={v.source} target="_blank" rel="noopener noreferrer" className="text-[11px] text-brand-300 hover:underline">source ↗</a>
              </div>
              <p className="mt-0.5 text-slate-400">{v.amendment}</p>
              <p className="text-[11px] text-slate-500">{v.status_note}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
