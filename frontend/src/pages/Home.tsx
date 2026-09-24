/** Landing page (spec §48). */
import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { useApp } from "../lib/store";
import { useI18n } from "../lib/i18n";
import { Badge } from "../components/ui";

const FLOW = [
  { icon: "🏢", label: "Project" },
  { icon: "🧠", label: "AI Analysis" },
  { icon: "🗂️", label: "Approvals" },
  { icon: "📄", label: "Documents" },
  { icon: "📮", label: "Application" },
  { icon: "🛰️", label: "Tracking" },
  { icon: "✅", label: "Compliance" },
];

const FEATURES = [
  { icon: "🎙️", title: "AI Assistant (voice-first)", text: "Ask in English, Tamil or Hindi — by voice or text. Answers come from a deterministic rule engine and verified sources, with confidence and provenance shown." },
  { icon: "🏛️", title: "Government sources", text: "Every requirement carries its legal basis, the administering authority, the official portal and a verification status. Verified facts, AI interpretation and user data are always distinguished." },
  { icon: "📄", title: "Document intelligence", text: "Upload once — NIECP-AI classifies, extracts key fields, compares with your project profile and flags mismatches, expiries and low-quality scans before an authority does." },
  { icon: "🕸️", title: "Approval graph", text: "See the whole approval journey as a dependency graph: what is ready, what is blocked, and the critical path from business registration to ongoing compliance." },
  { icon: "📅", title: "Compliance calendar", text: "Renewals, expiries, inspections, filing deadlines and government queries in one calendar with configurable 90/60/30/7-day reminders." },
  { icon: "🌐", title: "Official portal directory", text: "A verified directory of central and state portals. When an integration is unavailable, NIECP-AI says so and opens the official portal — it never fakes connectivity." },
];

export default function Home() {
  const { user } = useApp();
  const { t } = useI18n();
  const navigate = useNavigate();
  return (
    <div className="min-h-screen bg-ink-950 text-slate-200">
      <div className="pointer-events-none fixed inset-x-0 top-0 z-40 h-0.5 bg-gradient-to-r from-brand-500 via-teal-glow to-brand-500" />
      {/* nav */}
      <header className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-teal-glow">
            <svg viewBox="0 0 24 24" className="h-5 w-5 text-white" fill="currentColor"><path d="M12 2l2.4 4.8L20 8l-4 3.9.9 5.6L12 14.9 7.1 17.5 8 11.9 4 8l5.6-1.2z"/></svg>
          </div>
          <div>
            <div className="text-[15px] font-bold text-white">NIECP<span className="text-teal-glow">-AI</span></div>
          </div>
        </div>
        <nav className="flex items-center gap-2 text-sm">
          {user ? (
            <Link to="/dashboard" className="rounded-xl bg-brand-500 px-4 py-2 font-medium text-white hover:bg-brand-600">Open dashboard</Link>
          ) : (
            <>
              <Link to="/login" className="rounded-xl px-4 py-2 text-slate-300 hover:bg-white/8">Sign in</Link>
              <Link to="/register" className="rounded-xl bg-brand-500 px-4 py-2 font-medium text-white hover:bg-brand-600">Get started</Link>
            </>
          )}
        </nav>
      </header>

      {/* hero */}
      <section className="relative mx-auto max-w-6xl px-5 pb-16 pt-14 text-center">
        <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,rgba(37,99,235,0.16),transparent_55%)]" />
        <Badge tone="teal" className="mb-5">Never fabricates · Always shows its sources</Badge>
        <h1 className="mx-auto max-w-3xl text-4xl font-extrabold tracking-tight text-white md:text-5xl">{t("home.hero")}</h1>
        <p className="mx-auto mt-5 max-w-2xl text-[15px] leading-relaxed text-slate-400">{t("home.sub")}</p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Link to={user ? "/projects?new=1" : "/register"} className="rounded-xl bg-brand-500 px-6 py-3 text-[15px] font-semibold text-white shadow-lg shadow-brand-500/30 transition hover:bg-brand-600">
            START PROJECT →
          </Link>
          <Link to={user ? "/dashboard" : "/login"} className="rounded-xl border border-white/15 px-6 py-3 text-[15px] font-semibold text-slate-200 transition hover:bg-white/8">
            EXPLORE PLATFORM
          </Link>
        </div>

        {/* flow visual */}
        <div className="mt-14 flex flex-wrap items-center justify-center gap-2" aria-label="How it works">
          {FLOW.map((f, i) => (
            <React.Fragment key={f.label}>
              <div className="flex flex-col items-center gap-1.5 rounded-2xl border border-white/10 bg-ink-850/70 px-4 py-3">
                <span className="text-2xl" aria-hidden>{f.icon}</span>
                <span className="text-[11.5px] font-medium text-slate-300">{f.label}</span>
              </div>
              {i < FLOW.length - 1 ? <span className="text-slate-600" aria-hidden>→</span> : null}
            </React.Fragment>
          ))}
        </div>
      </section>

      {/* features */}
      <section className="mx-auto max-w-6xl px-5 pb-20">
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-2xl border border-white/8 bg-ink-850/60 p-5">
              <div className="text-2xl" aria-hidden>{f.icon}</div>
              <h3 className="mt-2 text-[15px] font-semibold text-slate-100">{f.title}</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">{f.text}</p>
            </div>
          ))}
        </div>
      </section>

      {/* honesty charter */}
      <section className="mx-auto max-w-4xl px-5 pb-20">
        <div className="rounded-3xl border border-teal-glow/20 bg-gradient-to-b from-teal-glow/6 to-transparent p-7 text-center">
          <h2 className="text-xl font-bold text-white">What NIECP-AI will never do</h2>
          <div className="mt-5 grid gap-2.5 text-left text-[13.5px] text-slate-300 md:grid-cols-2">
            {[
              "Fake government API connectivity or submission",
              "Invent application numbers, statuses or approvals",
              "Promise or guarantee that an approval will be granted",
              "Invent legal requirements not grounded in a source",
              "Submit anything to a government body without your explicit confirmation",
              "Hide whether information is verified, AI-generated, or user-entered",
            ].map((item) => (
              <div key={item} className="flex items-start gap-2 rounded-xl border border-white/8 bg-ink-900/60 px-3.5 py-2.5">
                <span className="mt-0.5 text-rose-400" aria-hidden>✕</span> {item}
              </div>
            ))}
          </div>
          <p className="mt-5 text-[12.5px] leading-relaxed text-slate-500">
            NIECP-AI is an approval and compliance navigator. It does not replace government authorities. You apply
            through official channels — NIECP-AI makes sure you walk in prepared.
          </p>
        </div>
      </section>

      <footer className="border-t border-white/8 py-8 text-center text-xs text-slate-600">
        NIECP-AI — National Industrial Ease & Compliance Platform · Demonstration build · Government statuses shown inside are user-recorded or demo-labelled
      </footer>
    </div>
  );
}
