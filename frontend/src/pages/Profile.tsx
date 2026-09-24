/** Master Project Profile (spec §4) + dynamic questionnaire (§5). */
import React, { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { Badge, Button, Card, CardHeader, Disclaimer, Field, Input, Select, Spinner, Tabs, Textarea } from "../components/ui";
import { useI18n } from "../lib/i18n";
import GovDataEnrichment from "../components/GovDataEnrichment";

export default function Profile() {
  const { projectId } = useParams();
  const [data, setData] = useState<any>(null);
  const [meta, setMeta] = useState<any>({ industries: [], states: [] });
  const [questionnaire, setQuestionnaire] = useState<any>(null);
  const [tab, setTab] = useState("master");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const easy = useApp().prefs?.easy_mode;

  const load = async () => {
    const [p, m, q] = await Promise.all([
      api<any>(`/projects/${projectId}/profile`),
      api<any>("/meta/industries").catch(() => ({ industries: [] })),
      api<any>(`/projects/${projectId}/questionnaire`).catch(() => null),
      api<any>("/meta/states").then((r) => r).catch(() => ({ states: [] })),
    ]);
    setData(p);
    setMeta({ industries: m.industries, states: [] });
    api("/meta/states").then((r) => setMeta((x: any) => ({ ...x, states: r.states })));
    setQuestionnaire(q);
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [projectId]);

  const set = (k: string) => (e: any) => {
    const value = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setData({ ...data, profile: { ...data.profile, [k]: value } });
  };

  const save = async () => {
    setSaving(true);
    setErr(null);
    try {
      await api(`/projects/${projectId}/profile`, "PATCH", data.profile);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e: any) {
      setErr(e?.message || "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  const saveAnswer = async (key: string, value: any, field: string, qset: string, why?: string) => {
    await api(`/projects/${projectId}/questionnaire`, "POST", { answers: [{ key, value, field, question_set: qset, why_asked: why }] });
    const q = await api<any>(`/projects/${projectId}/questionnaire`);
    setQuestionnaire(q);
  };

  const groups = useMemo(() => {
    if (!data?.profile) return [];
    const p = data.profile;
    return [
      { key: "org", title: "Organization", fields: [
        ["organization_name", "Registered name", "text"], ["applicant_name", "Applicant name", "text"],
        ["contact_email", "Email", "text"], ["contact_phone", "Phone", "text"],
        ["organization_type", "Organization type", "select:INDIVIDUAL,PROPRIETORSHIP,PARTNERSHIP,LLP,PRIVATE_LIMITED,PUBLIC_LIMITED,COOPERATIVE,TRUST_SOCIETY,PSU,OTHER"],
        ["enterprise_class", "Enterprise class", "select:,STARTUP,MICRO,SMALL,MEDIUM,LARGE,UNKNOWN"],
        ["pan", "PAN", "text"], ["gstin", "GSTIN", "text"], ["cin", "CIN", "text"], ["udyam_number", "Udyam number", "text"],
        ["startup_dpiit_number", "DPIIT startup number", "text"],
        ["is_export_oriented", "Export-oriented", "bool"],
      ]},
      { key: "project", title: "Project", fields: [
        ["project_type", "Project type", "select:NEW,EXPANSION,MODIFICATION,RELOCATION,CHANGE_OF_USE"],
        ["industry_code", "Industry", "industry"], ["industry_other_description", "Industry description (for 'Other')", "textarea"],
        ["sub_industry", "Sub-industry", "text"], ["project_stage", "Project stage", "select:IDEA,PLANNING,LAND_IDENTIFIED,APPROVALS_IN_PROGRESS,CONSTRUCTION,PRE_OPERATIONAL,OPERATIONAL,EXPANSION,CLOSURE"],
      ]},
      { key: "location", title: "Location & land", fields: [
        ["state_code", "State", "state"], ["district", "District", "text"], ["city_village", "City / village", "text"],
        ["industrial_area", "Industrial area / park", "text"], ["in_notified_industrial_area", "In notified industrial area", "bool"],
        ["land_tenure", "Land tenure", "select:,OWNED,LEASED_PRIVATE,LEASED_GOVERNMENT,INDUSTRIAL_PARK_ALLOTMENT,SEZ,PENDING"],
        ["land_area_sqm", "Land area (m²)", "number"], ["built_up_area_sqm", "Built-up area (m²)", "number"],
        ["survey_number", "Survey number", "text"], ["zoning_classification", "Zoning", "text"],
        ["is_coastal_regulation_zone", "In CRZ", "bool"], ["is_eco_sensitive_zone", "In eco-sensitive zone", "bool"], ["is_forest_land", "Includes forest land", "bool"],
      ]},
      { key: "investment", title: "Investment & employment", fields: [
        ["total_investment", "Total investment (₹)", "number"], ["land_investment", "Land (₹)", "number"],
        ["building_investment", "Building (₹)", "number"], ["machinery_investment", "Machinery (₹)", "number"],
        ["annual_turnover", "Annual turnover (₹/yr)", "number"],
        ["working_capital", "Working capital (₹)", "number"], ["employment_generated", "Employment generated", "number"],
        ["women_employed", "Women employed", "number"],
      ]},
      { key: "operations", title: "Operations & environment", fields: [
        ["production_type", "Production / activity", "text"], ["production_capacity", "Capacity", "text"],
        ["uses_hazardous_chemicals", "Uses hazardous chemicals", "bool"], ["is_mah_directed", "MAH installation", "bool"],
        ["water_consumption_kld", "Water use (KLD)", "number"], ["wastewater_generated_kld", "Wastewater (KLD)", "number"],
        ["has_etp", "Has ETP", "bool"], ["has_stp", "Has STP", "bool"],
        ["air_emissions_present", "Air emissions present", "bool"],
        ["has_boiler", "Has boiler", "bool"], ["boiler_capacity_tph", "Boiler capacity (TPH)", "number"],
        ["has_dg_set", "Has DG set", "bool"], ["dg_set_kva", "DG set (kVA)", "number"],
        ["fire_risk_level", "Fire risk", "select:,LOW,MEDIUM,HIGH"],
        ["electrical_load_kw", "Electrical load (kW)", "number"], ["htaht_connection_required", "HT connection needed", "bool"],
        ["hazardous_waste_generated", "Hazardous waste", "bool"], ["hazardous_waste_tpa", "Hazardous waste (TPA)", "number"],
        ["e_waste_generated", "E-waste", "bool"], ["plastic_waste_generated", "Plastic waste", "bool"],
        ["battery_waste_generated", "Battery waste", "bool"], ["uses_batteries", "Uses batteries", "bool"],
        ["solid_waste_generated", "Solid waste", "bool"], ["biomedical_waste_generated", "Bio-medical waste", "bool"],
        ["construction_demolition_waste", "C&D waste", "bool"],
      ]},
      { key: "business", title: "Business & labour", fields: [
        ["domestic_sales_annual", "Domestic sales (₹/yr)", "number"], ["export_annual", "Exports (₹/yr)", "number"],
        ["import_annual", "Imports (₹/yr)", "number"], ["number_of_employees", "Employees", "number"],
        ["power_requirement_kw", "Power requirement (kW)", "number"], ["water_requirement_kld", "Water requirement (KLD)", "number"],
        ["workers_on_site", "Workers on site", "number"], ["is_factory_under_factories_act", "Is a factory (Factories Act)", "bool"],
        ["uses_contract_labour", "Uses contract labour", "bool"],
        ["buys_from_msme_suppliers", "Buys from MSME suppliers", "bool"], ["operates_in_shifts", "Operates in shifts", "bool"],
      ]},
    ];
  }, [data]);

  if (!data) return <div className="flex justify-center py-20"><Spinner className="h-6 w-6" /></div>;

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-white">Master Project Profile</h1>
          <p className="text-[12.5px] text-slate-500">Enter information once — every approval, application and AI answer reuses it.</p>
        </div>
        <Button onClick={save} disabled={saving}>{saving ? <Spinner /> : null} {saved ? "Saved ✓" : "Save profile"}</Button>
      </div>

      {err ? <Disclaimer tone="amber">{err}</Disclaimer> : null}
      {saved ? <Disclaimer tone="blue">Profile saved. Re-run the analysis to refresh the approval map with the new facts.</Disclaimer> : null}

      <Tabs
        tabs={[{ key: "master", label: "Profile" }, { key: "questions", label: "Dynamic questions", count: questionnaire?.questions?.length }, { key: "govdata", label: "Gov data" }]}
        active={tab}
        onChange={setTab}
      />

      {tab === "govdata" ? (
        <GovDataEnrichment onChanged={() => { load(); }} />
      ) : tab === "master" ? (
        <div className="space-y-4">
          {groups.map((g) => (
            <Card key={g.key}>
              <CardHeader title={g.title} />
              <div className="grid gap-4 p-5 md:grid-cols-2">
                {g.fields.map(([key, label, type]) => {
                  if (easy && type === "text" && typeof label === "string" && label.length > 40) return null;
                  const opts = typeof type === "string" && type.startsWith("select:") ? type.slice(7).split(",").filter(Boolean) : null;
                  if (type === "bool") {
                    return (
                      <label key={key} className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/4 px-3.5 py-2.5 text-[13px] text-slate-200">
                        <input type="checkbox" checked={!!data.profile[key]} onChange={set(key as string)} className="h-4 w-4 rounded border-white/20 bg-ink-900 accent-brand-500" />
                        {label}
                      </label>
                    );
                  }
                  if (opts) {
                    return (
                      <Field key={key} label={label as string}>
                        <Select value={data.profile[key] || ""} onChange={set(key as string)}>
                          {opts.map((o) => <option key={o} value={o}>{o ? o.replace(/_/g, " ") : "—"}</option>)}
                        </Select>
                      </Field>
                    );
                  }
                  if (type === "industry") {
                    return (
                      <Field key={key} label={label as string}>
                        <Select value={data.profile[key] || ""} onChange={set(key as string)}>
                          <option value="">Select industry…</option>
                          {meta.industries.map((i: any) => <option key={i.code} value={i.code}>{i.name}</option>)}
                        </Select>
                      </Field>
                    );
                  }
                  if (type === "state") {
                    return (
                      <Field key={key} label={label as string}>
                        <Select value={data.profile[key] || ""} onChange={set(key as string)}>
                          <option value="">Select state…</option>
                          {meta.states.map((s: any) => <option key={s.code} value={s.code}>{s.name}</option>)}
                        </Select>
                      </Field>
                    );
                  }
                  if (type === "textarea") {
                    return (
                      <Field key={key} label={label as string}>
                        <Textarea value={data.profile[key] || ""} onChange={set(key as string)} />
                      </Field>
                    );
                  }
                  return (
                    <Field key={key} label={label as string}>
                      <Input type={type === "number" ? "number" : "text"} value={data.profile[key] ?? ""} onChange={set(key as string)} />
                    </Field>
                  );
                })}
              </div>
            </Card>
          ))}
          {data.derived ? (
            <Card>
              <CardHeader title="Derived facts (rule engine inputs)" subtitle="Computed from your profile — shown for transparency." />
              <div className="flex flex-wrap gap-2 p-5">
                <Badge tone={data.derived.is_manufacturing ? "green" : "slate"}>Manufacturing: {String(!!data.derived.is_manufacturing)}</Badge>
                <Badge tone={data.derived.food_related ? "green" : "slate"}>Food-related: {String(!!data.derived.food_related)}</Badge>
                {(data.derived.question_sets || []).map((qs: string) => <Badge key={qs} tone="blue">{qs}</Badge>)}
              </div>
            </Card>
          ) : null}
        </div>
      ) : (
        <div className="space-y-3">
          {(questionnaire?.questions || []).map((q: any) => (
            <Card key={q.key} className="p-4">
              <Field label={q.label} hint={q.why}>
                {q.type === "boolean" ? (
                  <div className="flex gap-2">
                    <Button size="sm" variant={q.value === true ? "primary" : "subtle"} onClick={() => { setDataValue(q, true); saveAnswer(q.key, true, q.field, q.question_set, q.why); }}>Yes</Button>
                    <Button size="sm" variant={q.value === false ? "primary" : "subtle"} onClick={() => { setDataValue(q, false); saveAnswer(q.key, false, q.field, q.question_set, q.why); }}>No</Button>
                  </div>
                ) : q.type === "select" ? (
                  <Select value={q.value ?? ""} onChange={(e) => saveAnswer(q.key, e.target.value, q.field, q.question_set, q.why)}>
                    <option value="">Select…</option>
                    {(q.options || []).map((o: string) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
                  </Select>
                ) : (
                  <Input type={q.type === "number" ? "number" : "text"} value={q.value ?? ""} onBlur={(e) => saveAnswer(q.key, e.target.value, q.field, q.question_set, q.why)} onChange={(e) => setDataValue(q, e.target.value)} />
                )}
              </Field>
            </Card>
          ))}
          {(questionnaire?.questions || []).length === 0 ? (
            <Disclaimer tone="blue">No unanswered questions — your profile covers what the rule engine needs. Re-run the analysis after any profile change.</Disclaimer>
          ) : null}
        </div>
      )}
    </div>
  );

  function setDataValue(q: any, value: any) {
    setQuestionnaire((qs: any) => ({ ...qs, questions: qs.questions.map((x: any) => (x.key === q.key ? { ...x, value } : x)) }));
  }
}
