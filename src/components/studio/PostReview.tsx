import { useCallback, useEffect, useRef, useState } from "react";
import {
  STUDIO_FORMATS, STUDIO_STATUS, addItemComment, addItemReference, deleteReference, listItemComments, listItemReferences, localParts, uploadReference,
  type BrandReference, type CalendarItem, type ItemComment, type StudioFormat, type StudioStatus,
} from "../../app/studio";
import { artList, artSlides, isDriveFolder } from "../../app/artLinks";
import ArtCarousel from "./ArtCarousel";
import Linkified from "./Linkified";

const VERTICAL: StudioFormat[] = ["reels", "stories", "video"];
const IMAGE_RE = /\.(jpe?g|png|webp|gif)(\?|$)/i;

type Props = {
  item: CalendarItem;
  handle: string;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  /** aprovado (comentário opcional) ou rejeitado (= pedir ajuste, comentário obrigatório). */
  onDecide: (status: Extract<StudioStatus, "aprovado" | "rejeitado">, note?: string) => Promise<void>;
  /** Mostra a conversa e as referências do post (precisam do backend). */
  showThread?: boolean;
};

const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const host = (url: string) => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; } };

/**
 * Revisão enxuta de uma peça (cliente e quadro de Tarefas): o post num celular com a legenda; ao lado, um campo de retorno,
 * referências (links ou imagens) e os botões Pedir ajuste / Aprovar. A edição completa da pauta fica com a equipe no Calendário.
 */
export default function PostReview({ item, handle, busy, error, onClose, onDecide, showThread = true }: Props) {
  const [note, setNote] = useState("");
  const [captionOpen, setCaptionOpen] = useState(false);
  const [artFailed, setArtFailed] = useState<string | null>(null);
  const [missingNote, setMissingNote] = useState(false);
  const [refs, setRefs] = useState<BrandReference[]>([]);
  const [refUrl, setRefUrl] = useState("");
  const [refBusy, setRefBusy] = useState<string | null>(null);
  const [comments, setComments] = useState<ItemComment[]>([]);
  const [sideError, setSideError] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const slides = artSlides(item.art_url);
  const art = slides.length && slides[0] !== artFailed ? slides : null;
  const folder = artList(item.art_url).some(isDriveFolder);
  const vertical = VERTICAL.includes(item.format);
  const at = localParts(item.scheduled_at);
  const caption = item.caption_draft || "";
  const limit = vertical ? 90 : 160;
  const short = caption.length > limit && !captionOpen ? `${caption.slice(0, limit).trimEnd()}…` : caption;
  const name = handle.replace(/^@/, "") || "perfil";
  const decided = item.status === "aprovado" || item.status === "publicado";
  const working = busy || refBusy !== null;

  const loadSide = useCallback(async () => {
    if (!showThread) return;
    const [r, c] = await Promise.allSettled([listItemReferences(item.id), listItemComments(item.id)]);
    if (r.status === "fulfilled") setRefs(r.value.references || []);
    if (c.status === "fulfilled") setComments(c.value.comments || []);
  }, [item.id, showThread]);

  useEffect(() => { void loadSide(); }, [loadSide]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    dialogRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  async function addLink() {
    const url = refUrl.trim();
    if (!url) return;
    if (!/^https?:\/\//i.test(url)) { setSideError("Cole o link completo, começando com https://"); return; }
    setRefBusy("Salvando referência…"); setSideError(null);
    try { const r = await addItemReference(item.id, { url }); setRefs((list) => [...list, r.reference]); setRefUrl(""); }
    catch (cause) { setSideError(cause instanceof Error && cause.message ? cause.message : "Não foi possível salvar a referência."); }
    finally { setRefBusy(null); }
  }

  async function addImages(files: FileList | null) {
    if (!files?.length) return;
    setSideError(null);
    try {
      for (const [i, file] of [...files].entries()) {
        setRefBusy(files.length > 1 ? `Enviando imagem ${i + 1} de ${files.length}…` : "Enviando imagem…");
        const url = await uploadReference(file);
        const r = await addItemReference(item.id, { url, kind: "arte" });
        setRefs((list) => [...list, r.reference]);
      }
    } catch (cause) { setSideError(cause instanceof Error && cause.message ? cause.message : "Não foi possível enviar a imagem."); }
    finally { setRefBusy(null); if (fileRef.current) fileRef.current.value = ""; }
  }

  async function removeRef(id: string) {
    setRefBusy("Removendo…"); setSideError(null);
    try { await deleteReference(id); setRefs((list) => list.filter((r) => r.id !== id)); }
    catch { setSideError("Não foi possível remover a referência."); }
    finally { setRefBusy(null); }
  }

  async function sendComment() {
    const body = note.trim();
    if (!body) { setMissingNote(true); return; }
    setRefBusy("Enviando…"); setSideError(null);
    try { const r = await addItemComment(item.id, body); setComments((c) => [...c, r.comment]); setNote(""); setSent("Comentário enviado. A equipe Mugô foi avisada."); }
    catch (cause) { setSideError(cause instanceof Error && cause.message ? cause.message : "Não foi possível enviar o comentário."); }
    finally { setRefBusy(null); }
  }

  async function askChanges() {
    const body = note.trim() || (refs.length ? "Veja as referências anexadas." : "");
    if (!body) { setMissingNote(true); return; }
    await onDecide("rejeitado", body);
    setNote(""); setSent(null);
  }

  async function approve() {
    await onDecide("aprovado", note.trim() || undefined);
    setNote(""); setSent(null);
  }

  const icons = <>
    <svg viewBox="0 0 24 24"><path d="M12 21s-7.5-4.6-9.6-9.2C1 8.6 3 5 6.4 5c2 0 3.4 1.1 4.1 2.4h3C14.2 6.1 15.6 5 17.6 5 21 5 23 8.6 21.6 11.8 19.5 16.4 12 21 12 21z" /></svg>
    <svg viewBox="0 0 24 24"><path d="M20.5 12a8.5 8.5 0 1 1-3.1-6.6L21 4l-1 4.1A8.4 8.4 0 0 1 20.5 12z" /></svg>
    <svg viewBox="0 0 24 24"><path d="M22 3 2 10.5l7.5 3L22 3zM9.5 13.5 12 21l10-18" /></svg>
    <svg className="igSave" viewBox="0 0 24 24"><path d="M6 3h12v18l-6-4.5L6 21z" /></svg>
  </>;
  const captionBlock = <div className="igCaption" aria-label="Legenda">
    <p><strong>{name}</strong> {short || <em>Sem legenda ainda.</em>}
      {caption.length > limit ? <button type="button" onClick={() => setCaptionOpen(!captionOpen)}>{captionOpen ? " menos" : " mais"}</button> : null}</p>
    {!vertical ? <small>{at.weekday}, {at.label} · {at.time}</small> : null}
  </div>;
  const media = <div className={`igMedia ${vertical ? "is-vertical" : ""} is-${item.format}${art ? " has-art" : ""}`}>
    {!vertical ? <span className="igFormat">{STUDIO_FORMATS[item.format]}</span> : null}
    {art ? <ArtCarousel images={art} onBroken={() => setArtFailed(art[0])} />
      : <p className="igCover">{folder ? "A arte está numa pasta do Drive: a equipe vai trocar pelo arquivo." : item.hook || item.title}</p>}
  </div>;

  return <div className="postModalBackdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
    <div className="postReview" role="dialog" aria-modal="true" aria-label={`Revisar: ${item.title}`} tabIndex={-1} ref={dialogRef}>
      <button type="button" className="postModalClose" aria-label="Fechar" onClick={onClose} disabled={busy}>×</button>

      <div className="postReviewStage">
        <div className="phoneFrame" aria-label="Como o post vai aparecer">
          <div className={`phoneScreen${vertical ? " is-full" : ""}`}>
            {vertical ? <>
              {media}
              <header className="igHeader"><span className="igAvatar">{name.slice(0, 2).toUpperCase()}</span>
                <div><strong>{name}</strong><small>{item.format === "stories" ? at.time : "Áudio original"}</small></div>
                <span className="igFormat">{STUDIO_FORMATS[item.format]}</span></header>
              <div className="igActions is-side" aria-hidden="true">{icons}</div>
              {captionBlock}
            </> : <>
              <header className="igHeader"><span className="igAvatar">{name.slice(0, 2).toUpperCase()}</span>
                <div><strong>{name}</strong></div><span className="igDots">•••</span></header>
              {media}
              <div className="igActions" aria-hidden="true">{icons}</div>
              {captionBlock}
            </>}
          </div>
        </div>
      </div>

      <div className="postReviewSide">
        <header className="postReviewHead">
          <p className="postReviewWhen"><span className={`studioStatus is-${item.status}`}>{STUDIO_STATUS[item.status]}</span>
            <span>{at.weekday}, {at.label} · {at.time}</span></p>
          <h2>{item.title}</h2>
        </header>

        <div className="postReviewBody">
          {item.review_note ? <div className="postReviewLast"><small>Último pedido de ajuste</small><p><Linkified text={item.review_note} /></p></div> : null}
          {decided ? <p className="studioOk">✓ {STUDIO_STATUS[item.status]}. Se quiser mudar algo, peça ajuste.</p> : null}

          <label className="postReviewNote"><span>Seu comentário</span>
            <textarea rows={4} maxLength={1000} value={note} placeholder="O que achou? Se algo precisa mudar, conte aqui: texto, cor, imagem, legenda…"
              onChange={(e) => { setNote(e.target.value); setMissingNote(false); setSent(null); }} aria-invalid={missingNote} />
          </label>
          {missingNote ? <p className="studioError" role="alert">Escreva o que precisa mudar.</p> : null}

          {showThread ? <section className="postReviewRefs" aria-label="Referências">
            <div className="postReviewRefsHead"><span>Referências</span><small>Links ou imagens no estilo que você quer</small></div>
            {refs.length ? <ul>{refs.map((r) => {
              const image = r.kind === "arte" || IMAGE_RE.test(r.url);
              return <li key={r.id} className={image ? "is-image" : ""}>
                <a href={r.url} target="_blank" rel="noopener noreferrer nofollow" title={r.url}>
                  {image ? <img src={r.url} alt="Referência" loading="lazy" /> : <><span className="postReviewRefIcon" aria-hidden="true">↗</span>{host(r.url)}</>}
                </a>
                {r.can_delete ? <button type="button" aria-label="Remover referência" disabled={working} onClick={() => void removeRef(r.id)}>×</button> : null}
              </li>;
            })}</ul> : null}
            <div className="postReviewRefForm">
              <input type="url" inputMode="url" placeholder="Cole um link de referência" value={refUrl}
                onChange={(e) => { setRefUrl(e.target.value); setSideError(null); }} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void addLink(); } }} />
              <button type="button" className="ds-button" disabled={working || !refUrl.trim()} onClick={() => void addLink()}>Adicionar</button>
              <button type="button" className="ds-button" disabled={working} onClick={() => fileRef.current?.click()}>Imagem</button>
              <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" multiple hidden onChange={(e) => void addImages(e.target.files)} />
            </div>
            {refBusy ? <p className="libHint">{refBusy}</p> : null}
          </section> : null}

          {sideError ? <p role="alert" className="studioError">{sideError}</p> : null}
          {error ? <p role="alert" className="studioError">{error}</p> : null}
          {sent ? <p className="studioOk">{sent}</p> : null}

          {showThread && comments.length ? <details className="postReviewThread"><summary>Conversa sobre este post ({comments.length})</summary>
            <ol>{comments.map((c) => <li key={c.id || c.created_at} className={`is-${c.author_side}`}>
              <small>{c.author_side === "mugo" ? "Equipe Mugô" : c.author_name || "Cliente"} · {c.created_at ? when(c.created_at) : "agora"}</small>
              <p><Linkified text={c.body} /></p>
            </li>)}</ol>
          </details> : null}
        </div>

        <footer className="postReviewFoot">
          <div className="postReviewActions">
            {item.status !== "publicado" ? <button type="button" className="ds-button" disabled={working} onClick={() => void askChanges()}>Pedir ajuste</button> : null}
            {!decided ? <button type="button" className="ds-button is-primary" disabled={working} onClick={() => void approve()}>{busy ? "Enviando…" : "Aprovar"}</button> : null}
          </div>
          <p className="libHint">
            A equipe Mugô é avisada na hora.
            {showThread ? <> {" "}<button type="button" className="studioLink" disabled={working || !note.trim()} onClick={() => void sendComment()}>Só enviar o comentário</button></> : null}
          </p>
        </footer>
      </div>
    </div>
  </div>;
}
