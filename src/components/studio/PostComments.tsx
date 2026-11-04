import { useEffect, useState, type FormEvent } from "react";
import Linkified from "./Linkified";
import { addItemComment, listItemComments, type ItemComment } from "../../app/studio";

const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

/** Fio de comentários do post. Qualquer pessoa da empresa comenta; a equipe é avisada (tarefa + WhatsApp). */
export default function PostComments({ itemId, clientMode }: { itemId: string; clientMode: boolean }) {
  const [comments, setComments] = useState<ItemComment[] | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  useEffect(() => {
    let alive = true;
    listItemComments(itemId).then((r) => { if (alive) setComments(r.comments || []); }).catch(() => { if (alive) setComments([]); });
    return () => { alive = false; };
  }, [itemId]);

  async function submit(event: FormEvent) {
    // O formulário do post envolve este bloco: não deixa o "Enter" salvar o post.
    event.preventDefault(); event.stopPropagation();
    const body = text.trim();
    if (!body) return;
    setBusy(true); setError(null); setSent(false);
    try {
      const r = await addItemComment(itemId, body);
      setComments((c) => [...(c || []), r.comment]); setText(""); setSent(true);
    } catch (cause) { setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível enviar o comentário."); }
    finally { setBusy(false); }
  }

  return <section className="postComments" aria-label="Comentários">
    <h4>Comentários{comments?.length ? ` (${comments.length})` : ""}</h4>
    {comments === null ? <p className="libHint">Carregando…</p> : null}
    {comments && !comments.length ? <p className="libHint">{clientMode ? "Tem alguma observação sobre este post? Escreva aqui (pode colar links de referência): a equipe Mugô é avisada na hora." : "Nenhum comentário ainda."}</p> : null}
    <ol>{(comments || []).map((c) => <li key={c.id || c.created_at} className={`is-${c.author_side}`}>
      <small>{c.author_side === "mugo" ? "Equipe Mugô" : "Cliente"} · {c.created_at ? when(c.created_at) : "agora"}</small>
      <p><Linkified text={c.body} /></p>
    </li>)}</ol>
    <div className="postCommentForm" role="group" aria-label="Novo comentário">
      <textarea rows={2} maxLength={2000} value={text} placeholder={clientMode ? "Escreva um comentário para a equipe Mugô" : "Responder ao cliente"} onChange={(e) => { setText(e.target.value); setSent(false); }}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit(e as unknown as FormEvent); }} />
      <button type="button" className="ds-button" disabled={busy || !text.trim()} onClick={(e) => void submit(e as unknown as FormEvent)}>{busy ? "Enviando…" : "Comentar"}</button>
    </div>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {sent && clientMode ? <p className="studioOk">Comentário enviado. A equipe Mugô foi avisada.</p> : null}
  </section>;
}
