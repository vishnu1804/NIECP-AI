/** Shared UI kit: cards, badges, progress, modals, fields — accessible and
 * theme-aware. All styles inline/tailwind; no external CSS dependencies. */
import React, { useEffect, useRef } from "react";
import { useI18n } from "../lib/i18n";

export function Card({ children, className = "", onClick }: { children: React.ReactNode; className?: string; onClick?: () => void }) {
  return (
    <div
      onClick={onClick}
      className={`rounded-2xl border border-white/8 bg-ink-850/80 shadow-lg shadow-black/20 backdrop-blur ${onClick ? "cursor-pointer hover:border-brand-500/40 transition-colors" : ""} ${className}`}
    >
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, right }: { title: React.ReactNode; subtitle?: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-white/8 px-5 py-4">
      <div>
        <h3 className="text-[15px] font-semibold text-slate-100">{title}</h3>
        {subtitle ? <p className="mt-0.5 text-xs leading-relaxed text-slate-400">{subtitle}</p> : null}
      </div>
      {right}
    </div>
  );
}

const BADGE_TONES: Record<string, string> = {
  green: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  red: "bg-rose-500/15 text-rose-300 border-rose-500/30",
  amber: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  blue: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  violet: "bg-violet-500/15 text-violet-300 border-violet-500/30",
  slate: "bg-slate-500/15 text-slate-300 border-slate-400/25",
  teal: "bg-teal-500/15 text-teal-300 border-teal-500/30",
};

export function Badge({ children, tone = "slate", className = "", title }: { children: React.ReactNode; tone?: keyof typeof BADGE_TONES; className?: string; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-4 ${BADGE_TONES[tone]} ${className}`}>
      {children}
    </span>
  );
}

const STATE_TONES: Record<string, keyof typeof BADGE_TONES> = {
  COMPLETED: "green", APPROVED: "green", PROCESSED: "green", DONE: "green", RESPONDED: "green", CLOSED: "slate", VERIFIED_GOV_SOURCE: "green",
  READY: "teal", READY_TO_APPLY: "teal",
  SUBMITTED: "blue", UNDER_REVIEW: "blue", IN_PROGRESS: "blue", SCHEDULED: "blue",
  QUERY_RAISED: "amber", WAITING: "amber", DUE_SOON: "amber", OPEN: "amber", UPLOADED: "amber", VALIDATION_REQUIRED: "amber", PENDING: "amber", CONDITIONAL: "amber", NEEDS_MORE_INFO: "amber", PENDING_VERIFICATION: "amber", REQUIRES_VERIFICATION: "amber", PROCESSING: "amber", UPCOMING: "blue",
  BLOCKED: "red", REJECTED: "red", OVERDUE: "red", EXPIRED: "red", FAILED: "red", ERROR: "red", RENEWAL_DUE: "red",
  NOT_APPLICABLE: "slate", NOT_CONNECTED: "slate", NOT_STARTED: "slate", DRAFT: "slate", INFORMATION_UNAVAILABLE: "slate", SKIPPED: "slate",
  USER_PROVIDED: "violet", AI_INTERPRETATION: "violet", OFFICIAL_API: "blue", VERIFIED: "green", DEMO: "violet", MANUAL_MODE: "amber", CONNECTED: "green", API_UNAVAILABLE: "red",
};

export function StatusBadge({ value, label }: { value: string | null | undefined; label?: string }) {
  const { statusLabel } = useI18n();
  if (!value) return <Badge tone="slate">—</Badge>;
  const tone = STATE_TONES[value] || "slate";
  return (
    <Badge tone={tone} title={value}>
      {label || statusLabel(value)}
    </Badge>
  );
}

export function SourceBadge({ status }: { status: string | null | undefined }) {
  const map: Record<string, { tone: keyof typeof BADGE_TONES; label: string }> = {
    VERIFIED_GOV_SOURCE: { tone: "green", label: "Verified government source" },
    OFFICIAL_API: { tone: "blue", label: "Official API" },
    USER_PROVIDED: { tone: "violet", label: "User-provided" },
    AI_INTERPRETATION: { tone: "violet", label: "AI interpretation" },
    REQUIRES_VERIFICATION: { tone: "amber", label: "Requires verification" },
    INFORMATION_UNAVAILABLE: { tone: "slate", label: "Information unavailable" },
    DEMO: { tone: "violet", label: "DEMO" },
  };
  const info = status ? map[status] : null;
  if (!info) return null;
  return <Badge tone={info.tone}>{info.label}</Badge>;
}

export function Progress({ value, tone = "brand", height = "h-2", label }: { value: number; tone?: "brand" | "green" | "amber" | "red"; height?: string; label?: string }) {
  const tones = {
    brand: "bg-gradient-to-r from-brand-500 to-teal-glow",
    green: "bg-emerald-500",
    amber: "bg-amber-500",
    red: "bg-rose-500",
  };
  const v = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div>
      <div className={`w-full overflow-hidden rounded-full bg-white/8 ${height}`} role="progressbar" aria-valuenow={v} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
        <div className={`h-full rounded-full transition-all duration-700 ${tones[tone]}`} style={{ width: `${v}%` }} />
      </div>
    </div>
  );
}

export function Button({
  children,
  variant = "primary",
  size = "md",
  className = "",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "outline" | "danger" | "subtle"; size?: "sm" | "md" | "lg" }) {
  const variants = {
    primary: "bg-brand-500 hover:bg-brand-600 text-white shadow-md shadow-brand-500/25",
    ghost: "text-slate-300 hover:bg-white/8",
    outline: "border border-white/15 text-slate-200 hover:bg-white/8",
    danger: "bg-rose-600 hover:bg-rose-500 text-white",
    subtle: "bg-white/8 text-slate-200 hover:bg-white/12",
  };
  const sizes = { sm: "px-2.5 py-1.5 text-xs", md: "px-4 py-2 text-sm", lg: "px-5 py-2.5 text-[15px]" };
  return (
    <button
      {...rest}
      className={`inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all disabled:cursor-not-allowed disabled:opacity-40 ${variants[variant]} ${sizes[size]} ${className}`}
    >
      {children}
    </button>
  );
}

export function Field({ label, hint, children, required }: { label: string; hint?: string; children: React.ReactNode; required?: boolean }) {
  return (
    <label className="block">
      <span className="mb-1.5 flex items-center gap-1 text-[13px] font-medium text-slate-300">
        {label}
        {required ? <span className="text-rose-400">*</span> : null}
      </span>
      {children}
      {hint ? <span className="mt-1 block text-[11.5px] leading-relaxed text-slate-500">{hint}</span> : null}
    </label>
  );
}

const inputCls =
  "w-full rounded-xl border border-white/12 bg-ink-900/80 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none transition-colors focus:border-brand-400/70 focus:ring-2 focus:ring-brand-500/25";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${inputCls} ${props.className || ""}`} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${inputCls} ${props.className || ""}`} />;
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${inputCls} min-h-[84px] ${props.className || ""}`} />;
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (open) {
      document.addEventListener("keydown", handler);
      ref.current?.focus();
    }
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div ref={ref} tabIndex={-1} className={`relative max-h-[86vh] w-full ${wide ? "max-w-3xl" : "max-w-lg"} overflow-y-auto rounded-2xl border border-white/10 bg-ink-850 p-5 shadow-2xl`}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-100">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10 hover:text-slate-200">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Tabs({ tabs, active, onChange }: { tabs: { key: string; label: string; count?: number }[]; active: string; onChange: (k: string) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.key}
          role="tab"
          aria-selected={active === t.key}
          onClick={() => onChange(t.key)}
          className={`rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors ${
            active === t.key ? "bg-brand-500/25 text-brand-300 ring-1 ring-brand-400/40" : "text-slate-400 hover:bg-white/8 hover:text-slate-200"
          }`}
        >
          {t.label}
          {typeof t.count === "number" ? <span className="ml-1.5 rounded-full bg-white/10 px-1.5 py-0.5 text-[10px]">{t.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function EmptyState({ icon = "🗂️", title, hint, action }: { icon?: string; title: string; hint?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-white/12 px-6 py-12 text-center">
      <div className="text-3xl" aria-hidden>{icon}</div>
      <p className="text-sm font-medium text-slate-200">{title}</p>
      {hint ? <p className="max-w-md text-xs leading-relaxed text-slate-500">{hint}</p> : null}
      {action}
    </div>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/25 border-t-brand-300 ${className}`} role="status" aria-label="Loading" />
  );
}

export function Disclaimer({ children, tone = "amber" }: { children: React.ReactNode; tone?: "amber" | "violet" | "blue" }) {
  const tones = {
    amber: "border-amber-500/30 bg-amber-500/8 text-amber-200/90",
    violet: "border-violet-500/30 bg-violet-500/8 text-violet-200/90",
    blue: "border-sky-500/30 bg-sky-500/8 text-sky-200/90",
  };
  return (
    <div className={`flex items-start gap-2 rounded-xl border px-3.5 py-2.5 text-[12.5px] leading-relaxed ${tones[tone]}`}>
      <span aria-hidden className="mt-0.5">{tone === "amber" ? "⚠️" : tone === "violet" ? "🤖" : "ℹ️"}</span>
      <div>{children}</div>
    </div>
  );
}

export function ProvenanceRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-white/6 py-1.5 last:border-0">
      <span className="shrink-0 text-xs text-slate-500">{label}</span>
      <span className="text-right text-[13px] text-slate-200">{value}</span>
    </div>
  );
}

export function confidenceLabel(c: string | null | undefined): { tone: keyof typeof BADGE_TONES; label: string } {
  const map: Record<string, { tone: keyof typeof BADGE_TONES; label: string }> = {
    HIGH: { tone: "green", label: "High confidence" },
    MEDIUM: { tone: "blue", label: "Medium confidence" },
    LOW: { tone: "amber", label: "Low confidence" },
    REQUIRES_VERIFICATION: { tone: "amber", label: "Requires verification" },
    UNKNOWN: { tone: "slate", label: "Unknown" },
  };
  return (c && map[c]) || { tone: "slate", label: "Unknown" };
}
