import { useEffect, useRef, useState, type FormEvent } from "react";
import { STUDIO_FORMATS, STUDIO_STATUS, localParts, type CalendarItem, type StudioFormat, type StudioStatus } from "../../app/studio";
import type { PostDraft } from "../../app/studioCalendar";
import type { StudioAsset } from "../../app/studioAssets";
import ArtViewer from "./ArtViewer";
import ArtPicker from "./ArtPicker";

const PUBLISHER_URL = "https://business.facebook.com/latest/composer";
const VERTICAL: StudioFormat[] = ["reels", "stories", "video"];
const MAX_ART = 20;

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
  /** Troca a arte da pauta (ordem = slides). */
  onAssets: (assets: StudioAsset[]) => Promise<boolean>;
};

/** Prévia no formato de um post do Instagram + painel de edição e aprovação. */
export default function PostModal({ item, initial, handle, pillars, canManage, busy, error, onClose, onSave, onStatus, onDelete, onAssets }: Props) {
  const [draft, setDraft] = useState<PostDraft>(initial);
  const [captionOpen, setCaptionOpen] = useState(false);
  const [rejectNote, setRejectNote] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [picking, setPicking] = useState(false);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy && !picking) onClose(); };
    window.addEventListener("keydown", onKey);
    dialogRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose, picking]);

  const vertical = VERTICAL.includes(draft.format);
  const when = draft.date ? localParts(`${draft.date}T${draft.time || "12:00"}:00-03:00`) : null;
  const caption = draft.caption_draft || "";
  const shortCaption = caption.length > 125 && !captionOpen ? `${caption.slice(0, 125).trimEnd()}…` : caption;
  const signals = item?.signals;
  const art = item?.assets || [];
  const move = (index: number, delta: number) => {
    const next = [...art]; const [moved] = next.splice(index, 1); next.splice(index + delta, 0, moved);
    void onAssets(next);
  };
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
        <div className={`igMedia ${vertical ? "is-vertical" : ""} is-${draft.format} ${art.length ? "has-art" : ""}`}>
          <span className="igFormat">{STUDIO_FORMATS[draft.format]}</span>
          {art.length ? <ArtViewer assets={art} label="Arte do post" /> : <>
            <p className="igCover">{draft.hook || draft.title || "Gancho do post"}</p>
            {draft.format === "carrossel" ? <span className="igCarouselDots"><i className="on" /><i /><i /><i /></span> : null}
            <span className="igArtNote">Arte ainda não anexada</span>
          </>}
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
          <label>Formato<select value={draft.format} disabled={!canManage} onChange={(e) => set({ format: e.target.value as StudioFormat })}>
            {Object.entries(STUDIO_FORMATS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        </div>
        <label>Pilar<input list="studio-pillars" maxLength={120} value={draft.pillar} disabled={!canManage} onChange={(e) => set({ pillar: e.target.value })} />
          <datalist id="studio-pillars">{pillars.map((p) => <option key={p} value={p} />)}</datalist></label>
        <label>Gancho (primeira frase/cena)<input maxLength={400} value={draft.hook} disabled={!canManage} onChange={(e) => set({ hook: e.target.value })} /></label>
        <label>Legenda<textarea rows={7} maxLength={4000} value={draft.caption_draft} disabled={!canManage} onChange={(e) => set({ caption_draft: e.target.value })} /></label>

        {canManage ? <fieldset className="postArt"><legend>Arte {art.length ? `(${art.length})` : ""}</legend>
          {!item ? <p className="postArtHint">Crie a pauta para anexar a arte.</p> : <>
            {art.length ? <ol className="postArtList">{art.map((a, index) => <li key={a.id}>
              <span className="libThumb">{a.thumb_url ? <img src={a.thumb_url} alt="" /> : <b>{a.kind === "video" ? "▶" : "▢"}</b>}</span>
              <span className="postArtName">{index + 1}. {a.name || (a.kind === "video" ? "Vídeo" : "Imagem")}</span>
              <span className="postArtTools">
                <button type="button" aria-label="Mover para antes" disabled={busy || index === 0} onClick={() => move(index, -1)}>↑</button>
                <button type="button" aria-label="Mover para depois" disabled={busy || index === art.length - 1} onClick={() => move(index, 1)}>↓</button>
                <button type="button" aria-label="Remover da pauta" disabled={busy} onClick={() => void onAssets(art.filter((x) => x.id !== a.id))}>×</button>
              </span>
            </li>)}</ol> : <p className="postArtHint">{draft.format === "carrossel" ? "Escolha os slides na ordem do carrossel." : VERTICAL.includes(draft.format) ? "Anexe o vídeo vertical (1080×1920)." : "Anexe a imagem do post (1080×1350)."}</p>}
            <button type="button" className="ds-button" disabled={busy} onClick={() => setPicking(true)}>{art.length ? "Trocar ou adicionar" : "+ Da Biblioteca"}</button>
          </>}
        </fieldset> : null}

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
        {item?.review_note ? <p className="studioReview">Nota da revisão: {item.review_note}</p> : null}
        {error ? <p role="alert" className="studioError">{error}</p> : null}

        {item?.status === "aprovado" ? <div className="studioPublish">
          <button type="button" onClick={() => void copyCaption()}>{copied ? "Legenda copiada ✓" : "Copiar legenda"}</button>
          <a href={PUBLISHER_URL} target="_blank" rel="noreferrer noopener">Abrir no Meta Business Suite ↗</a>
        </div> : null}

        {rejectNote !== null ? <div className="postReject">
          <label>O que precisa mudar?<textarea rows={3} maxLength={1000} value={rejectNote} onChange={(e) => setRejectNote(e.target.value)} /></label>
          <div className="studioActions"><button type="button" className="ds-button" onClick={() => setRejectNote(null)}>Cancelar</button>
            <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => void onStatus("rejeitado", rejectNote).then(() => setRejectNote(null))}>Rejeitar</button></div>
        </div> : null}

        {canManage ? <div className="postActions">
          {dirty || !item ? <button className="ds-button is-primary" disabled={busy}>{busy ? "Salvando…" : item ? "Salvar alterações" : "Criar pauta"}</button> : null}
          {item && !dirty ? <>
            {item.status !== "aprovado" ? <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => void onStatus("aprovado")}>Aprovar</button> : null}
            {item.status === "rascunho" ? <button type="button" className="ds-button" disabled={busy} onClick={() => void onStatus("em_revisao")}>Enviar p/ revisão</button> : null}
            {item.status !== "rejeitado" && rejectNote === null ? <button type="button" className="ds-button" disabled={busy} onClick={() => setRejectNote(item.review_note || "")}>Rejeitar</button> : null}
            {item.status === "aprovado" || item.status === "rejeitado" ? <button type="button" className="ds-button" disabled={busy} onClick={() => void onStatus("rascunho")}>Reabrir</button> : null}
            <button type="button" className="studioLink" disabled={busy} onClick={() => void onDelete()}>Excluir</button>
          </> : null}
          {dirty && item ? <button type="button" className="ds-button" disabled={busy} onClick={() => setDraft(initial)}>Descartar</button> : null}
        </div> : null}
      </form>
    </div>
    {picking ? <ArtPicker initial={art} max={MAX_ART} onClose={() => setPicking(false)}
      onConfirm={async (assets) => { if (await onAssets(assets)) setPicking(false); }} /> : null}
  </div>;
}
