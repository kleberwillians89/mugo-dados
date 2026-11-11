import { useEffect, useRef, useState } from "react";
import { BookmarkPlus, Check, Sparkles, Trash2 } from "lucide-react";
import { getActiveClientName } from "../app/activeClient";
import { addKnowledgeFacts, askMugoIA, clearMugoIA, getMugoIA, type MugoIAMessage } from "../app/studio";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import "../styles/studio.css";

const TEAM_SUGGESTIONS = [
  "Como está a saúde da marca e o que o público anda falando?",
  "O que os concorrentes fizeram nas últimas semanas?",
  "Quais produtos mais vendem e como usar isso no conteúdo?",
  "Resumo do mês: vendas, mídia, metas e o que fazer agora",
  "Quais alertas e tarefas abertas pedem atenção?",
  "O que falta conectar ou enviar para a IA conhecer melhor a marca?",
];
const CLIENT_SUGGESTIONS = [
  "Como está a saúde da minha marca?",
  "O que o público anda falando da gente?",
  "O que saiu na imprensa sobre a marca e os concorrentes?",
  "Quais são os próximos posts do calendário?",
  "Resumo do mês: vendas, mídia e metas",
];

/** Rótulos das lacunas que vêm do backend (fonte sem dado ou fora do ar). */
const GAP_LABEL: Record<string, string> = {
  perfil_da_marca_vazio: "perfil da marca", contexto_do_negocio_vazio: "contexto do negócio", sem_kpis_no_periodo: "indicadores do período",
  sem_historico_de_posts: "histórico de posts", sem_metas_no_mes: "metas do mês", saude_da_marca: "saúde da marca",
  voz_do_publico: "voz do público", concorrentes: "concorrentes", produtos_mais_vendidos: "produtos vendidos", clipping: "clipping",
  proximos_posts: "calendário", alertas: "alertas", briefings: "briefings", tarefas: "tarefas", pacote: "dados da marca",
};
const gapLabel = (gap: string) => GAP_LABEL[gap] || gap.replace(/_/g, " ");

/**
 * Mugô IA: a pessoa pergunta qualquer coisa sobre o mundo do cliente e a IA responde lendo TODO o contexto dele
 * (dados, material enviado, saúde da marca, voz do público, concorrentes, clipping, produtos, calendário, mídia, metas).
 * Cada empresa tem o seu contexto; cada pessoa, a sua conversa. O cliente nunca vê o que é só da equipe.
 */
export default function MugoIA({ canManage, isAgency }: { canManage: boolean; isAgency: boolean }) {
  const company = getActiveClientName() || "empresa";
  const [messages, setMessages] = useState<MugoIAMessage[] | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<Record<string, boolean>>({});
  const [confirmClear, setConfirmClear] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const suggestions = isAgency ? TEAM_SUGGESTIONS : CLIENT_SUGGESTIONS;

  useEffect(() => { getMugoIA().then((r) => setMessages(r.messages)).catch(() => setMessages([])); }, []);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "nearest" }); }, [messages?.length, busy]);

  async function send(question = text) {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true); setError(null);
    setMessages((m) => [...(m || []), { id: null, role: "user", content: q }]);
    setText("");
    try {
      const res = await askMugoIA(q);
      setMessages((m) => [...(m || []), { id: res.id, role: "assistant", content: res.answer,
        meta: { on_topic: res.on_topic, sources: res.sources, new_facts: res.new_facts, follow_ups: res.follow_ups, coverage: res.coverage } }]);
    } catch (cause) {
      setMessages((m) => (m || []).slice(0, -1));
      setText(q);
      setError(cause instanceof Error && cause.message ? cause.message : "A Mugô IA não respondeu agora. Tente de novo.");
    } finally { setBusy(false); }
  }

  async function keep(key: string, facts: string[]) {
    setError(null);
    try { await addKnowledgeFacts(facts); setSaved((s) => ({ ...s, [key]: true })); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível guardar."); }
  }

  async function clear() {
    setError(null);
    try { await clearMugoIA(); setMessages([]); setConfirmClear(false); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível apagar a conversa."); }
  }

  const lastAnswer = [...(messages || [])].reverse().find((m) => m.role === "assistant");

  return <Shell title="Mugô IA" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={company} title="Mugô IA" />
    <p className="libHint">Pergunte qualquer coisa sobre a {company}. A Mugô IA lê tudo da marca antes de responder: dados e métricas, material enviado,
      saúde da marca, o que o público fala, concorrentes, clipping, produtos, calendário, mídia e metas. Sua conversa é só sua.</p>
    <section className="agentBox mugoIA" aria-label="Conversar com a Mugô IA">
      <header>
        <h3><Sparkles size={16} aria-hidden="true" /> Mugô IA · {company}</h3>
        {messages?.length ? (confirmClear
          ? <span className="kbRow"><small>Apagar sua conversa?</small>
            <button type="button" className="kbLink" onClick={() => void clear()}>Apagar</button>
            <button type="button" className="kbLink" onClick={() => setConfirmClear(false)}>Cancelar</button></span>
          : <button type="button" className="kbLink" onClick={() => setConfirmClear(true)}><Trash2 size={14} aria-hidden="true" /> Limpar conversa</button>) : null}
      </header>
      <div className="chatThread mugoIAThread" aria-live="polite">
        {messages === null ? <p className="libHint">Carregando…</p> : null}
        {messages && !messages.length ? <div className="agentSuggest">
          {suggestions.map((s) => <button key={s} type="button" onClick={() => void send(s)} disabled={busy}>{s}</button>)}
        </div> : null}
        {(messages || []).map((m, i) => {
          const key = m.id || `local-${i}`;
          const facts = m.meta?.new_facts || [];
          const isLast = m === lastAnswer;
          return <div key={key} className={`chatMsg ${m.role === "user" ? "is-mine" : "is-agent"}${m.meta?.on_topic === false ? " is-offtopic" : ""}`}>
            <small>{m.role === "user" ? "Você" : "Mugô IA"}</small>
            <p>{m.content}</p>
            {m.meta?.sources?.length ? <small className="agentSources">Com base em: {m.meta.sources.join(", ")}</small> : null}
            {isLast && m.meta?.coverage?.gaps?.length ? <small className="mugoIAGaps">Sem dado agora: {m.meta.coverage.gaps.map(gapLabel).join(", ")}</small> : null}
            {facts.length && canManage ? <div className="agentFacts">
              <small>Fato novo sobre a marca:</small>
              <ul>{facts.map((f) => <li key={f}>{f}</li>)}</ul>
              {saved[key]
                ? <span className="agentSaved"><Check size={13} aria-hidden="true" /> Guardado na memória da marca</span>
                : <button type="button" className="kbLink" onClick={() => void keep(key, facts)}><BookmarkPlus size={14} aria-hidden="true" /> Guardar na memória da marca</button>}
            </div> : null}
            {isLast && m.meta?.follow_ups?.length && !busy ? <div className="agentSuggest mugoIAFollow">
              {m.meta.follow_ups.map((f) => <button key={f} type="button" onClick={() => void send(f)}>{f}</button>)}
            </div> : null}
          </div>;
        })}
        {busy ? <div className="chatMsg is-agent"><small>Mugô IA</small><p className="agentTyping">Lendo tudo da {company} e pensando…</p></div> : null}
        <div ref={end} />
      </div>
      {error ? <p role="alert" className="studioError">{error}</p> : null}
      <div className="chatComposer">
        <textarea rows={2} value={text} maxLength={1500} placeholder={`Pergunte qualquer coisa sobre a ${company}…`} aria-label="Pergunta para a Mugô IA"
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} />
        <div className="chatActions">
          <button type="button" className="ds-button is-primary" onClick={() => void send()} disabled={busy || !text.trim()}>{busy ? "Pensando…" : "Perguntar"}</button>
        </div>
      </div>
    </section>
  </div></Shell>;
}
