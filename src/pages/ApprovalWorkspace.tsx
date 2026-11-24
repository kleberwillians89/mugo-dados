import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarDays, Monitor, Smartphone } from "lucide-react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  STUDIO_FORMATS,
  deleteApprovalContent,
  decideCalendarItem,
  getItemHistory,
  getPipeline,
  localParts,
  sendForApproval,
  updateCalendarItem,
  type ItemEvent,
  type PipelineItem,
} from "../app/studio";
import { artSlides } from "../app/artLinks";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import ArtCarousel from "../components/studio/ArtCarousel";
import PostComments from "../components/studio/PostComments";
import "../styles/studio.css";
import "../styles/approval-workspace.css";

export type ApprovalMode = "internal" | "final";
type PreviewMode = "desktop" | "mobile";

const monthKey = (offset = 0) => {
  const now = new Date();
  const date = new Date(now.getFullYear(), now.getMonth() + offset, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
};
const shiftMonth = (month: string, offset: number) => {
  const date = new Date(Number(month.slice(0, 4)), Number(month.slice(5)) - 1 + offset, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
};
const monthLabel = (month: string) => new Date(`${month}-02T12:00:00`).toLocaleDateString("pt-BR", { month: "long", year: "numeric" });
const message = (cause: unknown, fallback: string) => cause instanceof Error && cause.message ? cause.message : fallback;

type Props = {
  mode: ApprovalMode;
  isAgency: boolean;
  canDeleteContent: boolean;
  onOpenCalendar: () => void;
};

export default function ApprovalWorkspace({ mode, isAgency, canDeleteContent, onOpenCalendar }: Props) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "marca";
  const [month, setMonth] = useState(monthKey);
  const [items, setItems] = useState<PipelineItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewMode>("desktop");
  const [note, setNote] = useState("");
  const [history, setHistory] = useState<ItemEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [approvalLink, setApprovalLink] = useState<string | null>(null);

  const stage = mode === "internal" ? "revisao_interna" : "com_cliente";
  const title = mode === "internal" ? "Aprovação Interna" : "Aprovação Final";
  const pending = useMemo(() => items.filter((item) => item.stage === stage), [items, stage]);
  const selected = pending.find((item) => item.id === selectedId) || pending[0] || null;

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const response = await getPipeline(month);
      if (getActiveClientId() !== clientId) return;
      setItems(response.items || []);
    } catch (cause) {
      if (getActiveClientId() !== clientId) return;
      setError(message(cause, "Não foi possível carregar as peças para aprovação."));
      setItems([]);
    } finally {
      if (getActiveClientId() === clientId) setLoading(false);
    }
  }, [clientId, month]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!pending.some((item) => item.id === selectedId)) setSelectedId(pending[0]?.id || null);
  }, [pending, selectedId]);
  useEffect(() => {
    setNote(""); setHistory([]);
    if (!selected || !isAgency) return;
    let alive = true;
    getItemHistory(selected.id).then((response) => { if (alive) setHistory(response.events || []); }).catch(() => { if (alive) setHistory([]); });
    return () => { alive = false; };
  }, [isAgency, selected?.id]);

  async function requestChanges() {
    if (!selected || busy) return;
    const text = note.trim();
    if (!text) { setError("Descreva o ajuste necessário antes de enviar."); return; }
    setBusy(true); setError(null); setNotice(null);
    try {
      if (mode === "internal") await updateCalendarItem(selected.id, { status: "rejeitado", review_note: text });
      else await decideCalendarItem(selected.id, "rejeitado", text);
      setNotice("Ajuste solicitado. A peça saiu desta fila."); setNote("");
      await load();
    } catch (cause) { setError(message(cause, "Não foi possível solicitar o ajuste.")); }
    finally { setBusy(false); }
  }

  async function approve() {
    if (!selected || busy) return;
    setBusy(true); setError(null); setNotice(null); setApprovalLink(null);
    try {
      if (mode === "internal") {
        const response = await sendForApproval({ month: selected.month || month, item_ids: [selected.id] });
        setApprovalLink(response.link || null);
        setNotice("Peça aprovada internamente e enviada para a aprovação final.");
      } else {
        await decideCalendarItem(selected.id, "aprovado", note.trim() || undefined);
        setNotice("Peça aprovada. A decisão foi registrada no Calendário.");
      }
      setNote(""); await load();
    } catch (cause) { setError(message(cause, "Não foi possível registrar a aprovação.")); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!selected || busy || !canDeleteContent) return;
    if (!window.confirm(`Excluir o conteúdo “${selected.title}” da fila de aprovação? O histórico será preservado.`)) return;
    const removedId = selected.id;
    setBusy(true); setError(null); setNotice(null); setApprovalLink(null);
    try {
      await deleteApprovalContent(removedId);
      setItems((current) => current.filter((item) => item.id !== removedId));
      setSelectedId(null); setNote(""); setHistory([]);
      setNotice("Conteúdo excluído. O histórico da peça foi preservado.");
    } catch (cause) { setError(message(cause, "Não foi possível excluir o conteúdo.")); }
    finally { setBusy(false); }
  }

  const controls = <div className="approvalWorkspaceTopActions">
    <button type="button" className="ds-button" onClick={onOpenCalendar}><CalendarDays size={16} aria-hidden="true" /> Calendário</button>
  </div>;

  return <Shell title={title} variant="editorial"><div className="ds-page approvalWorkspacePage">
    <PageHeader company={clientName} title={title} controls={controls} />
    <div className="approvalWorkspaceMonth" aria-label="Período da fila">
      <button type="button" className="ds-button" aria-label="Mês anterior" onClick={() => setMonth((value) => shiftMonth(value, -1))}>‹</button>
      <strong>{monthLabel(month)}</strong>
      <button type="button" className="ds-button" aria-label="Próximo mês" onClick={() => setMonth((value) => shiftMonth(value, 1))}>›</button>
    </div>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {notice ? <p role="status" className="studioOk">{notice}{approvalLink ? <> <a href={approvalLink} target="_blank" rel="noreferrer noopener">Abrir link da aprovação final ↗</a></> : null}</p> : null}
    <div className="approvalWorkspace">
      <aside className="approvalQueue" aria-label="Peças na fila">
        <header><span>Peças na Fila</span><b>{pending.length}</b></header>
        {loading ? <p className="approvalQueueEmpty">Carregando…</p> : null}
        {!loading && !pending.length ? <p className="approvalQueueEmpty">Nenhuma peça aguardando decisão nesta etapa.</p> : null}
        <ol>{pending.map((item) => {
          const when = localParts(item.scheduled_at);
          return <li key={item.id}><button type="button" className={selected?.id === item.id ? "is-active" : ""} onClick={() => { setSelectedId(item.id); setNotice(null); setApprovalLink(null); }}>
            <small>{item.channel || "social"} · {STUDIO_FORMATS[item.format]}</small>
            <strong>{item.title}</strong>
            <span>{when.label} · {when.time}</span>
          </button></li>;
        })}</ol>
      </aside>

      <main className="approvalPreview" aria-label="Visualização da peça">
        <div className="approvalPreviewToolbar" role="group" aria-label="Modo de visualização">
          <button type="button" className={preview === "desktop" ? "is-active" : ""} aria-pressed={preview === "desktop"} onClick={() => setPreview("desktop")}><Monitor size={15} aria-hidden="true" /> Desktop</button>
          <button type="button" className={preview === "mobile" ? "is-active" : ""} aria-pressed={preview === "mobile"} onClick={() => setPreview("mobile")}><Smartphone size={15} aria-hidden="true" /> Mobile</button>
        </div>
        {selected ? <ContentPreview item={selected} mode={preview} /> : <div className="approvalPreviewEmpty"><p>Selecione uma peça pendente para revisar.</p></div>}
      </main>

      <aside className="approvalNotes" aria-label="Notas e comentários">
        <header><span>Notas e comentários</span></header>
        {selected ? <>
          {selected.review_note ? <div className="approvalLastNote"><small>Último pedido de ajuste</small><p>{selected.review_note}</p></div> : null}
          <label><span>Observação da decisão</span><textarea rows={5} maxLength={1000} value={note} onChange={(event) => { setNote(event.target.value); setError(null); }} placeholder="Registre sua orientação para esta peça" /></label>
          <PostComments key={selected.id} itemId={selected.id} clientMode={!isAgency} />
          {isAgency && history.length ? <details className="approvalHistory"><summary>Histórico ({history.length})</summary><ol>{[...history].reverse().map((event) => <li key={event.id}><b>{event.actor_name || (event.actor_side === "cliente" ? "Cliente" : "Equipe Mugô")}</b> {event.action}<small>{new Date(event.created_at).toLocaleString("pt-BR")}</small>{event.detail ? <p>{event.detail}</p> : null}</li>)}</ol></details> : null}
        </> : <p className="approvalQueueEmpty">As notas da peça selecionada aparecem aqui.</p>}
      </aside>
    </div>
    {selected ? <footer className="approvalDecisionBar">
      {canDeleteContent ? <button type="button" className="ds-button" disabled={busy} onClick={() => void remove()}>Excluir conteúdo</button> : null}
      <button type="button" className="ds-button" disabled={busy} onClick={() => void requestChanges()}>Solicitar ajuste</button>
      <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => void approve()}>{busy ? "Salvando…" : "Aprovar agora"}</button>
    </footer> : null}
  </div></Shell>;
}

function ContentPreview({ item, mode }: { item: PipelineItem; mode: PreviewMode }) {
  const slides = artSlides(item.art_url);
  const when = localParts(item.scheduled_at);
  return <article className={`approvalDevice is-${mode}`}>
    <div className="approvalDeviceChrome"><span /><span /><span /></div>
    <header><small>{item.channel || "Social Media"} · {STUDIO_FORMATS[item.format]}</small><strong>{item.title}</strong></header>
    <div className="approvalDeviceMedia">{slides.length ? <ArtCarousel images={slides} /> : <div className="approvalMediaFallback">{item.hook || item.title}</div>}</div>
    <div className="approvalDeviceCopy">
      {item.hook ? <b>{item.hook}</b> : null}
      <p>{item.caption_draft || "Sem legenda cadastrada."}</p>
      <small>{when.weekday}, {when.label} · {when.time}</small>
    </div>
  </article>;
}
