import { useCallback, useEffect, useMemo, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { CRM_UNAVAILABLE_TEXT, TASK_PRIORITY, TASK_STATUS, dueInfo, listCrmTasks, type CrmTask, type CrmUnavailable, type TaskStatus } from "../app/crm";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import ClientTasks from "../components/studio/ClientTasks";
import "../styles/studio.css";

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const OPEN: TaskStatus[] = ["pending", "in_progress"];
const PRIORITY_RANK: Record<string, number> = { urgent: 0, high: 1, medium: 2, low: 3 };

/** Ordem do card dentro da coluna: atrasadas primeiro, depois prazo mais próximo, depois prioridade. */
export function sortTasks(list: CrmTask[], today = new Date()): CrmTask[] {
  return [...list].sort((a, b) => {
    const la = dueInfo(a.due_date, today).late && OPEN.includes(a.status) ? 0 : 1;
    const lb = dueInfo(b.due_date, today).late && OPEN.includes(b.status) ? 0 : 1;
    if (la !== lb) return la - lb;
    const da = a.due_date || "9999", db = b.due_date || "9999";
    if (da !== db) return da < db ? -1 : 1;
    return (PRIORITY_RANK[a.priority || ""] ?? 9) - (PRIORITY_RANK[b.priority || ""] ?? 9);
  });
}

/**
 * Tarefas da agência em quadro (mesmo modelo do Fluxo de aprovação do Calendário).
 * Leitura do CRM Mugô — lá continua sendo onde a tarefa é criada, editada e muda de etapa.
 */
export default function Tasks() {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "empresa";
  const [tasks, setTasks] = useState<CrmTask[]>([]);
  const [showCancelled, setShowCancelled] = useState(false);
  const [who, setWho] = useState<string>("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<CrmTask | null>(null);
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
    } catch (cause) { setError(message(cause, "Não foi possível ler as tarefas do CRM.")); }
    finally { setLoading(false); }
  }, [clientId, showCancelled]);
  useEffect(() => { void load(); }, [load]);

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

  const columns = (showCancelled ? ["pending", "in_progress", "completed", "cancelled"] : ["pending", "in_progress", "completed"]) as TaskStatus[];
  const late = visible.filter((t) => OPEN.includes(t.status) && dueInfo(t.due_date).late).length;

  return <Shell title="Tarefas" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={clientName} title="Tarefas da agência" controls={<button type="button" className="ds-button" onClick={() => void load()} disabled={loading}>Atualizar</button>} />
    <div className="taskToolbar">
      <input type="search" placeholder="Buscar tarefa" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Buscar tarefa" />
      <select value={who} onChange={(e) => setWho(e.target.value)} aria-label="Responsável">
        <option value="">Todos os responsáveis</option>
        {people.map(([name]) => <option key={name} value={name}>{name}</option>)}
        <option value="-">Sem responsável</option>
      </select>
      <label className="taskToggle"><input type="checkbox" checked={showCancelled} onChange={(e) => setShowCancelled(e.target.checked)} /> Mostrar canceladas</label>
      {late ? <span className="taskLateBadge">{late} atrasada{late > 1 ? "s" : ""}</span> : null}
    </div>
    <p className="libHint">Lidas do CRM Mugô, onde a tarefa é criada e muda de etapa. Financeiro não aparece aqui.</p>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {unavailable ? <div className="studioEmpty"><p>{CRM_UNAVAILABLE_TEXT[unavailable]}</p></div> : null}
    {loading && !tasks.length ? <p>Carregando…</p> : null}
    {!loading && !unavailable && !error && !tasks.length ? <div className="studioEmpty"><p>Nenhuma tarefa para {clientName} no CRM.</p></div> : null}
    {!unavailable && tasks.length ? <div className="kanban is-compact taskBoard" aria-label="Quadro de tarefas">
      {columns.map((status) => {
        const list = sortTasks(visible.filter((t) => t.status === status));
        return <section key={status} className={`kanbanCol is-task-${status}`} aria-label={TASK_STATUS[status]}>
          <header><b>{TASK_STATUS[status]}</b><span>{list.length}</span></header>
          {list.map((t) => <TaskCard key={t.id} task={t} onOpen={() => setOpen(t)} />)}
          {!list.length ? <p className="taskColEmpty">Nada aqui.</p> : null}
        </section>;
      })}
    </div> : null}
    {open ? <TaskDetail task={open} onClose={() => setOpen(null)} /> : null}
  </div></Shell>;
}

function TaskCard({ task: t, onOpen }: { task: CrmTask; onOpen: () => void }) {
  const due = dueInfo(t.due_date);
  const late = due.late && OPEN.includes(t.status);
  const urgent = t.priority === "urgent" || t.priority === "high";
  return <article className={`kanbanCard taskCard${late ? " is-late" : ""}`}>
    <button type="button" className="kanbanTitle" onClick={onOpen}>{t.title}</button>
    <div className="taskMeta">
      <span className={late ? "taskDue is-late" : "taskDue"}>{t.status === "completed" ? "✓ " : ""}{due.label}{t.due_time ? ` ${t.due_time.slice(0, 5)}` : ""}</span>
      {urgent ? <span className={`taskPrio is-${t.priority}`}>{TASK_PRIORITY[t.priority || ""]}</span> : null}
    </div>
    {t.assignee || t.category ? <small className="taskWho">
      {t.assignee ? <><i style={{ background: t.assignee.color || "#9aa3ad" }} aria-hidden="true" />{t.assignee.name}</> : null}
      {t.assignee && t.category ? " · " : ""}{t.category}
    </small> : null}
  </article>;
}

function TaskDetail({ task: t, onClose }: { task: CrmTask; onClose: () => void }) {
  const due = dueInfo(t.due_date);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return <div className="taskDetailBackdrop" onClick={onClose}>
    <aside className="taskDetail" role="dialog" aria-modal="true" aria-label={t.title} onClick={(e) => e.stopPropagation()}>
      <header><h2>{t.title}</h2><button type="button" className="ds-button" onClick={onClose}>Fechar</button></header>
      <dl>
        <dt>Etapa</dt><dd>{TASK_STATUS[t.status] || t.status}</dd>
        <dt>Prazo</dt><dd className={due.late && OPEN.includes(t.status) ? "is-late" : ""}>{due.label}{t.due_time ? ` ${t.due_time.slice(0, 5)}` : ""}</dd>
        {t.priority ? <><dt>Prioridade</dt><dd>{TASK_PRIORITY[t.priority] || t.priority}</dd></> : null}
        <dt>Responsável</dt><dd>{t.assignee?.name || "Sem responsável"}</dd>
        {t.category ? <><dt>Categoria</dt><dd>{t.category}</dd></> : null}
        {t.tags?.length ? <><dt>Etiquetas</dt><dd>{t.tags.join(", ")}</dd></> : null}
      </dl>
      {t.notes ? <p className="taskNotes">{t.notes}</p> : null}
      <p className="libHint">Para mudar etapa, prazo ou responsável, edite no CRM Mugô — aqui atualiza sozinho.</p>
    </aside>
  </div>;
}

/** Tarefas para o cliente: só o que a Mugô marcou com a etiqueta "cliente" no CRM, sem nada interno. */
export function ClientTasksPage() {
  const clientId = getActiveClientId();
  return <Shell title="Tarefas" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={getActiveClientName() || "empresa"} title="Tarefas" />
    <p className="libHint">O que está em andamento com a Mugô para a sua empresa.</p>
    <ClientTasks isAgency={false} clientId={clientId} standalone />
  </div></Shell>;
}
