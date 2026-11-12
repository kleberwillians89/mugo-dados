import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowUp, BookmarkPlus, Check, CornerDownRight, Plus, Sparkles } from "lucide-react";
import { getActiveClientName } from "../app/activeClient";
import { addKnowledgeFacts, askMugoIA, clearMugoIA, getMugoIA, type MugoIAMessage } from "../app/studio";
import Shell from "../components/Shell";
import "../styles/studio.css";
import "../styles/mugoverso-ia.css";

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
const READS = ["Métricas", "Material enviado", "Saúde da marca", "Voz do público", "Concorrentes", "Clipping", "Produtos", "Calendário", "Mídia", "Metas"];

/** Rótulos das lacunas que vêm do backend (fonte sem dado ou fora do ar). */
const GAP_LABEL: Record<string, string> = {
  perfil_da_marca_vazio: "perfil da marca", contexto_do_negocio_vazio: "contexto do negócio", sem_kpis_no_periodo: "indicadores do período",
  sem_historico_de_posts: "histórico de posts", sem_metas_no_mes: "metas do mês", saude_da_marca: "saúde da marca",
  voz_do_publico: "voz do público", concorrentes: "concorrentes", produtos_mais_vendidos: "produtos vendidos", clipping: "clipping",
  proximos_posts: "calendário", alertas: "alertas", briefings: "briefings", tarefas: "tarefas", pacote: "dados da marca",
};
const gapLabel = (gap: string) => GAP_LABEL[gap] || gap.replace(/_/g, " ");
const ACTION_RE = /^(o que eu faria agora|próximo passo|recomendação)\s*:?/i;

/** Texto da IA → parágrafos, listas e o bloco "O que eu faria agora" em destaque. Sem HTML vindo da IA. */
export function AnswerBody({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  let action: string[] | null = null;
  const flushList = () => {
    if (list.length) blocks.push(<ul key={`l${blocks.length}`}>{list.map((item, i) => <li key={i}>{item}</li>)}</ul>);
    list = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) { flushList(); continue; }
    if (ACTION_RE.test(line)) {
      flushList();
      action = [];
      const rest = line.replace(ACTION_RE, "").trim();
      if (rest) action.push(rest.replace(/^[-•]\s*/, ""));
      continue;
    }
    if (action) { action.push(line.replace(/^[-•]\s*/, "")); continue; }
    if (/^[-•]\s+/.test(line)) { list.push(line.replace(/^[-•]\s+/, "")); continue; }
    flushList();
    blocks.push(<p key={`p${blocks.length}`}>{line}</p>);
  }
  flushList();
  return <div className="miaAnswer">
    {blocks}
    {action && (action as string[]).length ? <div className="miaAction"><b>O que eu faria agora</b>
      {(action as string[]).length > 1 ? <ul>{(action as string[]).map((a, i) => <li key={i}>{a}</li>)}</ul> : <p>{(action as string[])[0]}</p>}</div> : null}
  </div>;
}

/**
 * Mugoverso IA: a pessoa pergunta qualquer coisa sobre o mundo do cliente e a IA responde lendo TODO o contexto dele
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
  const input = useRef<HTMLTextAreaElement>(null);
  const suggestions = isAgency ? TEAM_SUGGESTIONS : CLIENT_SUGGESTIONS;

  useEffect(() => { getMugoIA().then((r) => setMessages(r.messages)).catch(() => setMessages([])); }, []);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end", behavior: "smooth" }); }, [messages?.length, busy]);
  useEffect(() => {
    const el = input.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

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
      setError(cause instanceof Error && cause.message ? cause.message : "O Tira-dúvidas não respondeu agora. Tente de novo.");
    } finally { setBusy(false); input.current?.focus(); }
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
  const empty = messages !== null && !messages.length;

  return <Shell title="Tira-dúvidas" variant="editorial" themeClass="miaShell"><div className="mia">
    <header className="miaTop">
      <div className="miaBrand">
        <span className="miaMark" aria-hidden="true"><Sparkles size={16} /></span>
        <div><h1>Tira-dúvidas</h1><small>{company} · lê tudo da marca antes de responder</small></div>
      </div>
      {messages?.length ? (confirmClear
        ? <div className="miaConfirm"><span>Apagar esta conversa?</span>
          <button type="button" className="miaGhost is-danger" onClick={() => void clear()}>Apagar</button>
          <button type="button" className="miaGhost" onClick={() => setConfirmClear(false)}>Cancelar</button></div>
        : <button type="button" className="miaGhost" onClick={() => setConfirmClear(true)}><Plus size={15} aria-hidden="true" /> Nova conversa</button>) : null}
    </header>

    <div className="miaScroll" aria-live="polite">
      <div className="miaColumn">
        {messages === null ? <div className="miaLoading" role="status"><span className="miaDots"><i /><i /><i /></span></div> : null}

        {empty ? <section className="miaHero">
          <span className="miaMark is-big" aria-hidden="true"><Sparkles size={26} /></span>
          <h2>O que você quer saber sobre a {company}?</h2>
          <p>Antes de cada resposta eu leio tudo o que a Mugô tem da marca.</p>
          <ul className="miaReads" aria-label="O que o Tira-dúvidas lê">{READS.map((r) => <li key={r}>{r}</li>)}</ul>
          <div className="miaStarters">
            {suggestions.map((s) => <button key={s} type="button" disabled={busy} onClick={() => void send(s)}>{s}</button>)}
          </div>
        </section> : null}

        {(messages || []).map((m, i) => {
          const key = m.id || `local-${i}`;
          if (m.role === "user") return <div key={key} className="miaUser"><p>{m.content}</p></div>;
          const facts = m.meta?.new_facts || [];
          const isLast = m === lastAnswer;
          return <article key={key} className={`miaBot${m.meta?.on_topic === false ? " is-offtopic" : ""}`}>
            <span className="miaMark" aria-hidden="true"><Sparkles size={14} /></span>
            <div className="miaBotBody">
              <small className="miaName">Tira-dúvidas</small>
              <AnswerBody text={m.content} />
              {m.meta?.sources?.length || (isLast && m.meta?.coverage?.gaps?.length) ? <div className="miaMeta">
                {m.meta?.sources?.length ? <div className="miaChips"><span className="miaChipsLabel">Com base em</span>
                  {m.meta.sources.map((s) => <span key={s} className="miaChip">{s}</span>)}</div> : null}
                {isLast && m.meta?.coverage?.gaps?.length ? <div className="miaChips is-gap"><span className="miaChipsLabel">Sem dado agora</span>
                  {m.meta.coverage.gaps.map((g) => <span key={g} className="miaChip">{gapLabel(g)}</span>)}</div> : null}
              </div> : null}
              {facts.length && canManage ? <div className="miaFact">
                <div><b>Fato novo sobre a marca</b><ul>{facts.map((f) => <li key={f}>{f}</li>)}</ul></div>
                {saved[key]
                  ? <span className="miaSaved"><Check size={14} aria-hidden="true" /> Guardado na memória da marca</span>
                  : <button type="button" className="miaGhost" onClick={() => void keep(key, facts)}><BookmarkPlus size={15} aria-hidden="true" /> Guardar na memória da marca</button>}
              </div> : null}
              {isLast && m.meta?.follow_ups?.length && !busy ? <div className="miaFollow">
                {m.meta.follow_ups.map((f) => <button key={f} type="button" onClick={() => void send(f)}><CornerDownRight size={14} aria-hidden="true" /><span>{f}</span></button>)}
              </div> : null}
            </div>
          </article>;
        })}

        {busy ? <article className="miaBot is-thinking" role="status">
          <span className="miaMark" aria-hidden="true"><Sparkles size={14} /></span>
          <div className="miaBotBody"><small className="miaName">Tira-dúvidas</small>
            <p className="miaThinking"><span className="miaDots"><i /><i /><i /></span> Lendo tudo da {company} e pensando…</p></div>
        </article> : null}
        <div ref={end} />
      </div>
    </div>

    <footer className="miaDock">
      <div className="miaColumn">
        {error ? <p role="alert" className="miaError">{error}</p> : null}
        <form className="miaComposer" onSubmit={(e) => { e.preventDefault(); void send(); }}>
          <textarea ref={input} rows={1} value={text} maxLength={1500} placeholder={`Pergunte qualquer coisa sobre a ${company}…`}
            aria-label="Pergunta para o Tira-dúvidas" onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} />
          <button type="submit" className="miaSend" aria-label="Perguntar" disabled={busy || !text.trim()}><ArrowUp size={18} aria-hidden="true" /></button>
        </form>
        <small className="miaHint">Enter envia · Shift + Enter quebra a linha · sua conversa é só sua</small>
      </div>
    </footer>
  </div></Shell>;
}
