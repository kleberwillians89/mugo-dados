import { importArt, uploadArt } from "../../app/artUpload";
import PostReferences from "./PostReferences";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { AUTO_PUBLISH_CHANNELS, STUDIO_CHANNELS, STUDIO_FORMATS, STUDIO_STATUS, localParts, type CalendarItem, type StudioChannel, type StudioFormat, type StudioStatus } from "../../app/studio";
import { PLATFORM_FORMATS } from "../../app/contentOps";
import type { PostDraft } from "../../app/studioCalendar";
import AiAssist from "./AiAssist";
import PostComments from "./PostComments";
import ArtLink from "./ArtLink";
import ArtFiles from "./ArtFiles";
import ItemHistory from "./ItemHistory";
import Collaborators from "./Collaborators";
import { artList, artSlides, isDriveFolder } from "../../app/artLinks";
import ArtCarousel from "./ArtCarousel";

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
  /** Equipe: abre o envio ao cliente já com esta pauta (link de aprovação + WhatsApp oficial). */
  onSendForApproval?: () => void;
  /** Equipe: valida o agendamento de um post aprovado, na data e horário do post. */
  onConfirmSchedule?: (now?: boolean) => Promise<void>;
  /** Equipe: depois de corrigir o link da arte, devolve a pauta para a fila de publicação. */
  onRetryPublish?: () => Promise<void>;
  /** Business Suite já na Página desta marca (vem da conexão do Instagram). */
  publisherUrl?: string;
};

/** Prévia no formato de um post do Instagram + painel de edição e aprovação. */
export default function PostModal({ item, initial, handle, pillars, canManage, busy, error, onClose, onSave, onStatus, onDelete, clientMode = false, onSendForApproval, onConfirmSchedule, onRetryPublish, publisherUrl }: Props) {
  const [draft, setDraft] = useState<PostDraft>(initial);
  const [dragArt, setDragArt] = useState(false);
  const [ratio, setRatio] = useState<number | null>(null);
  const [linkInput, setLinkInput] = useState("");
  const [importing, setImporting] = useState<number | null>(null);
  const [importNote, setImportNote] = useState<string | null>(null);
  const [captionOpen, setCaptionOpen] = useState(false);
  const [rejectNote, setRejectNote] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  // Arte do Drive (ou link de imagem) vira a imagem grande da prévia; se não carregar, volta a capa com o gancho.
  const [artFailed, setArtFailed] = useState<string | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const slides = artSlides(draft.art_url);
  const folderLink = artList(draft.art_url).some(isDriveFolder);
  const art = slides.length && slides[0] !== artFailed ? slides : null;
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    dialogRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const vertical = VERTICAL.includes(draft.format);
  const channel: StudioChannel = draft.channel || "instagram";
  const channelLabel = STUDIO_CHANNELS[channel];
  // Só o Instagram publica sozinho; nas outras plataformas o agendamento lembra a equipe de publicar à mão.
  const autoPublish = AUTO_PUBLISH_CHANNELS.includes((item?.channel || "instagram") as StudioChannel);
  const formatsFor = PLATFORM_FORMATS[channel] || (Object.keys(STUDIO_FORMATS) as StudioFormat[]);
  const when = draft.date ? localParts(`${draft.date}T${draft.time || "12:00"}:00-03:00`) : null;
  const caption = draft.caption_draft || "";
  const shortCaption = caption.length > 125 && !captionOpen ? `${caption.slice(0, 125).trimEnd()}…` : caption;
  const signals = item?.signals;
  const set = (patch: Partial<PostDraft>) => setDraft((d) => ({ ...d, ...patch }));
  /** Traz a arte de um link do Drive/Canva. index = troca o link existente nessa posição; sem index = acrescenta no fim. */
  async function bringFromLink(url: string, index?: number) {
    if (!url.trim() || uploading || importing !== null) return;
    setUploadError(null); setImportNote(null); setImporting(index ?? -1);
    try {
      const out = await importArt(item?.id || null, url);
      setDraft((d) => {
        const list = artList(d.art_url);
        if (index !== undefined && index >= 0 && index < list.length) list[index] = out.public_url; else list.push(out.public_url);
        return { ...d, art_url: list.slice(0, 12).join("\n") };
      });
      if (index === undefined) setLinkInput("");
      setImportNote(out.note);
    } catch (cause) { setUploadError(cause instanceof Error ? cause.message : "Não foi possível trazer a arte do link."); }
    finally { setImporting(null); }
  }

  /** Sobe a arte (antes ou depois de a pauta existir) e acrescenta os links na ordem dos slides. */
  async function sendArt(files: File[]) {
    if (!files.length || uploading) return;
    setUploadError(null);
    try {
      const links: string[] = [];
      for (const [i, file] of files.entries()) { setUploading(`Enviando ${i + 1} de ${files.length}…`); links.push(await uploadArt(item?.id || null, file)); }
      setDraft((d) => ({ ...d, art_url: [...artList(d.art_url), ...links].slice(0, 12).join("\n") }));
    } catch (cause) { setUploadError(cause instanceof Error ? cause.message : "Não foi possível enviar a arte."); }
    finally { setUploading(null); }
  }

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
          <div><strong>{handle.slice(1)}{draft.collaborators?.length && draft.format !== "stories" ? <> e {draft.collaborators.length === 1 ? draft.collaborators[0] : `${draft.collaborators.length} outros`}</> : null}</strong>{draft.format === "reels" ? <small>Áudio original</small> : null}</div><span className="igDots">•••</span></header>
        <div className={`igMedia ${vertical ? "is-vertical" : ""} is-${draft.format}${art ? " has-art" : ""}`}
          style={art && !vertical && ratio ? { aspectRatio: String(ratio) } : undefined}>
          <span className="igFormat">{STUDIO_FORMATS[draft.format]}</span>
          {art ? <ArtCarousel images={art} onBroken={() => setArtFailed(art[0])} onRatio={setRatio} />
            : folderLink ? <p className="igCover igCoverWarn">Link de <b>pasta</b> do Drive não mostra a arte.<small>Use o link de cada arquivo ou envie o arquivo aqui do lado.</small></p>
            : <p className="igCover">{draft.hook || draft.title || "Gancho do post"}</p>}
          {draft.format === "carrossel" && !art ? <span className="igCarouselDots"><i className="on" /><i /><i /><i /></span> : null}
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
          {item?.origin === "matriz" ? <span className="studioChip">Da Matriz de conteúdo</span> : null}
          {channel !== "instagram" ? <span className={`studioChip is-platform is-${channel}`}>{channelLabel}</span> : null}
        </div>
        <label>Pauta<input required maxLength={200} value={draft.title} disabled={!canManage} onChange={(e) => set({ title: e.target.value })} /></label>
        <div className="studioRow">
          <label>Data<input type="date" required value={draft.date} disabled={!canManage} onChange={(e) => set({ date: e.target.value })} /></label>
          <label>Horário<input type="time" required value={draft.time} disabled={!canManage} onChange={(e) => set({ time: e.target.value })} /></label>
          <label>Formato<select value={draft.format} disabled={!canManage || clientMode} onChange={(e) => set({ format: e.target.value as StudioFormat })}>
            {[...new Set([draft.format, ...formatsFor])].map((k) => <option key={k} value={k}>{STUDIO_FORMATS[k]}</option>)}</select></label>
        </div>
        {canManage && !clientMode ? <label>Plataforma<select value={channel} onChange={(e) => {
          const next = e.target.value as StudioChannel; const allowed = PLATFORM_FORMATS[next];
          set({ channel: next, format: allowed.includes(draft.format) ? draft.format : allowed[0] });
        }}>{Object.entries(STUDIO_CHANNELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label> : null}
        {channel !== "instagram" && canManage && !clientMode ? <small className="postArtHint">{channelLabel} não publica sozinho pelo Mugoverso: depois da aprovação, agende para a equipe ser lembrada na hora e publique à mão.</small> : null}
        <label>Pilar<input list="studio-pillars" maxLength={120} value={draft.pillar} disabled={!canManage || clientMode} onChange={(e) => set({ pillar: e.target.value })} />
          <datalist id="studio-pillars">{pillars.map((p) => <option key={p} value={p} />)}</datalist></label>
        <label>Gancho (primeira frase/cena)<input maxLength={400} value={draft.hook} disabled={!canManage} onChange={(e) => set({ hook: e.target.value })} /></label>
        <label>Legenda<textarea rows={7} maxLength={4000} value={draft.caption_draft} disabled={!canManage} onChange={(e) => set({ caption_draft: e.target.value })} /></label>
        {item?.script || item?.visual_idea ? <details className="postFromMatrix" open>
          <summary>Criado na Matriz</summary>
          {item.script ? <div><b>Roteiro</b><p>{item.script}</p></div> : null}
          {item.visual_idea ? <div><b>Ideia de imagem</b><p>{item.visual_idea}</p></div> : null}
        </details> : null}
        {canManage && !clientMode && channel === "instagram" ? <Collaborators value={draft.collaborators || []} onChange={(collaborators) => set({ collaborators })}
          disabled={busy} isStory={draft.format === "stories"} /> : null}
        {canManage && !clientMode ? <div className="postArt">
          <span className="postArtTitle">Arte do post {artList(draft.art_url).length ? <em>{artList(draft.art_url).length} arquivo{artList(draft.art_url).length > 1 ? "s" : ""}</em> : null}</span>
          <label className={`postArtDrop${dragArt ? " is-drag" : ""}${uploading ? " is-busy" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragArt(true); }} onDragLeave={() => setDragArt(false)}
            onDrop={(e) => { e.preventDefault(); setDragArt(false); void sendArt(Array.from(e.dataTransfer.files || [])); }}>
            <b>{uploading ? uploading : "Arraste a arte aqui ou clique para escolher"}</b>
            <small>Imagem (JPG/PNG) ou vídeo (MP4/MOV) · no carrossel, envie os slides na ordem · é o formato que publica sozinho no Instagram</small>
            <input type="file" multiple accept="image/*,video/mp4,video/quicktime" disabled={Boolean(uploading) || busy} onChange={(e) => {
              const files = Array.from(e.target.files || []); e.target.value = ""; void sendArt(files);
            }} />
          </label>
          <div className="postArtFromLink">
            <input type="url" value={linkInput} placeholder="ou cole o link do Google Drive (arquivo) ou do Canva" aria-label="Link da arte no Drive ou Canva"
              onChange={(e) => setLinkInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void bringFromLink(linkInput); } }} />
            <button type="button" className="ds-button is-primary" disabled={!linkInput.trim() || importing !== null || Boolean(uploading) || busy}
              onClick={() => void bringFromLink(linkInput)}>{importing === -1 ? "Trazendo…" : "Trazer arte"}</button>
          </div>
          {uploadError ? <small className="studioError">{uploadError}</small> : null}
          {importNote ? <small className="postArtHint">{importNote}</small> : null}
          <ArtFiles value={draft.art_url} disabled={Boolean(uploading) || busy || importing !== null} onChange={(art_url) => set({ art_url })}
            onImport={(url, i) => void bringFromLink(url, i)} importing={importing} />
          {item && (draft.art_url || "") !== (initial.art_url || "") ? <small className="postArtHint is-pending">A arte mudou. Clique em <b>Salvar alterações</b>, aqui embaixo, para valer.</small> : null}
          <details className="postArtLink" open={Boolean(draft.art_url) && !artList(draft.art_url).every((u) => u.includes("/storage/v1/object/public/"))}>
            <summary>editar os links à mão</summary>
            <textarea rows={Math.min(6, Math.max(2, (draft.art_url || "").split("\n").length + 1))} maxLength={1000} placeholder="https://drive.google.com/file/d/… (um link por linha, na ordem dos slides)"
              value={draft.art_url || ""} onChange={(e) => set({ art_url: e.target.value })} aria-label="Link da arte" />
          </details>
          {folderLink ? <p className="postArtWarn">Esse é o link de uma <b>pasta</b> do Drive: não aparece na prévia, o cliente não vê a arte e não publica sozinho. No Drive, clique com o botão direito no <b>arquivo</b> → Compartilhar → Copiar link (deixe como "qualquer pessoa com o link"). Ou baixe e envie o arquivo aqui em cima.</p> : null}
          {!item && artList(draft.art_url).length ? <small className="postArtHint">A arte já subiu. Ela fica salva na pauta quando você clicar em <b>Criar pauta</b>.</small> : null}
        </div> : null}
        <ArtLink url={artList(draft.art_url)[0] || null} preview={!art} count={artList(draft.art_url).length} />

        {canManage && !clientMode ? <AiAssist draft={draft} disabled={busy} itemId={item?.id} onApply={(patch) => set(patch)} /> : null}
        {item?.client_edited_at ? <p className="postEdited">Editado pelo cliente em {new Date(item.client_edited_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}{item.client_edited_fields?.length ? ` (${item.client_edited_fields.map((f) => ({ title: "título", hook: "gancho", caption_draft: "legenda", scheduled_at: "data" } as Record<string, string>)[f] || f).join(", ")})` : ""}. {clientMode ? "A equipe Mugô já foi avisada." : "Confira antes de publicar."}</p> : null}


        {item && (item.rationale || signals) ? <details className="postWhy" open>
          <summary>Por que esta pauta, neste dia</summary>
          {item.rationale ? <p>{item.rationale}</p> : null}
          <ul className="studioSignals">
            {signals?.seasonal ? <li>📅 {signals.seasonal}</li> : null}
            {signals?.basis?.hours ? <li>⏱ Melhor faixa: {signals.basis.hours}{signals.basis.slot_reach_index ? ` (alcance ${signals.basis.slot_reach_index.toLocaleString("pt-BR")}x a média)` : ""}{signals.basis.confidence ? ` · confiança ${signals.basis.confidence}` : ""}</li> : null}
            {signals?.trend ? <li>🔥 Em alta: <a href={signals.trend.source_url} target="_blank" rel="noreferrer noopener">{signals.trend.topic}</a></li> : null}
            {signals?.palavras_evitar_encontradas?.length ? <li className="is-warning">⚠ Palavra a evitar: {signals.palavras_evitar_encontradas.join(", ")}</li> : null}
            {(signals?.fora_da_marca || []).map((g) => <li key={`${g.type}:${g.text}`} className="is-warning">⚠ {g.fix}</li>)}
          </ul>
        </details> : null}
        {item && canManage && !clientMode ? <ItemHistory itemId={item.id} refreshKey={`${item.updated_at || ""}:${item.status}`} /> : null}
        {item?.boost ? <p className="postBoost">⚡ Impulsionar de {item.boost.start.slice(8, 10)}/{item.boost.start.slice(5, 7)} a {item.boost.end.slice(8, 10)}/{item.boost.end.slice(5, 7)} com {item.boost.budget.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 })} (plano do Mídia On). {item.boost.why}.</p> : null}
        {item?.review_note ? <p className="studioReview">Nota da revisão: {item.review_note}</p> : null}
        {error ? <p role="alert" className="studioError">{error}</p> : null}

        {item?.status === "aprovado" || item?.status === "publicado" ? <div className="studioPublish">
          <button type="button" onClick={() => void copyCaption()}>{copied ? "Legenda copiada ✓" : "Copiar legenda"}</button>
          {channel === "instagram" || channel === "facebook" ? <a href={publisherUrl || PUBLISHER_URL} target="_blank" rel="noreferrer noopener">Abrir no Meta Business Suite ↗</a> : null}
        </div> : null}

        {rejectNote !== null ? <div className="postReject">
          <label>O que precisa mudar?<textarea rows={3} maxLength={1000} value={rejectNote} onChange={(e) => setRejectNote(e.target.value)} /></label>
          <div className="studioActions"><button type="button" className="ds-button" onClick={() => setRejectNote(null)}>Cancelar</button>
            <button type="button" className="ds-button is-primary" disabled={busy || (clientMode && !rejectNote.trim())} onClick={() => void onStatus("rejeitado", rejectNote).then(() => setRejectNote(null))}>{clientMode ? "Enviar pedido de ajuste" : "Rejeitar"}</button></div>
        </div> : null}

        {item ? <PostReferences itemId={item.id} isAgency={!clientMode} /> : null}
        {item ? <PostComments itemId={item.id} clientMode={clientMode} /> : null}
        {canManage && clientMode && item ? <div className="postActions">
          {dirty ? <button className="ds-button is-primary" disabled={busy}>{busy ? "Salvando…" : "Salvar alterações"}</button> : <>
            {item.status !== "aprovado" && item.status !== "publicado" ? <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => void onStatus("aprovado")}>Aprovar</button> : null}
            {item.status !== "publicado" && rejectNote === null ? <button type="button" className="ds-button" disabled={busy} onClick={() => setRejectNote("")}>Pedir ajuste</button> : null}
          </>}
          {dirty ? <button type="button" className="ds-button" disabled={busy} onClick={() => setDraft(initial)}>Descartar</button> : null}
        </div> : null}
        {canManage && !clientMode && item && !dirty && item.status === "aprovado" && !item.schedule_confirmed_at ? (autoPublish ? <p className="postPublishWarn">
          Aprovado, mas <b>ainda não vai para o Instagram</b>. Clique em <b>{new Date(item.scheduled_at).getTime() > Date.now() ? "Agendar" : "Publicar agora"}</b> para sair sozinho.</p>
          : <p className="postPublishWarn">Aprovado. <b>{channelLabel} não publica sozinho</b>: agende para a equipe ser lembrada na hora, ou marque <b>Já publiquei à mão</b>.</p>) : null}
        {canManage && !clientMode && item && item.status === "publicado" && !item.publish_status ? <p className="postPublishWarn is-muted">
          Marcado como publicado à mão: o Mugoverso não enviou este post ao {channelLabel}.</p> : null}
        {canManage && !clientMode ? <div className="postActions">
          {dirty || !item ? <button className="ds-button is-primary" disabled={busy}>{busy ? "Salvando…" : item ? "Salvar alterações" : "Criar pauta"}</button> : null}
          {item && !dirty ? <>
            {onSendForApproval && ["rascunho", "em_revisao", "rejeitado"].includes(item.status) ? <button type="button" className="ds-button is-primary" disabled={busy} onClick={onSendForApproval}>Enviar para o cliente aprovar</button> : null}
            {onConfirmSchedule && item.status === "aprovado" && !item.schedule_confirmed_at && new Date(item.scheduled_at).getTime() > Date.now() ? <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => void onConfirmSchedule(false)}>
              Agendar para {new Date(item.scheduled_at).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</button> : null}
            {onConfirmSchedule && autoPublish && item.status === "aprovado" && !item.schedule_confirmed_at ? <button type="button" className={`ds-button${new Date(item.scheduled_at).getTime() > Date.now() ? "" : " is-primary"}`} disabled={busy}
              onClick={() => { if (window.confirm("Publicar agora no Instagram? O post sai em até 5 minutos.")) void onConfirmSchedule(true); }}>Publicar agora</button> : null}
            {item.status === "aprovado" && item.schedule_confirmed_at && !item.publish_status ? <span className="studioOk">✓ Agendado para {new Date(item.scheduled_at).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}: {autoPublish ? "publica sozinho no Instagram" : `na hora fica marcado para publicar à mão no ${channelLabel}`}</span> : null}
            {item.publish_status === "publicado" && item.published_permalink ? <a className="studioOk" href={item.published_permalink} target="_blank" rel="noreferrer noopener">✓ Publicado no Instagram ↗</a> : null}
            {item.publish_status === "simulado" ? <span className="libHint">Publicação simulada (IG_PUBLISH_ENABLED desligado).</span> : null}
            {item.publish_status === "falhou" || item.publish_status === "manual" ? <span className="studioError">{item.publish_status === "manual" ? "Publicação manual: " : "Falhou: "}{item.publish_error}</span> : null}
            {onRetryPublish && autoPublish && (item.publish_status === "falhou" || item.publish_status === "manual") ? <button type="button" className="ds-button" disabled={busy} onClick={() => void onRetryPublish()}>Tentar de novo</button> : null}
            {item.status !== "aprovado" && item.status !== "publicado" ? <button type="button" className="ds-button" disabled={busy} onClick={() => void onStatus("aprovado")}>Aprovar</button> : null}
            {item.status === "aprovado" && (!item.schedule_confirmed_at || item.publish_status === "manual") ? <button type="button" className="studioLink" disabled={busy}
              onClick={() => { if (window.confirm(`Isso NÃO publica no ${channelLabel}: só marca no Mugoverso que você já publicou à mão. Continuar?`)) void onStatus("publicado"); }}>Já publiquei à mão</button> : null}
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
