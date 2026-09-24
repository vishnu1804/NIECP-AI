/**
 * Global ASK NIECP voice assistant (Master Upgrade Prompt §27–§44).
 *
 * One assistant surface for the whole app, mounted from Layout's floating AI
 * button. States: IDLE → ACTIVATING → LISTENING → PROCESSING → RESPONDING →
 * IDLE, plus ERROR / PERMISSION_DENIED / NO_SPEECH / NETWORK_ERROR /
 * UNSUPPORTED — each with distinct visual behavior.
 *
 * Honesty rules implemented here:
 *  - LISTENING visualisation is driven by REAL microphone amplitude
 *    (Web Audio AnalyserNode) and a REAL time-domain waveform — never a
 *    fake continuously-moving waveform.
 *  - RESPONDING visualisation is driven by real TTS speech events
 *    (start/boundary/end). Browser speechSynthesis exposes no audio stream,
 *    so a true AnalyserNode is only possible once a stream-TTS provider is
 *    configured (see speakTTS — the envelope hook is where it plugs in).
 *  - PROCESSING shows only stages that actually happen: transcript received →
 *    project analysis request in flight. No fake progress bars.
 *  - Sensitive actions surface a CONFIRM/CANCEL gate; nothing runs on voice
 *    alone (§28/§48).
 *  - Closing the assistant stops recognition, cancels TTS, stops ALL
 *    microphone tracks and closes the AudioContext (§43).
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "./motion";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { useI18n } from "../lib/i18n";
import { Button } from "./ui";

export type VoiceState =
  | "IDLE" | "ACTIVATING" | "LISTENING" | "PROCESSING" | "RESPONDING"
  | "ERROR" | "PERMISSION_DENIED" | "NO_SPEECH" | "NETWORK_ERROR" | "UNSUPPORTED";

const SR: any = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition || null;

/** Client-side affordances per intent (spec §56) — mirrors the backend map. */
function actionsForIntent(intent: string, projectId: number | null): { label: string; route: string }[] {
  const p = projectId ? String(projectId) : "";
  const table: Record<string, { label: string; route: string }[]> = {
    PENDING_APPROVALS: [{ label: "VIEW APPROVAL CHECKLIST", route: `/projects/${p}/approvals` }],
    MISSING_DOCUMENTS: [{ label: "CHECK DOCUMENTS", route: `/projects/${p}/documents` }],
    CRITICAL_PATH: [{ label: "VIEW CRITICAL PATH", route: `/projects/${p}/approvals` }],
    OPEN_PORTAL: [{ label: "GOVERNMENT PORTALS", route: "/government-portals" }],
    SCHEMES: [{ label: "VIEW SCHEMES", route: `/projects/${p}/schemes` }],
    CALENDAR: [{ label: "VIEW CALENDAR", route: `/projects/${p}/calendar` }],
    QUERIES: [{ label: "VIEW QUERIES", route: `/projects/${p}/queries` }],
    APPLICATIONS: [{ label: "VIEW APPLICATIONS", route: `/projects/${p}/applications` }],
    COMPLIANCE_TASKS: [{ label: "VIEW TODAY'S TASKS", route: `/projects/${p}/compliance` }],
  };
  const base = table[intent] || [];
  const extras = [
    { label: "VIEW APPROVAL CHECKLIST", route: `/projects/${p}/approvals` },
    { label: "CHECK DOCUMENTS", route: `/projects/${p}/documents` },
    { label: "VIEW CRITICAL PATH", route: `/projects/${p}/approvals` },
    { label: "GOVERNMENT PORTALS", route: "/government-portals" },
  ].filter((x) => !base.some((b) => b.label === x.label) && x.route !== `/projects//approvals` && x.route !== `/projects//documents`);
  return [...base, ...extras].slice(0, 5);
}

/* ═══════════════════════════ VoiceReactiveCore (§40) ═══════════════════════ */

interface CoreProps {
  state: VoiceState;
  /** REAL microphone amplitude 0..1 (from AnalyserNode) while LISTENING */
  getMicLevel: () => number;
  /** REAL time-domain samples (or null) while LISTENING */
  getWave: () => Uint8Array | null;
  /** speech-event envelope 0..1 while RESPONDING */
  getTtsLevel: () => number;
}

const _PALETTE: Record<string, [string, string, string]> = {
  IDLE: ["#64748b", "#2563eb", "#22d3ee"],
  ACTIVATING: ["#60a5fa", "#2563eb", "#67e8f9"],
  LISTENING: ["#2dd4bf", "#0d9488", "#99f6e4"],
  PROCESSING: ["#60a5fa", "#4f46e5", "#a5b4fc"],
  RESPONDING: ["#34d399", "#2563eb", "#7dd3fc"],
};

export function VoiceReactiveCore({ state, getMicLevel, getWave, getTtsLevel }: CoreProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    let t = 0;
    let smoothMic = 0;
    let smoothTts = 0;
    // particles: fixed pool, positions in polar coordinates
    const N = 54;
    const parts = Array.from({ length: N }, (_, i) => ({
      a: (i / N) * Math.PI * 2 + Math.random() * 0.4,
      r: 0.62 + Math.random() * 0.34,
      s: 0.0016 + Math.random() * 0.0022,
      z: 0.4 + Math.random() * 0.6,
    }));
    // expanding energy waves triggered by speech activity
    let waves: { r: number; a: number }[] = [];
    let lastWaveAt = 0;

    const draw = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const size = canvas.clientWidth;
      if (canvas.width !== size * dpr) {
        canvas.width = size * dpr;
        canvas.height = size * dpr;
      }
      const w = canvas.width;
      const h = canvas.height;
      const cx = w / 2;
      const cy = h / 2;
      const R = Math.min(w, h) / 2;
      ctx.clearRect(0, 0, w, h);

      const mic = getMicLevel();
      const tts = getTtsLevel();
      smoothMic += (mic - smoothMic) * 0.25;
      smoothTts += (tts - smoothTts) * 0.3;
      const energy = state === "LISTENING" ? smoothMic : state === "RESPONDING" ? smoothTts : 0;
      const busy = state === "PROCESSING" || state === "ACTIVATING";
      const [c1, c2, c3] = _PALETTE[state] || _PALETTE.IDLE;
      const dim = state === "IDLE" || state.startsWith("ERROR") || state === "PERMISSION_DENIED" || state === "UNSUPPORTED" || state === "NETWORK_ERROR" || state === "NO_SPEECH";
      const coreR = R * (0.16 + energy * 0.10 + (busy ? 0.03 * Math.sin(t / 5) : 0) + (dim ? 0 : 0.015 * Math.sin(t / 9)));

      // outer glow
      const glow = ctx.createRadialGradient(cx, cy, coreR * 0.2, cx, cy, R * 0.95);
      glow.addColorStop(0, dim ? "rgba(100,116,139,0.10)" : `${c2}${state === "LISTENING" ? "55" : "44"}`);
      glow.addColorStop(0.55, `${c1}14`);
      glow.addColorStop(1, "rgba(2,6,23,0)");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, w, h);

      // rotating rings
      const ringSpeed = 1 + energy * 3 + (busy ? 1.6 : 0) + (state === "ACTIVATING" ? 2.2 : 0);
      const rings = [
        { rr: 0.94, dash: [Math.PI * 0.32, Math.PI * 0.14], dir: 1, alpha: 0.5 },
        { rr: 0.82, dash: [Math.PI * 0.1, Math.PI * 0.07], dir: -1, alpha: 0.38 },
        { rr: 0.70, dash: [Math.PI * 0.5, Math.PI * 0.5], dir: 1, alpha: 0.22 },
      ];
      rings.forEach((ring, i) => {
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate((ring.dir * t * 0.0045 * ringSpeed) % (Math.PI * 2) + i);
        ctx.beginPath();
        ctx.setLineDash(ring.dash.map((d) => d * R));
        ctx.strokeStyle = dim ? "rgba(148,163,184,0.20)" : `${c3}${Math.round(ring.alpha * 200).toString(16).padStart(2, "0")}`;
        ctx.lineWidth = Math.max(1, R * 0.012);
        ctx.arc(0, 0, R * ring.rr, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      });

      // REAL waveform ring while listening
      const waveData = getWave();
      if (state === "LISTENING" && waveData) {
        ctx.beginPath();
        const base = R * 0.56;
        const n = waveData.length;
        for (let i = 0; i <= n; i++) {
          const v = (waveData[i % n] - 128) / 128; // -1..1 real samples
          const ang = (i / n) * Math.PI * 2 - Math.PI / 2;
          const rr = base + v * R * 0.16;
          const x = cx + Math.cos(ang) * rr;
          const y = cy + Math.sin(ang) * rr;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.strokeStyle = `${c3}cc`;
        ctx.lineWidth = Math.max(1, R * 0.02);
        ctx.stroke();
      }

      // particles orbit; drawn inward during ACTIVATING
      const inward = state === "ACTIVATING" ? 0.24 : 0;
      parts.forEach((p) => {
        p.a += p.s * ringSpeed * (1 + energy * 2);
        const rr = R * (p.r - inward + Math.sin(t / 17 + p.z * 9) * 0.02 - energy * 0.05 * p.z);
        const x = cx + Math.cos(p.a) * rr;
        const y = cy + Math.sin(p.a) * rr;
        ctx.beginPath();
        ctx.arc(x, y, Math.max(0.6, R * 0.011 * p.z * (1 + energy)), 0, Math.PI * 2);
        ctx.fillStyle = dim ? "rgba(148,163,184,0.35)" : `${c1}${Math.round(90 + p.z * 120).toString(16).padStart(2, "0")}`;
        ctx.fill();
      });

      // energy waves on speech activity
      const now = t;
      if (energy > 0.32 && now - lastWaveAt > 16) {
        waves.push({ r: coreR * 1.15, a: 0.5 * Math.min(1, energy * 1.6) });
        lastWaveAt = now;
      }
      waves = waves.filter((wv) => wv.a > 0.02 && wv.r < R);
      waves.forEach((wv) => {
        ctx.beginPath();
        ctx.arc(cx, cy, wv.r, 0, Math.PI * 2);
        ctx.strokeStyle = `${c3}${Math.round(wv.a * 160).toString(16).padStart(2, "0")}`;
        ctx.lineWidth = Math.max(1, R * 0.008);
        ctx.stroke();
        wv.r += R * 0.012;
        wv.a *= 0.965;
      });

      // scanning sweep during ACTIVATING / PROCESSING
      if (busy) {
        const scanY = cy - R * 0.9 + ((t * 2.4) % (R * 1.8));
        const scanGrad = ctx.createLinearGradient(0, scanY - R * 0.06, 0, scanY + R * 0.06);
        scanGrad.addColorStop(0, "rgba(103,232,249,0)");
        scanGrad.addColorStop(0.5, "rgba(103,232,249,0.20)");
        scanGrad.addColorStop(1, "rgba(103,232,249,0)");
        ctx.fillStyle = scanGrad;
        ctx.fillRect(cx - R * 0.8, scanY - R * 0.06, R * 1.6, R * 0.12);
      }

      // central core
      const coreGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR);
      coreGrad.addColorStop(0, dim ? "rgba(148,163,184,0.5)" : `${c3}f2`);
      coreGrad.addColorStop(0.45, `${c1}b0`);
      coreGrad.addColorStop(1, "rgba(2,6,23,0.05)");
      ctx.beginPath();
      ctx.arc(cx, cy, coreR, 0, Math.PI * 2);
      ctx.fillStyle = coreGrad;
      ctx.shadowColor = dim ? "rgba(100,116,139,0.4)" : `${c2}cc`;
      ctx.shadowBlur = R * (0.10 + energy * 0.22);
      ctx.fill();
      ctx.shadowBlur = 0;

      // neural-style spokes while PROCESSING
      if (state === "PROCESSING") {
        for (let i = 0; i < 6; i++) {
          const ang = (i / 6) * Math.PI * 2 + t * 0.02;
          const x1 = cx + Math.cos(ang) * coreR * 1.15;
          const y1 = cy + Math.sin(ang) * coreR * 1.15;
          const x2 = cx + Math.cos(ang) * R * (0.5 + 0.12 * Math.sin(t / 4 + i));
          const y2 = cy + Math.sin(ang) * R * (0.5 + 0.12 * Math.sin(t / 4 + i));
          ctx.beginPath();
          ctx.moveTo(x1, y1);
          ctx.lineTo(x2, y2);
          ctx.strokeStyle = "rgba(165,180,252,0.30)";
          ctx.lineWidth = Math.max(1, R * 0.007);
          ctx.stroke();
          ctx.beginPath();
          ctx.arc(x2, y2, Math.max(1, R * 0.014), 0, Math.PI * 2);
          ctx.fillStyle = "rgba(165,180,252,0.55)";
          ctx.fill();
        }
      }

      t += 1;
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [state, getMicLevel, getWave, getTtsLevel]);

  return <canvas ref={canvasRef} className="h-full w-full" aria-hidden />;
}

/* ═══════════════════════════════ the overlay ═══════════════════════════════ */

export default function VoiceHUD({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { activeProject } = useApp();
  const { lang } = useI18n();
  const navigate = useNavigate();
  const [state, setState] = useState<VoiceState>("IDLE");
  const [transcript, setTranscript] = useState("");
  const [answer, setAnswer] = useState<any>(null);
  const [confirmation, setConfirmation] = useState<any>(null);
  const [muted, setMuted] = useState(false);
  const [showType, setShowType] = useState(false);
  const [typeText, setTypeText] = useState("");
  const [actions, setActions] = useState<{ label: string; route: string }[]>([]);

  // real-mic metering refs
  const analyserRef = useRef<AnalyserNode | null>(null);
  const waveArrayRef = useRef<Uint8Array | null>(null);
  const micLevelRef = useRef(0);
  const ttsLevelRef = useRef(0);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef(0);
  const recognitionRef = useRef<any>(null);
  const closedRef = useRef(false);
  const typeInputRef = useRef<HTMLInputElement>(null);

  const srLang = lang === "ta" ? "ta-IN" : lang === "hi" ? "hi-IN" : "en-IN";

  const getMicLevel = useCallback(() => micLevelRef.current, []);
  const getWave = useCallback(() => (state === "LISTENING" ? waveArrayRef.current : null), [state]);
  const getTtsLevel = useCallback(() => ttsLevelRef.current, []);

  /** §43 — full resource release: recognition, TTS, mic tracks, AudioContext. */
  const stopAudioMeter = useCallback(() => {
    cancelAnimationFrame(rafRef.current);
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    analyserRef.current = null;
    waveArrayRef.current = null;
    micLevelRef.current = 0;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
  }, []);

  const releaseAll = useCallback(() => {
    try { recognitionRef.current?.abort?.(); } catch { /* noop */ }
    recognitionRef.current = null;
    speechSynthesis?.cancel?.();
    stopAudioMeter();
  }, [stopAudioMeter]);

  /** Activation chime (§28) — a short synthesized two-tone, no audio asset. */
  const playActivationSound = useCallback(() => {
    try {
      const ctx = new AudioContext();
      const now = ctx.currentTime;
      [
        { f: 740, at: 0.0 },
        { f: 1108, at: 0.09 },
      ].forEach(({ f, at }) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "sine";
        osc.frequency.value = f;
        gain.gain.setValueAtTime(0.0001, now + at);
        gain.gain.exponentialRampToValueAtTime(0.06, now + at + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + at + 0.22);
        osc.connect(gain).connect(ctx.destination);
        osc.start(now + at);
        osc.stop(now + at + 0.26);
      });
      setTimeout(() => ctx.close().catch(() => {}), 700);
    } catch { /* audio may be blocked — silent fallback */ }
  }, []);

  const speak = useCallback((text: string) => {
    return new Promise<void>((resolve) => {
      if (muted || !("speechSynthesis" in window)) return resolve();
      const clean = text.replace(/[*#•→]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 700);
      const u = new SpeechSynthesisUtterance(clean);
      const voices = speechSynthesis.getVoices();
      const pick =
        voices.find((v) => v.lang?.toLowerCase().startsWith(lang === "ta" ? "ta" : lang === "hi" ? "hi" : "en-in")) ||
        voices.find((v) => v.lang?.toLowerCase().startsWith("en-in")) ||
        voices.find((v) => v.lang?.toLowerCase().startsWith("en"));
      if (pick) u.voice = pick;
      u.rate = 1.02;
      // RESPONDING envelope from REAL speech events (browser TTS exposes no
      // audio stream — a stream-TTS provider would attach an AnalyserNode here)
      ttsLevelRef.current = 0.45;
      let decayTimer: any = null;
      const bump = () => {
        ttsLevelRef.current = 0.55 + Math.random() * 0.35;
        if (decayTimer) clearTimeout(decayTimer);
        decayTimer = setTimeout(() => { ttsLevelRef.current = 0.3; }, 90);
      };
      u.onstart = bump;
      u.onboundary = bump;
      const done = () => {
        if (decayTimer) clearTimeout(decayTimer);
        ttsLevelRef.current = 0;
        resolve();
      };
      u.onend = done;
      u.onerror = done;
      speechSynthesis.speak(u);
    });
  }, [lang, muted]);

  const ask = useCallback(async (text: string) => {
    const clean = text.replace(/[\u0000-\u0008\u000B-\u001F]/g, "").trim();
    if (!clean) return;
    setState("PROCESSING");
    setTranscript(clean);
    setActions([]);
    try {
      const resp = await api<any>("/assistant/chat", "POST", {
        message: clean,
        project_id: activeProject?.id ?? null,
        channel: "voice",
        language: lang,
      });
      if (closedRef.current) return;
      if (resp.requires_confirmation) {
        setConfirmation(resp.requires_confirmation);
        setAnswer(resp);
        setState("RESPONDING");
        await speak(resp.answer);
        if (!closedRef.current) setState("IDLE");
        api("/assistant/voice/log", "POST", {
          state: "PROCESSING", project_id: activeProject?.id ?? null,
          transcript: clean, intent: "SENSITIVE_ACTION",
          sensitive_action: true, confirmation_required: true,
          stt_engine: SR ? "webspeech" : "manual", tts_engine: "speechsynthesis", language: lang,
        }).catch(() => {});
        return;
      }
      setAnswer(resp);
      setConfirmation(null);
      setActions(actionsForIntent(resp.intent, activeProject?.id ?? null));
      setState("RESPONDING");
      api("/assistant/voice/log", "POST", {
        state: "RESPONDING", project_id: activeProject?.id ?? null,
        transcript: clean, intent: resp.intent,
        stt_engine: SR ? "webspeech" : "manual", tts_engine: "speechsynthesis", language: lang,
      }).catch(() => {});
      await speak(resp.answer);
      if (!closedRef.current) setState("IDLE");
    } catch (e: any) {
      if (closedRef.current) return;
      setState(e?.status === 0 ? "NETWORK_ERROR" : "ERROR");
    }
  }, [activeProject, lang, speak]);

  const startListening = useCallback(() => {
    setAnswer(null);
    setConfirmation(null);
    setTranscript("");
    setActions([]);
    if (!SR) {
      setState("UNSUPPORTED");
      setShowType(true);
      return;
    }
    setState("ACTIVATING");
    playActivationSound();

    // REAL microphone metering — the visualisation is only a bonus; if the
    // meter is denied, recognition may still work.
    const startMeter = async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        streamRef.current = stream;
        const ctx = new AudioContext();
        audioCtxRef.current = ctx;
        const source = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        analyser.smoothingTimeConstant = 0.55;
        source.connect(analyser);
        analyserRef.current = analyser;
        waveArrayRef.current = new Uint8Array(new ArrayBuffer(analyser.fftSize));
        const levelBuf = new Uint8Array(analyser.frequencyBinCount);
        const tick = () => {
          const a = analyserRef.current;
          if (!a) return;
          a.getByteTimeDomainData(waveArrayRef.current!);
          a.getByteFrequencyData(levelBuf);
          let sum = 0;
          for (let i = 0; i < waveArrayRef.current!.length; i++) sum += Math.abs(waveArrayRef.current![i] - 128);
          const rms = sum / waveArrayRef.current!.length / 128;
          micLevelRef.current = Math.min(1, rms * 2.4);
          rafRef.current = requestAnimationFrame(tick);
        };
        tick();
      } catch {
        /* meter denied — recognition may still work */
      }
    };
    startMeter();

    try {
      const rec = new SR();
      recognitionRef.current = rec;
      rec.lang = srLang;
      rec.interimResults = true;
      rec.maxAlternatives = 1;
      let finalText = "";
      rec.onresult = (event: any) => {
        let interim = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const res = event.results[i];
          if (res.isFinal) finalText += res[0].transcript;
          else interim += res[0].transcript;
        }
        setTranscript((finalText + " " + interim).trim());
      };
      rec.onerror = (event: any) => {
        stopAudioMeter();
        if (event.error === "not-allowed" || event.error === "service-not-allowed") {
          setState("PERMISSION_DENIED");
          setShowType(true);
        } else if (event.error === "no-speech") setState("NO_SPEECH");
        else if (event.error === "network") setState("NETWORK_ERROR");
        else setState("ERROR");
      };
      rec.onend = () => {
        stopAudioMeter();
        if (closedRef.current) return;
        if (finalText.trim()) ask(finalText.trim());
        else if (state !== "ERROR" && state !== "PERMISSION_DENIED") setState("NO_SPEECH");
        else setState("IDLE");
      };
      rec.start();
      setTimeout(() => { if (!closedRef.current && recognitionRef.current) setState("LISTENING"); }, 350);
    } catch {
      setState("UNSUPPORTED");
      setShowType(true);
      stopAudioMeter();
    }
  }, [ask, playActivationSound, srLang, state, stopAudioMeter]);

  /** §43 STOP — stop recognition, TTS, metering; back to IDLE. */
  const stopEverything = useCallback(() => {
    releaseAll();
    setConfirmation(null);
    setState("IDLE");
  }, [releaseAll]);

  /** §43 CLOSE — same release + close interface. */
  const closeAll = useCallback(() => {
    closedRef.current = true;
    releaseAll();
    onClose();
  }, [onClose, releaseAll]);

  useEffect(() => {
    closedRef.current = !open;
    if (open) {
      setState("IDLE");
      setTranscript("");
      setAnswer(null);
      setConfirmation(null);
      setActions([]);
      const unsupported = !SR;
      if (unsupported) setShowType(true); else setShowType(false);
      setTimeout(() => { if (!closedRef.current) startListening(); }, 420); // auto-start after expansion
    } else {
      releaseAll();
    }
    return () => releaseAll();
    // eslint-disable-next-line
  }, [open]);

  // Esc closes; focus the type input when shown
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeAll();
    };
    window.addEventListener("keydown", onKey);
    if (showType) setTimeout(() => typeInputRef.current?.focus(), 60);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, showType, closeAll]);

  const stateLabel: Record<VoiceState, string> = {
    IDLE: "AI ASSISTANT READY — tap the mic and speak",
    ACTIVATING: "INITIALIZING AI…",
    LISTENING: "LISTENING…",
    PROCESSING: "ANALYZING REQUEST…",
    RESPONDING: "NIECP-AI RESPONDING",
    ERROR: "Something went wrong. Try again.",
    PERMISSION_DENIED: "Microphone access is unavailable. You can type your request instead.",
    NO_SPEECH: "I didn't hear anything. Tap the mic and try again.",
    NETWORK_ERROR: "You appear to be offline. Voice needs a connection; your data is safe.",
    UNSUPPORTED: "Voice input isn't supported in this browser. Type your request instead.",
  };

  const stateTone: Record<VoiceState, string> = {
    IDLE: "text-slate-400", ACTIVATING: "text-cyan-300", LISTENING: "text-teal-300", PROCESSING: "text-indigo-300",
    RESPONDING: "text-emerald-300", ERROR: "text-rose-300", PERMISSION_DENIED: "text-rose-300",
    NO_SPEECH: "text-amber-300", NETWORK_ERROR: "text-amber-300", UNSUPPORTED: "text-amber-300",
  };

  const quick = [
    activeProject ? "What approvals are required for my project?" : "How does NIECP-AI work?",
    "What should I do next?",
    "What documents are missing?",
    "Show my pending approvals",
    "Find schemes for my business",
  ];

  const canRetakeMic = state === "IDLE" || state === "NO_SPEECH" || state === "ERROR" || state === "UNSUPPORTED" || state === "PERMISSION_DENIED" || state === "NETWORK_ERROR";

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex flex-col items-center overflow-y-auto bg-ink-950/94 p-4 backdrop-blur-md"
          role="dialog"
          aria-modal="true"
          aria-label="NIECP AI voice assistant"
        >
          {/* holographic HUD frame */}
          <div className="pointer-events-none fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 opacity-30" aria-hidden>
            <div className="h-[92vmin] w-[92vmin] rounded-full border border-cyan-400/10" />
          </div>

          <div className="w-full max-w-2xl">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-teal-300" aria-hidden />
                NIECP-AI Command
              </div>
              <button onClick={closeAll} className="rounded-lg border border-white/10 px-2.5 py-1 text-xs text-slate-400 hover:bg-white/10 hover:text-slate-200" aria-label="Close assistant">✕ ESC</button>
            </div>
          </div>

          {/* the voice-reactive core */}
          <div className="relative mt-4 h-56 w-56 sm:h-72 sm:w-72" role="img" aria-label={`Assistant state: ${stateLabel[state]}`}>
            <VoiceReactiveCore state={state} getMicLevel={getMicLevel} getWave={getWave} getTtsLevel={getTtsLevel} />
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className={`text-[10px] font-bold uppercase tracking-[0.28em] ${stateTone[state]}`}>
                {state === "IDLE" ? "STANDBY" : state}
              </div>
            </div>
          </div>

          <div className={`mt-2 text-center text-[12.5px] font-medium ${stateTone[state]}`} aria-live="polite">{stateLabel[state]}</div>

          {transcript ? (
            <div className="mt-3 w-full max-w-xl rounded-2xl border border-white/10 bg-white/5 px-4 py-2.5 text-center text-[13.5px] leading-relaxed text-slate-100">
              <span className="mr-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">You said</span>
              “{transcript}”
            </div>
          ) : null}

          {answer ? (
            <div className="mt-3 max-h-[28vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-white/10 bg-ink-850/90 p-4 text-[13px] leading-relaxed text-slate-200">
              <div className="whitespace-pre-wrap">{answer.answer}</div>
              {answer.sources?.length ? (
                <div className="mt-3 border-t border-white/10 pt-2 text-[11px] text-slate-500">
                  Source: {answer.sources[0].publisher || answer.sources[0].title} · {String(answer.status || "").replace(/_/g, " ").toLowerCase()}
                  {answer.used_llm ? " · AI rephrased" : " · deterministic"}
                </div>
              ) : null}
            </div>
          ) : null}

          {confirmation ? (
            <div className="mt-3 w-full max-w-xl rounded-2xl border border-amber-400/30 bg-amber-400/8 p-3.5">
              <p className="text-[12.5px] text-amber-100/90">{confirmation.message}</p>
              <p className="mt-1 text-[11px] text-amber-100/60">Sensitive government actions are never executed on voice alone. Confirm here, or cancel.</p>
              <div className="mt-2.5 flex gap-3">
                <Button variant="danger" onClick={async () => {
                  await api("/assistant/voice/confirmation", "POST", { session_id: null, action: confirmation.action, approved: true }).catch(() => {});
                  const act = confirmation.action;
                  setConfirmation(null);
                  await ask(act === "SUBMIT_APPLICATION"
                    ? "What are the steps to submit this application on the official portal?"
                    : confirmation.message);
                }}>
                  {confirmation.confirm_label || "CONFIRM"}
                </Button>
                <Button variant="outline" onClick={async () => {
                  await api("/assistant/voice/confirmation", "POST", { session_id: null, action: confirmation.action, approved: false }).catch(() => {});
                  setConfirmation(null);
                  setState("IDLE");
                }}>
                  {confirmation.cancel_label || "CANCEL"}
                </Button>
              </div>
            </div>
          ) : null}

          {/* action affordances (§56) */}
          {actions.length && !confirmation ? (
            <div className="mt-3 flex max-w-2xl flex-wrap justify-center gap-2">
              {actions.map((a) => (
                <button key={a.label}
                  onClick={() => { if (!a.route) return; closeAll(); navigate(a.route); }}
                  className="rounded-full border border-cyan-400/25 bg-cyan-400/8 px-3.5 py-1.5 text-[11px] font-semibold tracking-wide text-cyan-200 transition-colors hover:border-cyan-300/50 hover:bg-cyan-400/15">
                  {a.label}
                </button>
              ))}
            </div>
          ) : null}

          {/* controls (§43) */}
          <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
            {canRetakeMic && SR ? (
              <Button size="lg" onClick={startListening} aria-label="Start speaking">🎙 {state === "IDLE" ? "Speak" : "Try again"}</Button>
            ) : null}
            {!canRetakeMic ? (
              <Button variant="outline" onClick={stopEverything} aria-label="Stop">⏹ Stop</Button>
            ) : null}
            <Button variant="ghost" onClick={() => { setMuted(!muted); if (!muted) speechSynthesis?.cancel?.(); }} aria-pressed={muted} aria-label="Mute responses">
              {muted ? "🔇 Muted" : "🔊 Mute"}
            </Button>
            <Button variant="ghost" onClick={() => setShowType(!showType)} aria-expanded={showType} aria-label="Type instead">⌨ Type</Button>
            <Button variant="outline" onClick={closeAll} aria-label="Close">Close</Button>
          </div>

          {/* text fallback (§44) */}
          {showType ? (
            <form className="mt-3 flex w-full max-w-xl gap-2" onSubmit={(e) => { e.preventDefault(); const v = typeText; setTypeText(""); ask(v); }}>
              <input
                ref={typeInputRef}
                value={typeText}
                onChange={(e) => setTypeText(e.target.value)}
                placeholder="Type your request instead — e.g. “What approvals do I need?”"
                className="flex-1 rounded-xl border border-white/12 bg-ink-850 px-3.5 py-2.5 text-[13px] text-slate-100 outline-none placeholder:text-slate-600 focus:border-brand-400/60"
                aria-label="Type your question"
              />
              <Button disabled={!typeText.trim()} type="submit">Ask</Button>
            </form>
          ) : null}

          {state === "IDLE" && !transcript ? (
            <div className="mt-4 flex max-w-2xl flex-wrap justify-center gap-2 pb-4">
              {quick.map((q) => (
                <button key={q} onClick={() => ask(q)} className="rounded-full border border-white/12 px-3 py-1.5 text-[11.5px] text-slate-400 hover:border-brand-400/40 hover:text-brand-300">
                  {q}
                </button>
              ))}
            </div>
          ) : null}
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
