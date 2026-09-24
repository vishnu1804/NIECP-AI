/** Global scheme directory (spec §18). */
import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Badge, Card, Disclaimer, Input, Select, Spinner, StatusBadge } from "../components/ui";

export default function SchemesGlobal() {
  const [data, setData] = useState<any>(null);
  const [q, setQ] = useState("");
  const [level, setLevel] = useState("");
  const [category, setCategory] = useState("");

  const load = async () => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (level) p.set("level", level);
    if (category) p.set("category", category);
    setData(await api<any>(`/schemes?${p}`));
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [q, level, category]);

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div>
        <h1 className="text-xl font-bold text-white">Schemes & incentives</h1>
        <p className="text-[12.5px] text-slate-500">Central and state schemes relevant to industry. For a personalised eligibility comparison, open a project → Schemes.</p>
      </div>

      <Disclaimer tone="violet">Eligibility is always decided by the administering authority. Each entry shows its official source and verification status.</Disclaimer>

      <div className="flex flex-wrap gap-3">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search schemes…" className="max-w-xs" />
        <Select value={level} onChange={(e) => setLevel(e.target.value)} className="max-w-40">
          <option value="">All levels</option>
          <option value="CENTRAL">Central</option>
          <option value="STATE">State</option>
        </Select>
        <Select value={category} onChange={(e) => setCategory(e.target.value)} className="max-w-48">
          <option value="">All categories</option>
          {(data?.categories || []).map((c: any) => <option key={c.code} value={c.code}>{c.name}</option>)}
        </Select>
      </div>

      {!data ? <Spinner /> : (
        <div className="grid gap-3 md:grid-cols-2">
          {data.schemes.map((s: any) => (
            <Card key={s.code} className="p-4">
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-[14px] font-semibold text-slate-100">{s.name}</h3>
                <Badge tone={s.level === "CENTRAL" ? "blue" : "violet"}>{s.level}</Badge>
              </div>
              <div className="mt-0.5 text-[12px] text-slate-500">{s.authority}</div>
              <p className="mt-1.5 line-clamp-2 text-[12.5px] leading-relaxed text-slate-400">{s.short_description}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(s.categories || []).slice(0, 4).map((c: string) => <Badge key={c} tone="slate">{c.replace(/_/g, " ")}</Badge>)}
                <StatusBadge value={s.verification_status} />
              </div>
              {s.official_url ? (
                <a href={s.official_url} target="_blank" rel="noopener noreferrer" className="mt-3 inline-block text-xs font-medium text-brand-300 hover:underline">
                  Official source ↗
                </a>
              ) : null}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
