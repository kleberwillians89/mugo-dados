import { useEffect, useState } from "react";
import { getAutoReplySample, rateAutoReply, type AutoReply } from "../../app/brandContext";

/**
 * Respostas que a IA mandou sozinha (WhatsApp, Direct, comentários), sorteadas para a equipe avaliar.
 * Com a resposta automática ligada ninguém revisa antes de sair: o 👎 com motivo é o que ensina a IA a errar menos.
 */
export default function AutoReplyReview() {
  const [replies, setReplies] = useState<AutoReply[] | null>(null);
  const [down, setDown] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [rated, setRated] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { getAutoReplySample().then((r) => setReplies(r.replies)).catch(() => setReplies([])); }, []);

  async function send(reply: AutoReply, rating: "up" | "down") {
    setBusy(true); setError(null);
    try {
      await rateAutoReply(reply, rating, rating === "down" ? reason : undefined);
      setReplies((cur) => (cur || []).filter((r) => r.ref_id !== reply.ref_id));
      setRated((n) => n + 1); setDown(null); setReason("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível salvar a avaliação."); }
    finally { setBusy(false); }
  }

  if (!replies || (!replies.length && !rated)) return null;
  return <div className="bcAutoReplies" data-testid="auto-reply-review">
    <h3>Respostas que a IA mandou sozinha</h3>
    <p className="libHint">Avalie algumas da semana. O 👎 com o motivo vira aprendizado e a IA corrige nas próximas respostas.</p>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {!replies.length ? <p role="status" className="studioOk">{rated} avaliada(s). Obrigado: entram no próximo aprendizado.</p> : null}
    {replies.map((reply) => <article key={reply.ref_id} className="bcField" data-reply={reply.ref_id}>
      <div className="bcFieldHead"><b>{reply.channel_label}</b></div>
      <p><small>Cliente:</small> {reply.customer_text}</p>
      <p><small>IA:</small> {reply.ai_text}</p>
      {down === reply.ref_id ? <div className="kbRow">
        <input type="text" maxLength={300} value={reason} placeholder="O que estava errado? (ex.: tom formal demais, prometeu prazo)"
          aria-label="Motivo do 👎" onChange={(e) => setReason(e.target.value)} />
        <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => void send(reply, "down")}>Enviar</button>
        <button type="button" className="ds-button" disabled={busy} onClick={() => { setDown(null); setReason(""); }}>Cancelar</button>
      </div> : <div className="kbRow">
        <button type="button" className="ds-button" disabled={busy} aria-label="Resposta boa" onClick={() => void send(reply, "up")}>👍 Boa</button>
        <button type="button" className="ds-button" disabled={busy} aria-label="Resposta ruim" onClick={() => setDown(reply.ref_id)}>👎 Ruim</button>
      </div>}
    </article>)}
  </div>;
}
