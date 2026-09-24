/** Guided onboarding (spec §3 "Let's understand your business", §4, §5, §49):
 * create project → basics → industry → location → investment → dynamic
 * characteristics → AI analysis → approval map → document checklist. */
import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { useI18n } from "../lib/i18n";
import { Badge, Button, Card, Disclaimer, Field, Input, Progress, Select, SourceBadge, Spinner, StatusBadge, Textarea } from "../components/ui";

const STEPS = ["Business", "Project & industry", "Location", "Investment", "Characteristics", "Review & analyse"];

export default function Onboarding() {
  const [step, setStep] = useState(0);
  const [projects, setProjects] = useState<any[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [industries, setIndustries] = useState<any[]>([]);
  const [states, setStates] = useState<any[]>([]);
  const [questions, setQuestions] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [analysis, setAnalysis] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const { refreshProjects, setActiveProjectId, prefs } = useApp();
  const { t, lang } = useI18n();
  const navigate = useNavigate();

  const [p, setP] = useState<any>({
    name: "",
    description: "",
    organization_name: "",
    organization_type: "PRIVATE_LIMITED",
    industry_code: "",
    industry_other_description: "",
    project_type: "NEW",
    state_code: "TN",
    district: "",
    city_village: "",
    land_tenure: "",
    total_investment: "",
    employment_generated: "",
    number_of_employees: "",
    production_type: "",
  });
  const set = (k: string) => (e: any) => setP({ ...p, [k]: e.target.value });
  const easy = prefs?.easy_mode;

  useEffect(() => {
    api("/projects").then((r) => setProjects(r.projects)).catch(() => {});
    api("/meta/industries").then((r) => setIndustries(r.industries)).catch(() => {});
    api("/meta/states").then((r) => setStates(r.states)).catch(() => {});
  }, []);

  const createProject = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api<any>("/projects", "POST", { name: p.name, description: p.description }, { offlineWrite: false });
      setProjectId(r.project.id);
      setActiveProjectId(r.project.id);
      await api(`/projects/${r.project.id}/profile`, "PATCH", {
        organization_name: p.organization_name || undefined,
        organization_type: p.organization_type,
      });
      await refreshProjects();
      setStep(1);
    } catch (e: any) {
      setError(e?.message || "Could not create the project.");
    } finally {
      setBusy(false);
    }
  };

  const saveProfile = async (extra: Record<string, any> = {}) => {
    if (!projectId) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/projects/${projectId}/profile`, "PATCH", { ...p, ...extra });
      setStep((s) => s + 1);
    } catch (e: any) {
      setError(e?.message || "Could not save.");
    } finally {
      setBusy(false);
    }
  };

  const loadQuestionnaire = async () => {
    if (!projectId) return setStep(5);
    setBusy(true);
    try {
      const q = await api<any>(`/projects/${projectId}/questionnaire`);
      setQuestions(q.questions || []);
      setStep(4);
    } finally {
      setBusy(false);
    }
  };

  const answerQuestion = async () => {
    if (!projectId) return setStep(5);
    const answers = questions
      .filter((q) => q.value !== undefined && q.value !== "" && q.value !== null)
      .map((q) => ({ key: q.key, value: q.value, question_set: q.question_set, field: q.field, why_asked: q.why }));
    setBusy(true);
    try {
      if (answers.length) await api(`/projects/${projectId}/questionnaire`, "POST", { answers });
      setStep(5);
    } finally {
      setBusy(false);
    }
  };

  const runAnalysis = async () => {
    setBusy(true);
    setError(null);
    try {
      const a = await api<any>(`/projects/${projectId}/analysis`, "POST", {});
      setAnalysis(a);
      await refreshProjects();
    } catch (e: any) {
      setError(e?.message || "Analysis failed — check the industry is set.");
    } finally {
      setBusy(false);
    }
  };

  const industry = industries.find((i) => i.code === p.industry_code);
  const canNext = useMemo(() => {
    if (step === 0) return p.name.trim().length >= 2;
    if (step === 1) return !!p.industry_code && (p.industry_code !== "other" || (p.industry_other_description || "").length > 10);
    if (step === 2) return !!p.state_code;
    return true;
  }, [step, p]);

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-5 text-center">
        <h1 className="text-xl font-bold text-white">{easy ? t("easy.welcome") : "Let's set up your project"}</h1>
        <p className="mt-1 text-[13px] text-slate-500">Answer only what matters — questions adapt to your industry.</p>
      </div>

      {/* stepper */}
      <div className="mb-6">
        <Progress value={(step / (STEPS.length - 1)) * 100} label="Onboarding progress" />
        <div className="mt-2 flex justify-between text-[10.5px] text-slate-500">
          {STEPS.map((s, i) => (
            <span key={s} className={i <= step ? "font-semibold text-brand-300" : ""}>{s}</span>
          ))}
        </div>
      </div>

      <Card className="p-6">
        {/* STEP 0 — business */}
        {step === 0 ? (
          <div className="space-y-4">
            <h2 className="text-[15px] font-semibold text-slate-100">First, the basics</h2>
            <Field label="Project name" required hint="e.g. “Solar lantern assembly — Coimbatore”. One NIECP-AI account can hold many projects.">
              <Input value={p.name} onChange={set("name")} placeholder="Name this project" autoFocus />
            </Field>
            <Field label="Organization / business name">
              <Input value={p.organization_name} onChange={set("organization_name")} placeholder="Registered name (can add later)" />
            </Field>
            <Field label="What do you want to build or run? (optional)">
              <Textarea value={p.description} onChange={set("description")} placeholder="A sentence or two — helps the AI pick the right questions" />
            </Field>
            {projects.length > 0 ? (
              <Disclaimer tone="blue">
                You already have {projects.length} project(s). This creates a new, separate one.
              </Disclaimer>
            ) : null}
            {error ? <Disclaimer tone="amber">{error}</Disclaimer> : null}
            <div className="flex justify-end">
              <Button size="lg" disabled={!canNext || busy} onClick={createProject}>{t("action.next")} →</Button>
            </div>
          </div>
        ) : null}

        {/* STEP 1 — industry */}
        {step === 1 ? (
          <div className="space-y-4">
            <h2 className="text-[15px] font-semibold text-slate-100">What industry is this project in?</h2>
            <div className="grid max-h-72 grid-cols-2 gap-2 overflow-y-auto pr-1 md:grid-cols-3">
              {industries.map((i) => (
                <button
                  key={i.code}
                  onClick={() => setP({ ...p, industry_code: i.code })}
                  className={`rounded-xl border p-3 text-left text-[12.5px] font-medium transition-colors ${
                    p.industry_code === i.code ? "border-brand-400 bg-brand-500/15 text-brand-200" : "border-white/10 bg-white/4 text-slate-300 hover:border-white/25"
                  }`}
                >
                  {i.name}
                </button>
              ))}
            </div>
            {p.industry_code === "other" ? (
              <Field label="Describe your industry" required hint="NIECP-AI derives which extra questions to ask from your description.">
                <Textarea value={p.industry_other_description} onChange={set("industry_other_description")} placeholder="e.g. We repair and recondition marine diesel engines" />
              </Field>
            ) : null}
            {industry ? (
              <div className="text-[12px] text-slate-500">
                Will ask about: {(industry.question_sets || []).slice(0, 8).join(", ")} — irrelevant questions are skipped.
              </div>
            ) : null}
            <Field label="Project type">
              <Select value={p.project_type} onChange={set("project_type")}>
                <option value="NEW">New</option>
                <option value="EXPANSION">Expansion</option>
                <option value="MODIFICATION">Modification</option>
                <option value="RELOCATION">Relocation</option>
              </Select>
            </Field>
            {error ? <Disclaimer tone="amber">{error}</Disclaimer> : null}
            <div className="flex justify-between">
              <Button variant="ghost" onClick={() => setStep(0)}>← {t("action.back")}</Button>
              <Button size="lg" disabled={!canNext || busy} onClick={() => saveProfile()}>{t("action.next")} →</Button>
            </div>
          </div>
        ) : null}

        {/* STEP 2 — location */}
        {step === 2 ? (
          <div className="space-y-4">
            <h2 className="text-[15px] font-semibold text-slate-100">Where is the project located?</h2>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="State" required>
                <Select value={p.state_code} onChange={set("state_code")}>
                  {states.map((s: any) => <option key={s.code} value={s.code}>{s.name}</option>)}
                </Select>
              </Field>
              <Field label="District"><Input value={p.district} onChange={set("district")} placeholder="District" /></Field>
              <Field label="City / town / village"><Input value={p.city_village} onChange={set("city_village")} /></Field>
              <Field label="Land tenure">
                <Select value={p.land_tenure} onChange={set("land_tenure")}>
                  <option value="">Select…</option>
                  <option value="OWNED">Owned</option>
                  <option value="LEASED_PRIVATE">Leased (private)</option>
                  <option value="LEASED_GOVERNMENT">Leased (government)</option>
                  <option value="INDUSTRIAL_PARK_ALLOTMENT">Industrial park allotment</option>
                  <option value="SEZ">SEZ</option>
                  <option value="PENDING">Not finalized yet</option>
                </Select>
              </Field>
            </div>
            <Disclaimer tone="blue">Location decides which state authorities and portals apply — it's the highest-impact fact in your profile.</Disclaimer>
            <div className="flex justify-between">
              <Button variant="ghost" onClick={() => setStep(1)}>← {t("action.back")}</Button>
              <Button size="lg" disabled={!canNext || busy} onClick={() => saveProfile()}>{t("action.next")} →</Button>
            </div>
          </div>
        ) : null}

        {/* STEP 3 — investment */}
        {step === 3 ? (
          <div className="space-y-4">
            <h2 className="text-[15px] font-semibold text-slate-100">Scale of the project</h2>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Total investment (₹)" hint="Approximate is fine — thresholds like environmental clearance depend on it.">
                <Input type="number" value={p.total_investment} onChange={set("total_investment")} placeholder="e.g. 12000000" />
              </Field>
              <Field label="Expected employment (people)">
                <Input type="number" value={p.employment_generated} onChange={set("employment_generated")} />
              </Field>
              <Field label="Employees at the unit">
                <Input type="number" value={p.number_of_employees} onChange={set("number_of_employees")} />
              </Field>
              <Field label="What will it produce / do?">
                <Input value={p.production_type} onChange={set("production_type")} placeholder="e.g. LED bulb assembly" />
              </Field>
            </div>
            <div className="flex justify-between">
              <Button variant="ghost" onClick={() => setStep(2)}>← {t("action.back")}</Button>
              <Button size="lg" disabled={busy} onClick={() => saveProfile()}>{t("action.next")} →</Button>
            </div>
          </div>
        ) : null}

        {/* STEP 4 — dynamic questions */}
        {step === 4 ? (
          <div className="space-y-4">
            <h2 className="text-[15px] font-semibold text-slate-100">A few industry-specific questions</h2>
            <p className="text-[12px] text-slate-500">These are selected because they change which approvals may apply. Skip anything you're not sure about.</p>
            <div className="max-h-80 space-y-3 overflow-y-auto pr-1">
              {questions.map((q) => (
                <div key={q.key} className="rounded-xl border border-white/10 bg-white/4 p-3.5">
                  <Field label={q.label} hint={q.why}>
                    {q.type === "boolean" ? (
                      <div className="flex gap-2">
                        <Button size="sm" variant={q.value === true ? "primary" : "subtle"} onClick={() => setQuestions((qs) => qs.map((x) => x.key === q.key ? { ...x, value: true } : x))}>Yes</Button>
                        <Button size="sm" variant={q.value === false ? "primary" : "subtle"} onClick={() => setQuestions((qs) => qs.map((x) => x.key === q.key ? { ...x, value: false } : x))}>No</Button>
                      </div>
                    ) : q.type === "select" ? (
                      <Select value={q.value ?? ""} onChange={(e) => setQuestions((qs) => qs.map((x) => x.key === q.key ? { ...x, value: e.target.value } : x))}>
                        <option value="">Select…</option>
                        {(q.options || []).map((o: string) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
                      </Select>
                    ) : (
                      <Input type={q.type === "number" ? "number" : "text"} value={q.value ?? ""} onChange={(e) => setQuestions((qs) => qs.map((x) => x.key === q.key ? { ...x, value: e.target.value } : x))} />
                    )}
                  </Field>
                </div>
              ))}
              {questions.length === 0 ? <p className="text-[13px] text-slate-400">No extra questions needed for this project right now.</p> : null}
            </div>
            <div className="flex justify-between">
              <Button variant="ghost" onClick={() => setStep(3)}>← {t("action.back")}</Button>
              <Button size="lg" disabled={busy} onClick={answerQuestion}>Save & review →</Button>
            </div>
          </div>
        ) : null}

        {/* STEP 5 — review & analyse */}
        {step === 5 ? (
          <div className="space-y-5">
            {!analysis ? (
              <>
                <h2 className="text-[15px] font-semibold text-slate-100">Ready for the AI analysis</h2>
                <p className="text-[13.5px] leading-relaxed text-slate-400">
                  The deterministic rule engine will evaluate your project profile against a curated catalogue of Indian
                  industrial approvals — every result shows <em>why</em> it applies, the matched facts, the authority and the
                  official portal.
                </p>
                <Disclaimer tone="violet">
                  Results are planning-level indications, not legal determinations. Each card links to the official portal for confirmation.
                </Disclaimer>
                {error ? <Disclaimer tone="amber">{error}</Disclaimer> : null}
                <div className="flex justify-between">
                  <Button variant="ghost" onClick={() => setStep(4)}>← {t("action.back")}</Button>
                  <Button size="lg" disabled={busy} onClick={runAnalysis}>
                    {busy ? <Spinner /> : "⚡"} Run AI analysis
                  </Button>
                </div>
              </>
            ) : (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-[15px] font-semibold text-slate-100">Analysis complete</h2>
                  <Badge tone="green">{analysis.summary.applies} apply</Badge>
                </div>
                <p className="text-[12.5px] text-slate-500">
                  {analysis.summary.applies} approvals likely apply · {analysis.summary.conditional} need more information · {analysis.summary.not_applicable} evaluated as not applicable to your project.
                </p>
                <div className="max-h-80 space-y-2 overflow-y-auto pr-1">
                  {analysis.approvals.slice(0, 12).map((a: any) => (
                    <div key={a.template_code} className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/4 px-3.5 py-2.5">
                      <div className="min-w-0">
                        <div className="truncate text-[13px] font-medium text-slate-200">{a.name}</div>
                        <div className="truncate text-[11px] text-slate-500">{a.authority}</div>
                      </div>
                      <SourceBadge status={a.source_status} />
                    </div>
                  ))}
                </div>
                <Disclaimer tone="amber">{analysis.disclaimer}</Disclaimer>
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => navigate(`/projects/${projectId}/approvals`)}>Open approvals map</Button>
                  <Button size="lg" onClick={() => navigate("/dashboard")}>Go to dashboard →</Button>
                </div>
              </div>
            )}
          </div>
        ) : null}
      </Card>
    </div>
  );
}
