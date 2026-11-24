import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarDays, Monitor, Smartphone } from "lucide-react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  CRM_UNAVAILABLE_TEXT,
  TASK_EVENT,
  dueInfo,
  listCrmTasks,
  taskApproval,
  taskHistory,
  updateTask,
  type CrmTask,
} from "../app/crm";
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
type QueueEntry =
  | { key: string; kind: "calendar"; item: PipelineItem }
  | { key: string; kind: "task"; task: CrmTask };
type HistoryEntry = { id: string; action: string; detail: string | null; actor_name: string | null; actor_side: "mugo" | "cliente" | "sistema"; created_at: string };

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
  canDeleteCalendarContent: boolean;
  canDeleteTaskContent: boolean;
  onOpenCalendar: () => void;
};

export default function ApprovalWorkspace({ mode, isAgency, canDeleteCalendarContent, canDeleteTaskContent, onOpenCalendar }: Props) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "marca";
  const [month, setMonth] = useState(monthKey);
  const [items, setItems] = useState<PipelineItem[]>([]);
  const [tasks, setTasks] = useState<CrmTask[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewMode>("desktop");
  const [note, setNote] = useState("");
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [approvalLink, setApprovalLink] = useState<string | null>(null);

  const stage = mode === "internal" ? "revisao_interna" : "com_cliente";
  const title = mode === "internal" ? "Aprovação Interna" : "Aprovação Final";
  const pending = useMemo<QueueEntry[]>(() => [
    ...items.filter((item) => item.stage === stage).map((item) => ({ key: `calendar:${item.id}`, kind: "calendar" as const, item })),
    ...(mode === "internal" ? tasks.filter((task) => task.status === "internal_review" && !task.calendar_item_id)
      .map((task) => ({ key: `task:${task.id}`, kind: "task" as const, task })) : []),
  ], [items, mode, stage, tasks]);
  const selected = pending.find((entry) => entry.key === selectedId) || pending[0] || null;

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    const [calendarResult, taskResult] = await Promise.allSettled([
      getPipeline(month),
      mode === "internal" ? listCrmTasks("internal_review") : Promise.resolve(null),
    ]);
    if (getActiveClientId() !== clientId) return;
    const errors: string[] = [];
    if (calendarResult.status === "fulfilled") setItems(calendarResult.value.items || []);
    else { setItems([]); errors.push(message(calendarResult.reason, "Não foi possível carregar as peças para aprovação.")); }
    if (taskResult.status === "fulfilled" && taskResult.value) {
      if (taskResult.value.available) setTasks(taskResult.value.tasks || []);
      else { setTasks([]); errors.push(CRM_UNAVAILABLE_TEXT[taskResult.value.reason]); }
    } else if (taskResult.status === "rejected") {
      setTasks([]); errors.push(message(taskResult.reason, "Não foi possível carregar os jobs para aprovação."));
    } else setTasks([]);
    setError(errors.length ? errors.join(" ") : null);
    setLoading(false);
  }, [clientId, mode, month]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!pending.some((entry) => entry.key === selectedId)) setSelectedId(pending[0]?.key || null);
  }, [pending, selectedId]);
  useEffect(() => {
    setNote(""); setHistory([]);
    if (!selected || (selected.kind === "calendar" && !isAgency)) return;
    let alive = true;
    const request = selected.kind === "calendar"
      ? getItemHistory(selected.item.id).then((response) => (response.events || []).map((event: ItemEvent) => ({
        id: event.id, action: event.action, detail: event.detail, actor_name: event.actor_name,
        actor_side: event.actor_side, created_at: event.created_at,
      })))
      : taskHistory(selected.task.id).then((response) => (response.events || []).map((event) => ({
        id: event.id, action: TASK_EVENT[event.kind].toLowerCase(), detail: event.comment,
        actor_name: event.actor_name, actor_side: event.actor_side, created_at: event.created_at,
      })));
    request.then((events) => { if (alive) setHistory(events); }).catch(() => { if (alive) setHistory([]); });
    return () => { alive = false; };
  }, [isAgency, selected?.key]);

  async function requestChanges() {
    if (!selected || busy) return;
    const text = note.trim();
    if (!text) { setError("Descreva o ajuste necessário antes de enviar."); return; }
    setBusy(true); setError(null); setNotice(null);
    try {
      if (selected.kind === "task") await taskApproval(selected.task.id, "internal_changes", text);
      else if (mode === "internal") await updateCalendarItem(selected.item.id, { status: "rejeitado", review_note: text });
      else await decideCalendarItem(selected.item.id, "rejeitado", text);
      setNotice(`Ajuste solicitado. ${selected.kind === "task" ? "O job" : "A peça"} saiu desta fila.`); setNote("");
      await load();
    } catch (cause) { setError(message(cause, "Não foi possível solicitar o ajuste.")); }
    finally { setBusy(false); }
  }

  async function approve() {
    if (!selected || busy) return;
    setBusy(true); setError(null); setNotice(null); setApprovalLink(null);
    try {
      if (selected.kind === "task") {
        await taskApproval(selected.task.id, "internal_approve");
        setNotice(selected.task.visible_to_client && selected.task.needs_client_approval !== false
          ? "Job aprovado internamente e enviado para a aprovação do cliente."
          : "Job aprovado internamente e concluído.");
      } else if (mode === "internal") {
        const response = await sendForApproval({ month: selected.item.month || month, item_ids: [selected.item.id] });
        setApprovalLink(response.link || null);
        setNotice("Peça aprovada internamente e enviada para a aprovação final.");
      } else {
        await decideCalendarItem(selected.item.id, "aprovado", note.trim() || undefined);
        setNotice("Peça aprovada. A decisão foi registrada no Calendário.");
      }
      setNote(""); await load();
    } catch (cause) { setError(message(cause, "Não foi possível registrar a aprovação.")); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!selected || busy) return;
    const allowed = selected.kind === "calendar" ? canDeleteCalendarContent : canDeleteTaskContent;
    if (!allowed) return;
    const title = selected.kind === "calendar" ? selected.item.title : selected.task.title;
    if (!window.confirm(`Excluir o conteúdo “${title}” da fila de aprovação? O histórico será preservado.`)) return;
    setBusy(true); setError(null); setNotice(null); setApprovalLink(null);
    try {
      if (selected.kind === "calendar") {
        await deleteApprovalContent(selected.item.id);
        setItems((current) => current.filter((item) => item.id !== selected.item.id));
        setNotice("Conteúdo excluído. O histórico da peça foi preservado.");
      } else {
        await updateTask(selected.task.id, { status: "cancelled" });
        setTasks((current) => current.filter((task) => task.id !== selected.task.id));
        setNotice("Conteúdo excluído da fila. O job foi cancelado e seu histórico foi preservado.");
      }
      setSelectedId(null); setNote(""); setHistory([]);
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
        {!loading && !pending.length ? <p className="approvalQueueEmpty">Nenhum conteúdo aguardando decisão nesta etapa.</p> : null}
        <ol>{pending.map((entry) => {
          const calendarWhen = entry.kind === "calendar" ? localParts(entry.item.scheduled_at) : null;
          const taskDue = entry.kind === "task" ? dueInfo(entry.task.due_date) : null;
          return <li key={entry.key}><button type="button" className={selected?.key === entry.key ? "is-active" : ""} onClick={() => { setSelectedId(entry.key); setNotice(null); setApprovalLink(null); }}>
            <small>{entry.kind === "calendar" ? `${entry.item.channel || "social"} · ${STUDIO_FORMATS[entry.item.format]}` : `Job · ${entry.task.category || "Tarefa"}`}</small>
            <strong>{entry.kind === "calendar" ? entry.item.title : entry.task.title}</strong>
            <span>{calendarWhen ? `${calendarWhen.label} · ${calendarWhen.time}` : taskDue?.label}</span>
          </button></li>;
        })}</ol>
      </aside>

      <main className="approvalPreview" aria-label="Visualização da peça">
        <div className="approvalPreviewToolbar" role="group" aria-label="Modo de visualização">
          <button type="button" className={preview === "desktop" ? "is-active" : ""} aria-pressed={preview === "desktop"} onClick={() => setPreview("desktop")}><Monitor size={15} aria-hidden="true" /> Desktop</button>
          <button type="button" className={preview === "mobile" ? "is-active" : ""} aria-pressed={preview === "mobile"} onClick={() => setPreview("mobile")}><Smartphone size={15} aria-hidden="true" /> Mobile</button>
        </div>
        {selected ? (selected.kind === "calendar" ? <ContentPreview item={selected.item} mode={preview} /> : <TaskPreview task={selected.task} mode={preview} />)
          : <div className="approvalPreviewEmpty"><p>Selecione um conteúdo pendente para revisar.</p></div>}
      </main>

      <aside className="approvalNotes" aria-label="Notas e comentários">
        <header><span>Notas e comentários</span></header>
        {selected ? <>
          {selected.kind === "calendar" && selected.item.review_note ? <div className="approvalLastNote"><small>Último pedido de ajuste</small><p>{selected.item.review_note}</p></div> : null}
          <label><span>Observação da decisão</span><textarea rows={5} maxLength={1000} value={note} onChange={(event) => { setNote(event.target.value); setError(null); }} placeholder="Registre sua orientação para este conteúdo" /></label>
          {selected.kind === "calendar" ? <PostComments key={selected.item.id} itemId={selected.item.id} clientMode={!isAgency} /> : null}
          {(isAgency || selected.kind === "task") && history.length ? <details className="approvalHistory"><summary>Histórico ({history.length})</summary><ol>{[...history].reverse().map((event) => <li key={event.id}><b>{event.actor_name || (event.actor_side === "cliente" ? "Cliente" : "Equipe Mugô")}</b> {event.action}<small>{new Date(event.created_at).toLocaleString("pt-BR")}</small>{event.detail ? <p>{event.detail}</p> : null}</li>)}</ol></details> : null}
        </> : <p className="approvalQueueEmpty">As notas da peça selecionada aparecem aqui.</p>}
      </aside>
    </div>
    {selected ? <footer className="approvalDecisionBar">
      {(selected.kind === "calendar" ? canDeleteCalendarContent : canDeleteTaskContent)
        ? <button type="button" className="ds-button" disabled={busy} onClick={() => void remove()}>Excluir conteúdo</button> : null}
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

function TaskPreview({ task, mode }: { task: CrmTask; mode: PreviewMode }) {
  const due = dueInfo(task.due_date);
  return <article className={`approvalDevice is-${mode}`}>
    <div className="approvalDeviceChrome"><span /><span /><span /></div>
    <header><small>Job · {task.category || "Tarefa"}</small><strong>{task.title}</strong></header>
    <div className="approvalDeviceMedia"><div className="approvalMediaFallback">{task.deliverable_url
      ? <a href={task.deliverable_url} target="_blank" rel="noreferrer noopener">Abrir material para revisão ↗</a>
      : "Nenhum material foi anexado ao job."}</div></div>
    <div className="approvalDeviceCopy">
      <b>{task.assignee?.name || "Sem responsável definido"}</b>
      <p>{task.notes || "Sem orientações adicionais."}</p>
      <small>{due.label}</small>
    </div>
  </article>;
}
