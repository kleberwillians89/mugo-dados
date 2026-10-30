import { useEffect, useRef, useState, type FormEvent } from "react";
import { STUDIO_FORMATS, STUDIO_STATUS, localParts, type CalendarItem, type StudioFormat, type StudioStatus } from "../../app/studio";
import type { PostDraft } from "../../app/studioCalendar";
import AiAssist from "./AiAssist";

const PUBLISHER_URL = "https://business.facebook.com/latest/composer";
const VERTICAL: StudioFormat[] = ["reels", "stories", "video"];

type Props = {
  item: CalendarItem | null;          // null = nova pauta
  initial: PostDraft;
  handle: string;
  pillars: string[];
  canManage: boolean;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSave: (draft: PostDraft) => Promise<boolean>;
  onStatus: (status: StudioStatus, note?: string) => Promise<void>;
  onDelete: () => Promise<void>;
  /** Cliente: edita texto e data, aprova ou pede ajuste; formato, pilar, IA, publicar e excluir ficam com a Mugô. */
  clientMode?: boolean;
  /** Troca a arte da pauta (ordem = slides). */
};

/** Prévia no formato de um post do Instagram + painel de edição e aprovação. */
export default function PostModal({ item, initial, handle, pillars, canManage, busy, error, onClose, onSave, onStatus, onDelete, clientMode = false }: Props) {
  const [draft, setDraft] = useState<PostDraft>(initial);
  const [captionOpen, setCaptionOpen] = useState(false);
  const [rejectNote, setRejectNote] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    dialogRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const vertical = VERTICAL.includes(draft.format);
  const when = draft.date ? localParts(`${draft.date}T${draft.time || "12:00"}:00-03:00`) : null;
  const caption = draft.caption_draft || "";
  const shortCaption = caption.length > 125 && !captionOpen ? `${caption.slice(0, 125).trimEnd()}…` : caption;
  const signals = item?.signals;
  const set = (patch: Partial<PostDraft>) => setDraft((d) => ({ ...d, ...patch }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (await onSave(draft) && !item) onClose();
  }

  async function copyCaption() {
    try { await navigator.clipboard.writeText([draft.hook, draft.caption_draft].filter(Boolean).join("\n\n") || draft.title); setCopied(true); window.setTimeout(() => setCopied(false), 2500); }
    catch { /* o texto continua visível para copiar à mão */ }
  }

  return <div className="postModalBackdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
    <div className="postModal" role="dialog" aria-modal="true" aria-label={item ? item.title : "Nova pauta"} tabIndex={-1} ref={dialogRef}>
      <button type="button" className="postModalClose" aria-label="Fechar" onClick={onClose} disabled={busy}>×</button>

      <section className="igPreview" aria-label="Prévia do post">
        <header className="igHeader"><span className="igAvatar">{handle.slice(1, 3).toUpperCase()}</span>
          <div><strong>{handle.slice(1)}</strong>{draft.format === "reels" ? <small>Áudio original</small> : null}</div><span className="igDots">•••</span></header>
        <div className={`igMedia ${vertical ? "is-vertical" : ""} is-${draft.format}`}>
          <span className="igFormat">{STUDIO_FORMATS[draft.format]}</span>
          <p className="igCover">{draft.hook || draft.title || "Gancho do post"}</p>
          {draft.format === "carrossel" ? <span className="igCarouselDots"><i className="on" /><i /><i /><i /></span> : null}
        </div>
        <div className="igActions" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M12 21s-7.5-4.6-9.6-9.2C1 8.6 3 5 6.4 5c2 0 3.4 1.1 4.1 2.4h3C14.2 6.1 15.6 5 17.6 5 21 5 23 8.6 21.6 11.8 19.5 16.4 12 21 12 21z" /></svg>
          <svg viewBox="0 0 24 24"><path d="M20.5 12a8.5 8.5 0 1 1-3.1-6.6L21 4l-1 4.1A8.4 8.4 0 0 1 20.5 12z" /></svg>
          <svg viewBox="0 0 24 24"><path d="M22 3 2 10.5l7.5 3L22 3zM9.5 13.5 12 21l10-18" /></svg>
          <svg className="igSave" viewBox="0 0 24 24"><path d="M6 3h12v18l-6-4.5L6 21z" /></svg>
        </div>
        <div className="igCaption">
          <p><strong>{handle.slice(1)}</strong> {shortCaption || <em>Sem legenda ainda.</em>}
            {caption.length > 125 ? <button type="button" onClick={() => setCaptionOpen(!captionOpen)}>{captionOpen ? " menos" : " mais"}</button> : null}</p>
          {when ? <small>{when.weekday}, {when.label} · {when.time}</small> : null}
        </div>
      </section>

      <form className="postPanel" onSubmit={submit}>
        <div className="postPanelHead">
          {item ? <span className={`studioStatus is-${item.status}`}>{STUDIO_STATUS[item.status]}</span> : <span className="studioStatus">Nova pauta</span>}
          {item?.origin === "ia" ? <span className="studioChip">Sugerida pela IA</span> : null}
        </div>
        <label>Pauta<input required maxLength={200} value={draft.title} disabled={!canManage} onChange={(e) => set({ title: e.target.value })} /></label>
        <div className="studioRow">
          <label>Data<input type="date" required value={draft.date} disabled={!canManage} onChange={(e) => set({ date: e.target.value })} /></label>
          <label>Horário<input type="time" required value={draft.time} disabled={!canManage} onChange={(e) => set({ time: e.target.value })} /></label>
          <label>Formato<select value={draft.format} disabled={!canManage || clientMode} onChange={(e) => set({ format: e.target.value as StudioFormat })}>
            {Object.entries(STUDIO_FORMATS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        </div>
        <label>Pilar<input list="studio-pillars" maxLength={120} value={draft.pillar} disabled={!canManage || clientMode} onChange={(e) => set({ pillar: e.target.value })} />
          <datalist id="studio-pillars">{pillars.map((p) => <option key={p} value={p} />)}</datalist></label>
        <label>Gancho (primeira frase/cena)<input maxLength={400} value={draft.hook} disabled={!canManage} onChange={(e) => set({ hook: e.target.value })} /></label>
        <label>Legenda<textarea rows={7} maxLength={4000} value={draft.caption_draft} disabled={!canManage} onChange={(e) => set({ caption_draft: e.target.value })} /></label>

        {canManage && !clientMode ? <AiAssist draft={draft} disabled={busy} onApply={(patch) => set(patch)} /> : null}
        {item?.client_edited_at ? <p className="postEdited">Editado pelo cliente em {new Date(item.client_edited_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}{item.client_edited_fields?.length ? ` (${item.client_edited_fields.map((f) => ({ title: "título", hook: "gancho", caption_draft: "legenda", scheduled_at: "data" } as Record<string, string>)[f] || f).join(", ")})` : ""}. {clientMode ? "A equipe Mugô já foi avisada." : "Confira antes de publicar."}</p> : null}


        {item && (item.rationale || signals) ? <details className="postWhy" open>
          <summary>Por que esta pauta, neste dia</summary>
          {item.rationale ? <p>{item.rationale}</p> : null}
          <ul className="studioSignals">
            {signals?.seasonal ? <li>📅 {signals.seasonal}</li> : null}
            {signals?.basis?.hours ? <li>⏱ Melhor faixa: {signals.basis.hours}{signals.basis.slot_reach_index ? ` (alcance ${signals.basis.slot_reach_index.toLocaleString("pt-BR")}x a média)` : ""}{signals.basis.confidence ? ` · confiança ${signals.basis.confidence}` : ""}</li> : null}
            {signals?.trend ? <li>🔥 Em alta: <a href={signals.trend.source_url} target="_blank" rel="noreferrer noopener">{signals.trend.topic}</a></li> : null}
            {signals?.palavras_evitar_encontradas?.length ? <li className="is-warning">⚠ Palavra a evitar: {signals.palavras_evitar_encontradas.join(", ")}</li> : null}
          </ul>
        </details> : null}
        {item?.boost ? <p className="postBoost">⚡ Impulsionar de {item.boost.start.slice(8, 10)}/{item.boost.start.slice(5, 7)} a {item.boost.end.slice(8, 10)}/{item.boost.end.slice(5, 7)} com {item.boost.budget.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 })} (plano do Mídia On). {item.boost.why}.</p> : null}
        {item?.review_note ? <p className="studioReview">Nota da revisão: {item.review_note}</p> : null}
        {error ? <p role="alert" className="studioError">{error}</p> : null}

        {item?.status === "aprovado" || item?.status === "publicado" ? <div className="studioPublish">
          <button type="button" onClick={() => void copyCaption()}>{copied ? "Legenda copiada ✓" : "Copiar legenda"}</button>
          <a href={PUBLISHER_URL} target="_blank" rel="noreferrer noopener">Abrir no Meta Business Suite ↗</a>
        </div> : null}

        {rejectNote !== null ? <div className="postReject">
          <label>O que precisa mudar?<textarea rows={3} maxLength={1000} value={rejectNote} onChange={(e) => setRejectNote(e.target.value)} /></label>
          <div className="studioActions"><button type="button" className="ds-button" onClick={() => setRejectNote(null)}>Cancelar</button>
            <button type="button" className="ds-button is-primary" disabled={busy || (clientMode && !rejectNote.trim())} onClick={() => void onStatus("rejeitado", rejectNote).then(() => setRejectNote(null))}>{clientMode ? "Enviar pedido de ajuste" : "Rejeitar"}</button></div>
        </div> : null}

        {canManage && clientMode && item ? <div className="postActions">
          {dirty ? <button className="ds-button is-primary" disabled={busy}>{busy ? "Salvando…" : "Salvar alterações"}</button> : <>
            {item.status !== "aprovado" && item.status !== "publicado" ? <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => void onStatus("aprovado")}>Aprovar</button> : null}
            {item.status !== "publicado" && rejectNote === null ? <button type="button" className="ds-button" disabled={busy} onClick={() => setRejectNote("")}>Pedir ajuste</button> : null}
          </>}
          {dirty ? <button type="button" className="ds-button" disabled={busy} onClick={() => setDraft(initial)}>Descartar</button> : null}
        </div> : null}
        {canManage && !clientMode ? <div className="postActions">
          {dirty || !item ? <button className="ds-button is-primary" disabled={busy}>{busy ? "Salvando…" : item ? "Salvar alterações" : "Criar pauta"}</button> : null}
          {item && !dirty ? <>
            {item.status !== "aprovado" && item.status !== "publicado" ? <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => void onStatus("aprovado")}>Aprovar</button> : null}
            {item.status === "aprovado" ? <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => void onStatus("publicado")}>Marcar como publicado</button> : null}
            {item.status === "rascunho" ? <button type="button" className="ds-button" disabled={busy} onClick={() => void onStatus("em_revisao")}>Enviar p/ revisão</button> : null}
            {item.status !== "rejeitado" && item.status !== "publicado" && rejectNote === null ? <button type="button" className="ds-button" disabled={busy} onClick={() => setRejectNote(item.review_note || "")}>Rejeitar</button> : null}
            {item.status === "aprovado" || item.status === "rejeitado" || item.status === "publicado" ? <button type="button" className="ds-button" disabled={busy} onClick={() => void onStatus("rascunho")}>Reabrir</button> : null}
            <button type="button" className="studioLink" disabled={busy} onClick={() => void onDelete()}>Excluir</button>
          </> : null}
          {dirty && item ? <button type="button" className="ds-button" disabled={busy} onClick={() => setDraft(initial)}>Descartar</button> : null}
        </div> : null}
      </form>
    </div>
  </div>;
}
