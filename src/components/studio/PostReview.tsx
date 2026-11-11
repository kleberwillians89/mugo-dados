import { useEffect, useRef, useState } from "react";
import { STUDIO_FORMATS, STUDIO_STATUS, localParts, type CalendarItem, type StudioFormat, type StudioStatus } from "../../app/studio";
import { artList, artSlides, isDriveFolder } from "../../app/artLinks";
import ArtCarousel from "./ArtCarousel";
import PostComments from "./PostComments";

const VERTICAL: StudioFormat[] = ["reels", "stories", "video"];

type Props = {
  item: CalendarItem;
  handle: string;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  /** aprovado (comentário opcional) ou rejeitado (= pedir ajuste, comentário obrigatório). */
  onDecide: (status: Extract<StudioStatus, "aprovado" | "rejeitado">, note?: string) => Promise<void>;
  /** Mostra a conversa do post (comentários com a equipe) recolhida embaixo. */
  showThread?: boolean;
};

/**
 * Revisão enxuta de uma peça (cliente e quadro de Tarefas): o post num celular, a legenda, um campo para
 * comentar e os botões Aprovar / Pedir ajuste. Edição completa da pauta fica com a equipe no Calendário.
 */
export default function PostReview({ item, handle, busy, error, onClose, onDecide, showThread = true }: Props) {
  const [note, setNote] = useState("");
  const [captionOpen, setCaptionOpen] = useState(false);
  const [artFailed, setArtFailed] = useState<string | null>(null);
  const [missingNote, setMissingNote] = useState(false);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const slides = artSlides(item.art_url);
  const art = slides.length && slides[0] !== artFailed ? slides : null;
  const folder = artList(item.art_url).some(isDriveFolder);
  const vertical = VERTICAL.includes(item.format);
  const when = localParts(item.scheduled_at);
  const caption = item.caption_draft || "";
  const short = caption.length > 180 && !captionOpen ? `${caption.slice(0, 180).trimEnd()}…` : caption;
  const name = handle.replace(/^@/, "");
  const decided = item.status === "aprovado" || item.status === "publicado";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    dialogRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  async function askChanges() {
    if (!note.trim()) { setMissingNote(true); return; }
    await onDecide("rejeitado", note.trim());
    setNote("");
  }

  return <div className="postModalBackdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
    <div className="postReview" role="dialog" aria-modal="true" aria-label={`Revisar: ${item.title}`} tabIndex={-1} ref={dialogRef}>
      <button type="button" className="postModalClose" aria-label="Fechar" onClick={onClose} disabled={busy}>×</button>

      <div className="phoneFrame" aria-label="Como o post vai aparecer">
        <div className="phoneScreen">
          <header className="igHeader"><span className="igAvatar">{name.slice(0, 2).toUpperCase()}</span>
            <div><strong>{name}</strong>{item.format === "reels" ? <small>Áudio original</small> : null}</div><span className="igDots">•••</span></header>
          <div className={`igMedia ${vertical ? "is-vertical" : ""} is-${item.format}${art ? " has-art" : ""}`}>
            <span className="igFormat">{STUDIO_FORMATS[item.format]}</span>
            {art ? <ArtCarousel images={art} onBroken={() => setArtFailed(art[0])} />
              : <p className="igCover">{folder ? "A arte está numa pasta do Drive: a equipe vai trocar pelo arquivo." : item.hook || item.title}</p>}
          </div>
          <div className="igActions" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M12 21s-7.5-4.6-9.6-9.2C1 8.6 3 5 6.4 5c2 0 3.4 1.1 4.1 2.4h3C14.2 6.1 15.6 5 17.6 5 21 5 23 8.6 21.6 11.8 19.5 16.4 12 21 12 21z" /></svg>
            <svg viewBox="0 0 24 24"><path d="M20.5 12a8.5 8.5 0 1 1-3.1-6.6L21 4l-1 4.1A8.4 8.4 0 0 1 20.5 12z" /></svg>
            <svg viewBox="0 0 24 24"><path d="M22 3 2 10.5l7.5 3L22 3zM9.5 13.5 12 21l10-18" /></svg>
            <svg className="igSave" viewBox="0 0 24 24"><path d="M6 3h12v18l-6-4.5L6 21z" /></svg>
          </div>
          <div className="igCaption">
            <p><strong>{name}</strong> {short || <em>Sem legenda ainda.</em>}
              {caption.length > 180 ? <button type="button" onClick={() => setCaptionOpen(!captionOpen)}>{captionOpen ? " menos" : " mais"}</button> : null}</p>
            <small>{when.weekday}, {when.label} · {when.time}</small>
          </div>
        </div>
      </div>

      <div className="postReviewSide">
        <p className="postReviewWhen"><span className={`studioStatus is-${item.status}`}>{STUDIO_STATUS[item.status]}</span> {when.label} · {when.time}</p>
        <h2>{item.title}</h2>
        {item.review_note ? <p className="studioReview">Último pedido: {item.review_note}</p> : null}
        <label className="postReviewNote">Comentário
          <textarea rows={4} maxLength={1000} value={note} placeholder="O que achou? Para pedir ajuste, conte o que precisa mudar."
            onChange={(e) => { setNote(e.target.value); setMissingNote(false); }} aria-invalid={missingNote} />
        </label>
        {missingNote ? <p className="studioError" role="alert">Escreva o que precisa mudar para pedir ajuste.</p> : null}
        {error ? <p role="alert" className="studioError">{error}</p> : null}
        {decided ? <p className="studioOk">✓ {STUDIO_STATUS[item.status]}. Se quiser mudar algo, peça ajuste.</p> : null}
        <div className="postReviewActions">
          {!decided ? <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => void onDecide("aprovado", note.trim() || undefined).then(() => setNote(""))}>{busy ? "Enviando…" : "Aprovar"}</button> : null}
          {item.status !== "publicado" ? <button type="button" className="ds-button" disabled={busy} onClick={() => void askChanges()}>Pedir ajuste</button> : null}
        </div>
        <p className="libHint">A equipe Mugô é avisada na hora.</p>
        {showThread ? <details className="postReviewThread"><summary>Conversa sobre este post</summary><PostComments itemId={item.id} clientMode /></details> : null}
      </div>
    </div>
  </div>;
}
