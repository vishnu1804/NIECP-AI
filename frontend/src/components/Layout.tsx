/** App shell: sidebar navigation, topbar (project selector, notifications,
 * language, theme), offline banner, and the floating voice AI button. */
import React, { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate, useParams } from "react-router-dom";
import { useApp } from "../lib/store";
import { useI18n, LANGUAGES, Lang } from "../lib/i18n";
import { Badge, Button, Progress } from "./ui";
import VoiceHUD from "./VoiceHUD";

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-teal-glow shadow-lg shadow-brand-500/30">
        <svg viewBox="0 0 24 24" className="h-5 w-5 text-white" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
          <path d="M12 2l2.4 4.8L20 8l-4 3.9.9 5.6L12 14.9 7.1 17.5 8 11.9 4 8l5.6-1.2z" />
        </svg>
        <span className="absolute inset-0 animate-pulse-ring rounded-xl border border-brand-400/40" aria-hidden />
      </div>
      <div className="leading-tight">
        <div className="text-[15px] font-bold tracking-tight text-white">
          NIECP<span className="text-teal-glow">-AI</span>
        </div>
        <div className="text-[9.5px] font-medium uppercase tracking-[0.14em] text-slate-500">Industrial Ease & Compliance</div>
      </div>
    </div>
  );
}

function projectIcon(stage?: string | null) {
  switch (stage) {
    case "OPERATIONAL": return "🏭";
    case "CONSTRUCTION": return "🏗️";
    case "APPROVALS_IN_PROGRESS": return "📋";
    case "IDEA": return "💡";
    case "PLANNING": return "🧭";
    default: return "🏢";
  }
}

export default function Layout() {
  const { user, prefs, projects, activeProject, setActiveProjectId, unread, logout, offline, pendingSync } = useApp();
  const { t, lang, setLang } = useI18n();
  const navigate = useNavigate();
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">((localStorage.getItem("niecp.theme") as any) || "dark");

  useEffect(() => {
    document.documentElement.classList.toggle("light", theme === "light");
    localStorage.setItem("niecp.theme", theme);
  }, [theme]);

  const nav = [
    { to: "/dashboard", icon: "🛰️", label: t("nav.dashboard") },
    { to: "/projects", icon: "🏢", label: t("nav.projects") },
    ...(activeProject
      ? [
          { to: `/projects/${activeProject.id}/approvals`, icon: "🗂️", label: t("nav.approvals") },
          { to: `/projects/${activeProject.id}/documents`, icon: "📄", label: t("nav.documents") },
          { to: `/projects/${activeProject.id}/applications`, icon: "📮", label: t("nav.applications") },
          { to: `/projects/${activeProject.id}/msme`, icon: "📊", label: "MSME Intelligence" },
          { to: `/projects/${activeProject.id}/compliance`, icon: "✅", label: t("nav.compliance") },
          { to: `/projects/${activeProject.id}/calendar`, icon: "📅", label: t("nav.calendar") },
          { to: `/projects/${activeProject.id}/queries`, icon: "💬", label: t("nav.queries") },
          { to: `/projects/${activeProject.id}/inspections`, icon: "🔍", label: t("nav.inspections") },
          { to: `/projects/${activeProject.id}/schemes`, icon: "🎁", label: t("nav.schemes") },
        ]
      : []),
    { to: "/government-portals", icon: "🌐", label: t("nav.portals") },
    { to: "/change-radar", icon: "📡", label: t("nav.radar") },
    { to: "/assistant", icon: "🤖", label: t("nav.assistant") },
  ];

  const adminNav = user && ["SYSTEM_ADMIN", "ORGANIZATION_ADMIN"].includes(user.platform_role)
    ? [{ to: "/admin", icon: "⚙️", label: t("nav.admin") }]
    : [];

  return (
    <div className="min-h-screen bg-ink-950 text-slate-200">
      {/* top progress hairline */}
      <div className="pointer-events-none fixed inset-x-0 top-0 z-40 h-0.5 bg-gradient-to-r from-brand-500 via-teal-glow to-brand-500 opacity-70" />

      <div className="mx-auto flex max-w-[1500px]">
        {/* ── sidebar ── */}
        <aside className={`fixed inset-y-0 left-0 z-40 w-[248px] transform border-r border-white/8 bg-ink-900/95 backdrop-blur transition-transform lg:static lg:translate-x-0 ${mobileNav ? "translate-x-0" : "-translate-x-full"}`}>
          <div className="flex h-full flex-col">
            <div className="flex items-center justify-between px-4 py-4">
              <Logo />
              <button className="rounded-lg p-1.5 text-slate-500 hover:bg-white/10 lg:hidden" onClick={() => setMobileNav(false)} aria-label="Close menu">✕</button>
            </div>

            {/* project selector */}
            <div className="px-3 pb-2">
              <label className="mb-1 block px-1 text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">Project</label>
              <select
                value={activeProject?.id ?? ""}
                onChange={(e) => setActiveProjectId(Number(e.target.value))}
                className="w-full truncate rounded-xl border border-white/12 bg-ink-850 px-2.5 py-2 text-[13px] text-slate-200 outline-none focus:border-brand-400/60"
                aria-label="Active project"
              >
                {projects.length === 0 ? <option value="">No projects yet</option> : null}
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {projectIcon(p.stage)} {p.name}
                  </option>
                ))}
              </select>
              {activeProject ? (
                <div className="mt-2 rounded-xl bg-white/4 px-2.5 py-2">
                  <div className="mb-1 flex items-center justify-between text-[10.5px] text-slate-500">
                    <span>Readiness</span>
                    <span className="font-semibold text-teal-glow">{activeProject.readiness_overall ?? "—"}%</span>
                  </div>
                  <Progress value={activeProject.readiness_overall ?? 0} height="h-1.5" label="Project readiness" />
                </div>
              ) : null}
            </div>

            <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-2" aria-label="Primary">
              {nav.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  onClick={() => setMobileNav(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-2.5 rounded-xl px-3 py-2 text-[13.5px] font-medium transition-colors ${
                      isActive ? "bg-brand-500/18 text-brand-300 ring-1 ring-brand-400/30" : "text-slate-400 hover:bg-white/6 hover:text-slate-200"
                    }`
                  }
                >
                  <span aria-hidden className="text-[15px]">{item.icon}</span>
                  {item.label}
                </NavLink>
              ))}
              {adminNav.map((item) => (
                <NavLink key={item.to} to={item.to} className={({ isActive }) => `flex items-center gap-2.5 rounded-xl px-3 py-2 text-[13.5px] font-medium ${isActive ? "bg-violet-500/18 text-violet-300" : "text-slate-400 hover:bg-white/6"}`}>
                  <span aria-hidden>{item.icon}</span> {item.label}
                </NavLink>
              ))}
            </nav>

            <div className="space-y-1 border-t border-white/8 px-3 py-3">
              <NavLink to="/settings" className="flex items-center gap-2.5 rounded-xl px-3 py-2 text-[13.5px] text-slate-400 hover:bg-white/6 hover:text-slate-200">
                <span aria-hidden>⚙️</span> {t("nav.settings")}
              </NavLink>
              {user ? (
                <div className="flex items-center gap-2.5 rounded-xl px-3 py-2">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full text-[13px] font-bold text-white" style={{ background: user.avatar_color || "#2563eb" }}>
                    {user.full_name.slice(0, 1).toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1 leading-tight">
                    <div className="truncate text-[12.5px] font-medium text-slate-200">{user.full_name}</div>
                    <div className="truncate text-[10.5px] text-slate-500">{user.email}</div>
                  </div>
                  <button onClick={async () => { await logout(); navigate("/"); }} className="rounded-lg p-1.5 text-slate-500 hover:bg-white/10 hover:text-rose-300" title="Sign out" aria-label="Sign out">
                    ⏻
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </aside>

        {mobileNav ? <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={() => setMobileNav(false)} /> : null}

        {/* ── main ── */}
        <div className="min-w-0 flex-1">
          <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-white/8 bg-ink-950/85 px-4 py-2.5 backdrop-blur">
            <button className="rounded-lg p-2 text-slate-400 hover:bg-white/10 lg:hidden" onClick={() => setMobileNav(true)} aria-label="Open menu">☰</button>
            <div className="flex-1" />
            {pendingSync > 0 ? <Badge tone="amber">📤 {pendingSync} pending sync</Badge> : null}
            {offline ? <Badge tone="red">Offline</Badge> : null}
            <select
              value={lang}
              onChange={(e) => setLang(e.target.value as Lang)}
              className="rounded-lg border border-white/12 bg-ink-850 px-2 py-1.5 text-xs text-slate-300 outline-none"
              aria-label="Language"
            >
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>{l.native}</option>
              ))}
            </select>
            <button
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              className="rounded-lg border border-white/12 px-2 py-1.5 text-xs text-slate-300 hover:bg-white/8"
              aria-label="Toggle theme"
            >
              {theme === "dark" ? "☀️" : "🌙"}
            </button>
            <NavLink to="/notifications" className="relative rounded-lg border border-white/12 px-2 py-1.5 text-xs hover:bg-white/8" aria-label="Notifications">
              🔔
              {unread > 0 ? <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-500 px-1 text-[9px] font-bold text-white">{unread}</span> : null}
            </NavLink>
            <Button size="sm" variant="subtle" onClick={() => navigate("/projects?new=1")}>+ {t("action.start")}</Button>
          </header>

          {prefs?.easy_mode ? (
            <div className="border-b border-teal-glow/20 bg-teal-glow/8 px-4 py-1.5 text-center text-[12px] font-medium text-teal-200">
              {t("easy.on")} — simple language, large buttons, voice guidance
            </div>
          ) : null}

          <main className="px-4 pb-28 pt-5 lg:px-7">
            <Outlet />
          </main>
        </div>
      </div>

      {/* ── floating AI assistant button (spec §28) ── */}
      {user ? (
        <>
          <button
            onClick={() => setVoiceOpen(true)}
            className="group fixed bottom-6 right-6 z-40 flex items-center gap-2.5 rounded-full border border-brand-400/30 bg-gradient-to-br from-brand-500 via-brand-600 to-teal-glow py-2 pl-2 pr-4 shadow-2xl shadow-brand-500/40 transition-all hover:scale-105 hover:border-brand-300/50 active:scale-95"
            aria-label="Open AI assistant"
            title="AI Assistant — ask about approvals, documents, readiness, next steps"
          >
            <span className="relative flex h-10 w-10 items-center justify-center rounded-full bg-ink-950/40">
              <span className="absolute inset-0 animate-pulse-ring rounded-full border-2 border-brand-300/60" aria-hidden />
              <span className="absolute inset-1 rounded-full bg-gradient-to-br from-cyan-300/70 to-brand-400/70 blur-[2px] transition-all group-hover:blur-[3px]" aria-hidden />
              <svg viewBox="0 0 24 24" className="relative h-5 w-5 text-white" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z" fill="currentColor" stroke="none" />
                <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
              </svg>
            </span>
            <span className="hidden text-left leading-tight sm:block">
              <span className="block text-[12px] font-bold tracking-wide text-white">AI Assistant</span>
              <span className="block text-[9.5px] font-medium uppercase tracking-[0.14em] text-brand-100/80">Ask NIECP</span>
            </span>
          </button>
          <VoiceHUD open={voiceOpen} onClose={() => setVoiceOpen(false)} />
        </>
      ) : null}
    </div>
  );
}
