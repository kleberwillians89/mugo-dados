import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { getActiveClientId, getActiveClientName } from "../../app/activeClient";
import { CRM_UNAVAILABLE_TEXT, TASK_PRIORITY, TASK_STATUS, createTask, deleteTask, dueInfo, listCrmTasks, updateTask, type CrmTask, type CrmUnavailable, type TaskInput, type TaskStatus } from "../../app/crm";
import Drawer from "../Drawer";
import { OPEN, sortTasks } from "./taskBoard.helpers";

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);


const NEXT: Partial<Record<TaskStatus, TaskStatus>> = { pending: "in_progress", in_progress: "completed" };
type Draft = { id?: string; title: string; notes: string; status: TaskStatus; priority: string; due_date: string; due_time: string;
  category: string; assignee_name: string; visible_to_client: boolean };
const emptyDraft = (isAgency: boolean): Draft => ({ title: "", notes: "", status: "pending", priority: "", due_date: "", due_time: "",
  category: "", assignee_name: "", visible_to_client: !isAgency });
const toDraft = (t: CrmTask): Draft => ({ id: t.id, title: t.title, notes: t.notes || "", status: t.status, priority: t.priority || "",
  due_date: t.due_date || "", due_time: t.due_time || "", category: t.category || "", assignee_name: t.assignee?.name || "",
  visible_to_client: Boolean(t.visible_to_client) });

/**
 * Tarefas da empresa em quadro (mesmo modelo do Fluxo de aprovação do Calendário), guardadas no Mugoverso.
 * Equipe Mugô vê todas; o cliente vê as visíveis a ele. Quem tem "Gerenciar tarefas" cria, edita e move.
 */
export default function TaskBoard({ onRefreshRef, canManage = false, isAgency = false }: { onRefreshRef?: (fn: () => void) => void; canManage?: boolean; isAgency?: boolean }) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "empresa";
  const [tasks, setTasks] = useState<CrmTask[]>([]);
  const [showCancelled, setShowCancelled] = useState(false);
  const [who, setWho] = useState<string>("");
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [unavailable, setUnavailable] = useState<CrmUnavailable["reason"] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const calls: Promise<Awaited<ReturnType<typeof listCrmTasks>>>[] = [listCrmTasks(), listCrmTasks("completed")];
      if (showCancelled) calls.push(listCrmTasks("cancelled"));
      const results = await Promise.all(calls);
      if (getActiveClientId() !== clientId) return;
      const down = results.find((r) => !r.available);
      if (down && !down.available) { setUnavailable(down.reason); setTasks([]); return; }
      const byId = new Map<string, CrmTask>();
      for (const r of results) if (r.available) for (const t of r.tasks || []) byId.set(t.id, t);
      setUnavailable(null); setTasks([...byId.values()]);
    } catch (cause) { setError(message(cause, "Não foi possível carregar as tarefas.")); }
    finally { setLoading(false); }
  }, [clientId, showCancelled]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { onRefreshRef?.(() => void load()); }, [load, onRefreshRef]);

  const people = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of tasks) if (t.assignee?.name) map.set(t.assignee.name, t.assignee.color || "#9aa3ad");
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [tasks]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return tasks.filter((t) => (!who || (who === "-" ? !t.assignee : t.assignee?.name === who))
      && (!q || `${t.title} ${t.notes || ""} ${t.category || ""}`.toLowerCase().includes(q)));
  }, [tasks, who, query]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft || busy) return;
    const input: TaskInput = { title: draft.title.trim(), notes: draft.notes.trim() || null, status: draft.status, priority: draft.priority || null,
      due_date: draft.due_date || null, due_time: draft.due_time || null, category: draft.category.trim() || null,
      assignee_name: draft.assignee_name.trim() || null, ...(isAgency ? { visible_to_client: draft.visible_to_client } : {}) };
    setBusy(true); setError(null);
    try { if (draft.id) await updateTask(draft.id, input); else await createTask(input); setDraft(null); await load(); }
    catch (cause) { setError(message(cause, "Não foi possível salvar a tarefa.")); }
    finally { setBusy(false); }
  }

  async function move(task: CrmTask, status: TaskStatus) {
    setError(null);
    setTasks((current) => current.map((t) => (t.id === task.id ? { ...t, status } : t)));
    try { await updateTask(task.id, { status }); } catch (cause) { setError(message(cause, "Não foi possível mudar a etapa.")); await load(); }
  }

  async function remove() {
    if (!draft?.id || busy || !window.confirm(`Excluir a tarefa "${draft.title}"?`)) return;
    setBusy(true); setError(null);
    try { await deleteTask(draft.id); setDraft(null); await load(); }
    catch (cause) { setError(message(cause, "Não foi possível excluir.")); }
    finally { setBusy(false); }
  }

  const columns = (showCancelled ? ["pending", "in_progress", "completed", "cancelled"] : ["pending", "in_progress", "completed"]) as TaskStatus[];
  const late = visible.filter((t) => OPEN.includes(t.status) && dueInfo(t.due_date).late).length;

  return <div className="taskBoardWrap">
    <div className="taskToolbar">
      <input type="search" placeholder="Buscar tarefa" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Buscar tarefa" />
      <select value={who} onChange={(e) => setWho(e.target.value)} aria-label="Responsável">
        <option value="">Todos os responsáveis</option>
        {people.map(([name]) => <option key={name} value={name}>{name}</option>)}
        <option value="-">Sem responsável</option>
      </select>
      <label className="taskToggle"><input type="checkbox" checked={showCancelled} onChange={(e) => setShowCancelled(e.target.checked)} /> Mostrar canceladas</label>
      {late ? <span className="taskLateBadge">{late} atrasada{late > 1 ? "s" : ""}</span> : null}
      {canManage ? <button type="button" className="ds-button is-primary taskNew" onClick={() => setDraft(emptyDraft(isAgency))}>+ Nova tarefa</button> : null}
    </div>
    <p className="libHint">{isAgency ? "Tarefas da empresa no Mugoverso. Marque \"Visível ao cliente\" para o cliente acompanhar." : "O que está em andamento com a Mugô para a sua empresa."}</p>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {unavailable ? <div className="studioEmpty"><p>{CRM_UNAVAILABLE_TEXT[unavailable]}</p></div> : null}
    {loading && !tasks.length ? <p>Carregando…</p> : null}
    {!loading && !unavailable && !error && !tasks.length ? <div className="studioEmpty"><p>Nenhuma tarefa para {clientName} ainda.{canManage ? " Clique em + Nova tarefa." : ""}</p></div> : null}
    {!unavailable && tasks.length ? <div className="kanban is-compact taskBoard" aria-label="Quadro de tarefas">
      {columns.map((status) => {
        const list = sortTasks(visible.filter((t) => t.status === status));
        return <section key={status} className={`kanbanCol is-task-${status}`} aria-label={TASK_STATUS[status]}>
          <header><b>{TASK_STATUS[status]}</b><span>{list.length}</span></header>
          {list.map((t) => <TaskCard key={t.id} task={t} onOpen={() => setDraft(toDraft(t))}
            onAdvance={canManage && NEXT[t.status] ? () => void move(t, NEXT[t.status]!) : undefined} />)}
          {!list.length ? <p className="taskColEmpty">Nada aqui.</p> : null}
        </section>;
      })}
    </div> : null}
    <Drawer open={Boolean(draft)} title={draft?.id ? (canManage ? "Editar tarefa" : draft.title) : "Nova tarefa"} onClose={() => { if (!busy) setDraft(null); }}>
      {draft ? <form className="taskForm" onSubmit={save}>
        <fieldset disabled={!canManage || busy}>
          <label className="ds-field">Título<input required maxLength={200} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} placeholder="Ex.: Aprovar fotos do lançamento" /></label>
          <div className="taskFormRow">
            <label className="ds-field">Etapa<select value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value as TaskStatus })}>
              {(Object.keys(TASK_STATUS) as TaskStatus[]).map((k) => <option key={k} value={k}>{TASK_STATUS[k]}</option>)}</select></label>
            <label className="ds-field">Prioridade<select value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: e.target.value })}>
              <option value="">Sem prioridade</option>{Object.entries(TASK_PRIORITY).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          </div>
          <div className="taskFormRow">
            <label className="ds-field">Prazo<input type="date" value={draft.due_date} onChange={(e) => setDraft({ ...draft, due_date: e.target.value })} /></label>
            <label className="ds-field">Hora<input type="time" value={draft.due_time} onChange={(e) => setDraft({ ...draft, due_time: e.target.value })} /></label>
          </div>
          <div className="taskFormRow">
            <label className="ds-field">Responsável<input maxLength={80} value={draft.assignee_name} onChange={(e) => setDraft({ ...draft, assignee_name: e.target.value })} placeholder="Nome" /></label>
            <label className="ds-field">Categoria<input maxLength={60} value={draft.category} onChange={(e) => setDraft({ ...draft, category: e.target.value })} placeholder="Ex.: Conteúdo" /></label>
          </div>
          <label className="ds-field">Observações<textarea rows={4} maxLength={4000} value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} /></label>
          {isAgency ? <label className="taskCheck"><input type="checkbox" checked={draft.visible_to_client} onChange={(e) => setDraft({ ...draft, visible_to_client: e.target.checked })} /> Visível ao cliente</label> : null}
        </fieldset>
        {canManage ? <div className="taskFormActions">
          {draft.id ? <button type="button" className="ds-link is-quiet taskDanger" disabled={busy} onClick={() => void remove()}>Excluir</button> : <span />}
          <span className="taskFormButtons"><button type="button" className="ds-button" onClick={() => setDraft(null)}>Cancelar</button>
            <button className="ds-button is-primary" disabled={busy || !draft.title.trim()}>{busy ? "Salvando…" : draft.id ? "Salvar" : "Criar tarefa"}</button></span>
        </div> : null}
      </form> : null}
    </Drawer>
  </div>;
}

function TaskCard({ task: t, onOpen, onAdvance }: { task: CrmTask; onOpen: () => void; onAdvance?: () => void }) {
  const due = dueInfo(t.due_date);
  const late = due.late && OPEN.includes(t.status);
  const urgent = t.priority === "urgent" || t.priority === "high";
  return <article className={`kanbanCard taskCard${late ? " is-late" : ""}`}>
    <button type="button" className="kanbanTitle" onClick={onOpen}>{t.title}</button>
    <div className="taskMeta">
      <span className={late ? "taskDue is-late" : "taskDue"}>{t.status === "completed" ? "✓ " : ""}{due.label}{t.due_time ? ` ${t.due_time.slice(0, 5)}` : ""}</span>
      {urgent ? <span className={`taskPrio is-${t.priority}`}>{TASK_PRIORITY[t.priority || ""]}</span> : null}
      {onAdvance ? <button type="button" className="ds-link is-quiet taskAdvance" onClick={onAdvance}>{t.status === "pending" ? "Iniciar →" : "Concluir ✓"}</button> : null}
    </div>
    {t.assignee || t.category ? <small className="taskWho">
      {t.assignee ? <><i style={{ background: t.assignee.color || "#9aa3ad" }} aria-hidden="true" />{t.assignee.name}</> : null}
      {t.assignee && t.category ? " · " : ""}{t.category}
    </small> : null}
  </article>;
}
