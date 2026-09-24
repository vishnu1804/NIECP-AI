/** AI chat interface (spec §50, §51): conversations left, messages center,
 * live project context right. */
import React, { useEffect, useRef, useState } from "react";
import { useApp } from "../lib/store";
import { api } from "../lib/api";
import { Badge, Button, Card, CardHeader, Disclaimer, Input, Spinner, StatusBadge } from "../components/ui";
import { SourceBadge } from "../components/ui";

export default function AssistantPage() {
  const { activeProject } = useApp();
  const [conversations, setConversations] = useState<any[]>([]);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [context, setContext] = useState<any>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const [speakReplies, setSpeakReplies] = useState(true);

  const loadConversations = async () => {
    const r = await api<any>(`/assistant/conversations${activeProject ? `?project_id=${activeProject.id}` : ""}`);
    setConversations(r.conversations);
  };

  useEffect(() => { loadConversations(); /* eslint-disable-next-line */ }, [activeProject?.id]);

  useEffect(() => {
    if (conversationId) {
      api<any>(`/assistant/conversations/${conversationId}`).then((c) => {
        setMessages(c.messages.map((m: any) => ({ role: m.role, content: m.content, structured: m.structured, citations: m.citations })));
        setContext(c.context_snapshot);
      });
    }
  }, [conversationId]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);

  const send = async (text?: string) => {
    const message = (text ?? input).trim();
    if (!message || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: message }]);
    setBusy(true);
    try {
      const r = await api<any>("/assistant/chat", "POST", {
        message, project_id: activeProject?.id ?? null, conversation_id: conversationId, language: localStorage.getItem("niecp.lang") || "en",
      });
      setConversationId(r.conversation_id);
      setMessages((m) => [...m, { role: "assistant", content: r.answer, structured: r, citations: r.sources }]);
      setContext(r.data?.project_context || context);
      if (speakReplies && "speechSynthesis" in window) {
        const u = new SpeechSynthesisUtterance(r.answer.replace(/[*#•]+/g, " ").slice(0, 500));
        speechSynthesis.speak(u);
      }
      loadConversations();
    } catch (e: any) {
      setMessages((m) => [...m, { role: "assistant", content: e?.message || "AI assistance is temporarily unavailable. Your saved project information remains available.", structured: null }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto grid max-w-6xl gap-4 lg:grid-cols-[240px_1fr_260px]">
      {/* conversations */}
      <Card className="hidden max-h-[70vh] overflow-y-auto lg:block">
        <CardHeader title="Conversations" />
        <div className="space-y-1 p-2">
          <button onClick={() => { setConversationId(null); setMessages([]); }} className="w-full rounded-lg px-3 py-2 text-left text-[13px] font-medium text-brand-300 hover:bg-white/8">
            + New conversation
          </button>
          {conversations.map((c) => (
            <button key={c.id} onClick={() => setConversationId(c.id)}
              className={`w-full truncate rounded-lg px-3 py-2 text-left text-[12.5px] ${conversationId === c.id ? "bg-brand-500/15 text-brand-200" : "text-slate-400 hover:bg-white/8"}`}>
              {c.title}
            </button>
          ))}
        </div>
      </Card>

      {/* messages */}
      <Card className="flex max-h-[75vh] min-h-[60vh] flex-col">
        <CardHeader
          title={<>🤖 AI Assistant <span className="ml-2 text-[11px] font-normal text-slate-500">{activeProject ? `context: ${activeProject.name}` : "no project selected"}</span></>}
          right={
            <label className="flex items-center gap-1.5 text-[11px] text-slate-500">
              <input type="checkbox" checked={speakReplies} onChange={(e) => setSpeakReplies(e.target.checked)} className="h-3.5 w-3.5 accent-brand-500" />
              speak replies
            </label>
          }
        />
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {messages.length === 0 ? (
            <div className="space-y-3 py-8 text-center">
              <div className="text-4xl" aria-hidden>🎙️</div>
              <p className="text-[14px] font-medium text-slate-300">Ask about your approvals, documents, next steps…</p>
              <div className="mx-auto flex max-w-md flex-wrap justify-center gap-2">
                {["What approvals do I need?", "What documents are missing?", "What should I do next?", "Find schemes for my business", "Why do I need this approval?"].map((s) => (
                  <button key={s} onClick={() => send(s)} className="rounded-full border border-white/12 px-3 py-1.5 text-xs text-slate-400 hover:border-brand-400/40 hover:text-brand-300">{s}</button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-[13.5px] leading-relaxed ${m.role === "user" ? "bg-brand-500 text-white" : "border border-white/10 bg-ink-900 text-slate-200"}`}>
                  <div className="whitespace-pre-wrap">{m.content}</div>
                  {m.role === "assistant" && m.structured ? (
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      {m.structured.status ? <SourceBadge status={m.structured.status} /> : null}
                      {m.structured.confidence ? <Badge tone="slate">{m.structured.confidence.replace("_", " ").toLowerCase()}</Badge> : null}
                      {m.structured.used_llm ? <Badge tone="violet">LLM-phrased</Badge> : null}
                      {m.structured.agent ? <Badge tone="slate">{m.structured.agent.replace(/_/g, " ")}</Badge> : null}
                    </div>
                  ) : null}
                  {m.role === "assistant" && m.structured?.sources?.length ? (
                    <div className="mt-2 border-t border-white/10 pt-2">
                      {m.structured.sources.slice(0, 3).map((s: any, j: number) => (
                        <div key={j} className="text-[10.5px] text-slate-500">
                          📚 {s.title} {s.publisher ? `— ${s.publisher}` : ""} {s.url ? <a className="text-brand-300 hover:underline" href={s.url} target="_blank" rel="noopener noreferrer">view ↗</a> : null}
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {m.role === "assistant" && m.structured?.requires_confirmation ? (
                    <div className="mt-2 flex gap-2">
                      <Button size="sm" variant="danger" onClick={() => send(m.structured.requires_confirmation.action === "SUBMIT_APPLICATION" ? "What are the steps to submit this application on the official portal?" : m.structured.requires_confirmation.message)}>CONFIRM</Button>
                      <Button size="sm" variant="outline" onClick={() => setMessages((ms) => [...ms, { role: "assistant", content: "Cancelled — nothing was sent. The confirmation decision is recorded in the audit log.", structured: null }])}>CANCEL</Button>
                    </div>
                  ) : null}
                  {m.role === "assistant" && m.structured?.next_step?.link ? (
                    <a href={`#${m.structured.next_step.link}`} className="mt-2 inline-block rounded-lg bg-white/8 px-3 py-1.5 text-[12px] font-medium text-brand-300 hover:bg-white/12">
                      {m.structured.next_step.action} →
                    </a>
                  ) : null}
                </div>
              </div>
            ))
          )}
          {busy ? <div className="flex justify-start"><div className="rounded-2xl border border-white/10 bg-ink-900 px-4 py-2.5"><Spinner /></div></div> : null}
          <div ref={endRef} />
        </div>
        <div className="border-t border-white/8 p-3">
          <form onSubmit={(e) => { e.preventDefault(); send(); }} className="flex gap-2">
            <Input value={input} onChange={(e) => setInput(e.target.value)} placeholder={activeProject ? `Ask about ${activeProject.name}…` : "Ask anything — select a project for grounded answers…"} />
            <Button type="submit" disabled={busy || !input.trim()}>Send</Button>
          </form>
        </div>
      </Card>

      {/* context panel */}
      <Card className="hidden max-h-[70vh] overflow-y-auto lg:block">
        <CardHeader title="Project context" subtitle="What the assistant can see" />
        <div className="space-y-3 p-4 text-[12.5px]">
          {!activeProject ? (
            <Disclaimer tone="blue">Select a project to ground answers in your profile, approvals and documents.</Disclaimer>
          ) : context ? (
            <>
              <ContextList title="Applicable approvals" items={(context.applicable_approvals || []).map((a: any) => `${a.name} (${a.state})`)} />
              <ContextList title="Documents on file" items={(context.documents_on_file || []).map((d: any) => d.title)} />
              <ContextList title="Applications" items={(context.applications || []).map((a: any) => `${a.title} — ${a.status}`)} />
            </>
          ) : (
            <p className="text-slate-500">Context loads with the first reply. The assistant sees: project profile, applicable approvals, documents, applications, compliance and schemes — never anything else.</p>
          )}
        </div>
      </Card>
    </div>
  );
}

function ContextList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">{title}</div>
      {items.length === 0 ? <p className="text-[11.5px] text-slate-600">none yet</p> : (
        <ul className="space-y-0.5 text-[11.5px] leading-relaxed text-slate-400">
          {items.slice(0, 8).map((i, k) => <li key={k} className="truncate">• {i}</li>)}
        </ul>
      )}
    </div>
  );
}
