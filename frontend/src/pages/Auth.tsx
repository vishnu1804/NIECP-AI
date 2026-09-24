/** Auth pages (spec §3): login, register, forgot, reset. */
import React, { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { login, useApp } from "../lib/store";
import { api, setTokens } from "../lib/api";
import { Button, Card, Disclaimer, Field, Input } from "../components/ui";
import { useI18n } from "../lib/i18n";

function Shell({ title, children, footer }: { title: string; children: React.ReactNode; footer?: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-ink-950 px-4 py-10 text-slate-200">
      <div className="w-full max-w-md">
        <Link to="/" className="mb-6 flex items-center justify-center gap-2.5">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-teal-glow">
            <svg viewBox="0 0 24 24" className="h-5 w-5 text-white" fill="currentColor"><path d="M12 2l2.4 4.8L20 8l-4 3.9.9 5.6L12 14.9 7.1 17.5 8 11.9 4 8l5.6-1.2z"/></svg>
          </div>
          <span className="text-lg font-bold text-white">NIECP<span className="text-teal-glow">-AI</span></span>
        </Link>
        <Card className="p-6">
          <h1 className="mb-4 text-lg font-bold text-white">{title}</h1>
          {children}
        </Card>
        {footer ? <div className="mt-4 text-center text-[13px] text-slate-500">{footer}</div> : null}
      </div>
    </div>
  );
}

export function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const { refreshUser } = useApp();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await login(email, password);
      await refreshUser();
      const me = await api<any>("/auth/me");
      navigate(me.user.onboarding_completed ? "/dashboard" : "/onboarding");
    } catch (e: any) {
      setErr(e?.message || "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Shell
      title="Welcome back"
      footer={<>New here? <Link to="/register" className="text-brand-300 hover:underline">Create an account</Link></>}
    >
      <form onSubmit={submit} className="space-y-4">
        <Field label="Email" required>
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required placeholder="you@company.in" />
        </Field>
        <Field label="Password" required>
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </Field>
        {err ? <Disclaimer tone="amber">{err}</Disclaimer> : null}
        <Button type="submit" size="lg" className="w-full" disabled={busy}>Sign in</Button>
        <div className="text-center">
          <Link to="/forgot-password" className="text-xs text-slate-500 hover:text-brand-300">Forgot password?</Link>
        </div>
      </form>
      <div className="mt-5 rounded-xl bg-white/4 p-3 text-[11.5px] leading-relaxed text-slate-500">
        <span className="font-semibold text-slate-400">Demo account:</span> demo@niecp.local / Demo!Demo!123 — a fully labelled
        demo project with DEMO-marked sample data.
      </div>
    </Shell>
  );
}

export function Register() {
  const [form, setForm] = useState({ full_name: "", email: "", password: "", organization_name: "", phone: "" });
  const [verification, setVerification] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const { refreshUser } = useApp();
  const set = (k: string) => (e: any) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await api<any>("/auth/register", "POST", form);
      setTokens(r.access_token, r.refresh_token);
      await refreshUser();
      if (r.email_verification?.token && r.email_delivery?.smtp_configured === false) {
        setVerification(r.email_verification.token);
      } else {
        navigate("/onboarding");
      }
    } catch (e: any) {
      setErr(e?.message || "Registration failed.");
    } finally {
      setBusy(false);
    }
  };

  if (verification) {
    return (
      <Shell title="Almost there — verify your email">
        <div className="space-y-4">
          <Disclaimer tone="blue">
            Email delivery is not configured in this deployment, so your verification link is shown here instead of being emailed. In production this token is only ever sent by email.
          </Disclaimer>
          <Field label="Verification token">
            <Input readOnly value={verification} className="font-mono text-xs" />
          </Field>
          <Button className="w-full" onClick={async () => {
            await api("/auth/verify-email", "POST", { email: form.email, token: verification });
            navigate("/onboarding");
          }}>Verify & continue</Button>
          <button className="w-full text-center text-xs text-slate-500 hover:text-brand-300" onClick={() => navigate("/onboarding")}>
            Skip for now (verification stays pending)
          </button>
        </div>
      </Shell>
    );
  }

  return (
    <Shell
      title="Create your account"
      footer={<>Already registered? <Link to="/login" className="text-brand-300 hover:underline">Sign in</Link></>}
    >
      <form onSubmit={submit} className="space-y-4">
        <Field label="Full name" required>
          <Input value={form.full_name} onChange={set("full_name")} required placeholder="Your name" />
        </Field>
        <Field label="Email" required>
          <Input type="email" value={form.email} onChange={set("email")} required placeholder="you@company.in" autoComplete="email" />
        </Field>
        <Field label="Phone (optional)">
          <Input value={form.phone} onChange={set("phone")} placeholder="+91…" autoComplete="tel" />
        </Field>
        <Field label="Organization / business name (optional)" hint="You can also set this later, or manage multiple projects personally.">
          <Input value={form.organization_name} onChange={set("organization_name")} placeholder="Company / proprietorship name" />
        </Field>
        <Field label="Password" required hint="At least 10 characters with upper & lower case, a number and a symbol.">
          <Input type="password" value={form.password} onChange={set("password")} required autoComplete="new-password" />
        </Field>
        {err ? <Disclaimer tone="amber">{err}</Disclaimer> : null}
        <Button type="submit" size="lg" className="w-full" disabled={busy}>Create account</Button>
        <p className="text-center text-[11px] leading-relaxed text-slate-600">
          By registering you accept that NIECP-AI provides planning assistance only — approvals are granted solely by government authorities.
        </p>
      </form>
    </Shell>
  );
}

export function Forgot() {
  const [email, setEmail] = useState("");
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      setResult(await api<any>("/auth/forgot-password", "POST", { email }));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Shell title="Reset your password" footer={<Link to="/login" className="text-brand-300 hover:underline">Back to sign in</Link>}>
      {!result ? (
        <form onSubmit={submit} className="space-y-4">
          <Field label="Account email" required>
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </Field>
          <Button type="submit" className="w-full" disabled={busy}>Send reset link</Button>
        </form>
      ) : (
        <div className="space-y-4">
          <p className="text-[13.5px] text-slate-300">{result.message}</p>
          {result.reset_token ? (
            <>
              <Disclaimer tone="blue">Email delivery is not configured here. Use this one-time token on the reset screen (valid 2 hours).</Disclaimer>
              <Field label="Reset token">
                <Input readOnly value={result.reset_token} className="font-mono text-xs" />
              </Field>
              <Button className="w-full" onClick={() => (window.location.hash = `/reset-password?email=${encodeURIComponent(email)}&token=${encodeURIComponent(result.reset_token)}`)}>
                Continue to reset
              </Button>
            </>
          ) : null}
        </div>
      )}
    </Shell>
  );
}

export function Reset() {
  const [params] = useSearchParams();
  const [form, setForm] = useState({ email: params.get("email") || "", token: params.get("token") || "", new_password: "" });
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      await api("/auth/reset-password", "POST", form);
      setDone(true);
    } catch (e: any) {
      setErr(e?.message || "Reset failed.");
    }
  };
  if (done) {
    return (
      <Shell title="Password updated">
        <p className="mb-4 text-[13.5px] text-slate-300">Your password has been changed and other sessions were signed out.</p>
        <Link to="/login"><Button className="w-full">Sign in</Button></Link>
      </Shell>
    );
  }
  return (
    <Shell title="Choose a new password">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Email" required><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></Field>
        <Field label="Reset token" required><Input value={form.token} onChange={(e) => setForm({ ...form, token: e.target.value })} required className="font-mono text-xs" /></Field>
        <Field label="New password" required hint="At least 10 characters with upper & lower case, a number and a symbol.">
          <Input type="password" value={form.new_password} onChange={(e) => setForm({ ...form, new_password: e.target.value })} required autoComplete="new-password" />
        </Field>
        {err ? <Disclaimer tone="amber">{err}</Disclaimer> : null}
        <Button type="submit" className="w-full">Update password</Button>
      </form>
    </Shell>
  );
}
