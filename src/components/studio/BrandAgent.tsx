import { useEffect, useRef, useState } from "react";
import { BookmarkPlus, Check, MessageCircle, Trash2 } from "lucide-react";
import { addKnowledgeFacts, askBrandAgent, clearBrandAgent, getBrandAgent, type BrandAgentMessage } from "../../app/studio";

const SUGGESTIONS = ["Qual é o tom de voz da marca?", "Quais produtos e preços você conhece?", "O que a marca não pode dizer?",
  "Me dá 3 ideias de post com base no que você sabe"];

/**
 * Conversa com a IA da marca. Responde só sobre a marca, com base no que ela aprendeu.
 * Quando a pessoa conta um fato novo, a IA sugere guardar; quem pode ensinar guarda com um clique.
 */
export default function BrandAgent({ canManage, company, onLearned }: { canManage: boolean; company: string; onLearned?: () => void }) {
  const [messages, setMessages] = useState<BrandAgentMessage[] | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<Record<string, boolean>>({});
  const [confirmClear, setConfirmClear] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => { getBrandAgent().then((r) => setMessages(r.messages)).catch(() => setMessages([])); }, []);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "nearest" }); }, [messages?.length, busy]);

  async function send(question = text) {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true); setError(null);
    setMessages((m) => [...(m || []), { id: null, role: "user", content: q }]);
    setText("");
    try {
      const res = await askBrandAgent(q);
      setMessages((m) => [...(m || []), { id: res.id, role: "assistant", content: res.answer,
        meta: { on_topic: res.on_topic, sources: res.sources, new_facts: res.new_facts } }]);
    } catch (cause) {
      setMessages((m) => (m || []).slice(0, -1));
      setText(q);
      setError(cause instanceof Error ? cause.message : "A IA não respondeu agora. Tente de novo.");
    } finally { setBusy(false); }
  }

  async function keep(key: string, facts: string[]) {
    setError(null);
    try { await addKnowledgeFacts(facts); setSaved((s) => ({ ...s, [key]: true })); onLearned?.(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível guardar."); }
  }

  async function clear() {
    setError(null);
    try { await clearBrandAgent(); setMessages([]); setConfirmClear(false); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível apagar a conversa."); }
  }

  return <section className="agentBox" aria-label="Conversar com a IA da marca">
    <header>
      <h3><MessageCircle size={16} aria-hidden="true" /> Conversar com a IA da {company}</h3>
      {messages?.length ? (confirmClear
        ? <span className="kbRow"><small>Apagar sua conversa?</small>
          <button type="button" className="kbLink" onClick={() => void clear()}>Apagar</button>
          <button type="button" className="kbLink" onClick={() => setConfirmClear(false)}>Cancelar</button></span>
        : <button type="button" className="kbLink" onClick={() => setConfirmClear(true)}><Trash2 size={14} aria-hidden="true" /> Limpar conversa</button>) : null}
    </header>
    <p className="libHint">Responde só sobre a marca, com base no que ela aprendeu. Sua conversa é só sua.</p>
    <div className="chatThread" aria-live="polite">
      {messages === null ? <p className="libHint">Carregando…</p> : null}
      {messages && !messages.length ? <div className="agentSuggest">
        {SUGGESTIONS.map((s) => <button key={s} type="button" onClick={() => void send(s)} disabled={busy}>{s}</button>)}
      </div> : null}
      {(messages || []).map((m, i) => {
        const key = m.id || `local-${i}`;
        const facts = m.meta?.new_facts || [];
        return <div key={key} className={`chatMsg ${m.role === "user" ? "is-mine" : "is-agent"}${m.meta?.on_topic === false ? " is-offtopic" : ""}`}>
          <small>{m.role === "user" ? "Você" : `IA da ${company}`}</small>
          <p>{m.content}</p>
          {m.meta?.sources?.length ? <small className="agentSources">Fonte: {m.meta.sources.map((s) => s.name).join(", ")}</small> : null}
          {facts.length && canManage ? <div className="agentFacts">
            <small>Fato novo sobre a marca:</small>
            <ul>{facts.map((f) => <li key={f}>{f}</li>)}</ul>
            {saved[key]
              ? <span className="agentSaved"><Check size={13} aria-hidden="true" /> Guardado na memória da marca</span>
              : <button type="button" className="kbLink" onClick={() => void keep(key, facts)}><BookmarkPlus size={14} aria-hidden="true" /> Guardar na memória da marca</button>}
          </div> : null}
        </div>;
      })}
      {busy ? <div className="chatMsg is-agent"><small>IA da {company}</small><p className="agentTyping">Pensando…</p></div> : null}
      <div ref={end} />
    </div>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    <div className="chatComposer">
      <textarea rows={2} value={text} maxLength={1000} placeholder={`Pergunte algo sobre a ${company}…`} aria-label="Pergunta para a IA da marca"
        onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} />
      <div className="chatActions">
        <button type="button" className="ds-button is-primary" onClick={() => void send()} disabled={busy || !text.trim()}>{busy ? "Pensando…" : "Perguntar"}</button>
      </div>
    </div>
  </section>;
}
