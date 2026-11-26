import { useContext, useRef, useState } from "react";
import { ArrowUp, Copy, MessageCircleQuestion } from "lucide-react";
import Drawer from "../Drawer";
import { askMugoIA, type MugoIAMessage } from "../../app/studio";
import { navigateToAppRoute } from "../../app/routes";
import { ASSIST_SCREENS, MugoIAAssistContext } from "./assist";
import { AnswerBody } from "./AnswerBody";
import MugoIAActions from "./MugoIAActions";
import "../../styles/mugoverso-ia.css";

/**
 * Mugô IA dentro das telas de criação (Briefing, Redação, Social Media, E-mail, Mídia On…): o botão fica no cabeçalho
 * e abre a conversa sem sair da tela. É a mesma Mugô IA (lê tudo da marca e pesquisa o mercado), com o foco da etapa.
 */
export default function MugoIAAssist() {
  const assist = useContext(MugoIAAssistContext);
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<MugoIAMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const info = assist ? ASSIST_SCREENS[assist.screen] : undefined;
  if (!assist || !info) return null;
  const screen = assist.screen;

  async function send(question = text) {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true); setError(null); setText("");
    setMessages((m) => [...m, { id: null, role: "user", content: q }]);
    try {
      const res = await askMugoIA(q, screen);
      setMessages((m) => [...m, { id: res.id, role: "assistant", content: res.answer, meta: { sources: res.sources, acao: res.acao, acoes: res.acoes } }]);
    } catch (cause) {
      setMessages((m) => m.slice(0, -1)); setText(q);
      setError(cause instanceof Error && cause.message ? cause.message : "A Mugô IA não respondeu agora. Tente de novo.");
    } finally { setBusy(false); input.current?.focus(); }
  }

  async function copy(key: string, value: string) {
    try { await navigator.clipboard.writeText(value); setCopied(key); window.setTimeout(() => setCopied(null), 1800); } catch { /* sem permissão */ }
  }

  return <>
    <button type="button" className="miaAssistButton" onClick={() => setOpen(true)} data-testid="mia-assist">
      <MessageCircleQuestion size={16} aria-hidden="true" /> {info.button || "Pedir à Mugô IA"}
    </button>
    <Drawer open={open} onClose={() => setOpen(false)} width="lg" title={`Mugô IA · ${info.label}`}
      description="Lê tudo da marca, pesquisa o mercado e ajuda nesta etapa. O que ela criar vira rascunho para vocês revisarem."
      footer={<form className="miaAssistForm" onSubmit={(e) => { e.preventDefault(); void send(); }}>
        <textarea ref={input} value={text} rows={2} placeholder={`Peça algo para ${info.label.toLowerCase()}…`} aria-label="Pergunta para a Mugô IA"
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} />
        <button type="submit" className="miaSend" disabled={busy || !text.trim()} aria-label="Enviar"><ArrowUp size={16} aria-hidden="true" /></button>
      </form>}>
      <div className="mia miaAssist">
        {!messages.length ? <div className="miaStarters">
          {info.suggestions.map((s) => <button key={s} type="button" disabled={busy} onClick={() => void send(s)}>{s}</button>)}
        </div> : null}
        {messages.map((m, i) => m.role === "user"
          ? <div key={`u${i}`} className="miaUser"><p>{m.content}</p></div>
          : <article key={m.id || `a${i}`} className="miaBot"><div className="miaBotBody">
            <AnswerBody text={m.content} />
            <MugoIAActions messageId={m.id} meta={m.meta} canCreate={assist.canCreate}
              onMeta={(meta) => setMessages((list) => list.map((x) => (x === m ? { ...x, meta } : x)))} />
            <div className="miaAssistTools">
              <button type="button" className="miaGhost" onClick={() => void copy(`a${i}`, m.content)}>
                <Copy size={14} aria-hidden="true" /> {copied === `a${i}` ? "Copiado" : "Copiar texto"}</button>
              {m.meta?.sources?.length ? <small>Com base em: {m.meta.sources.join(", ")}</small> : null}
            </div>
          </div></article>)}
        {busy ? <p className="miaHint" role="status">A Mugô IA está lendo a marca e o mercado…</p> : null}
        {error ? <p role="alert" className="studioError">{error}</p> : null}
        {messages.length ? <button type="button" className="miaGhost miaAssistContinue" onClick={() => navigateToAppRoute("mugo_ia")}>Continuar a conversa na Mugô IA</button> : null}
      </div>
    </Drawer>
  </>;
}
