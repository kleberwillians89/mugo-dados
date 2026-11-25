import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight } from "lucide-react";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import { TASK_PRIORITY, TASK_STATUS, dueInfo, type TaskStatus } from "../app/crm";
import { MY_TASK_GROUPS, groupMyTasks, listMyTasks, type MyTask, type MyTasksResult } from "../app/myTasks";
import "../styles/my-tasks.css";

type StatusFilter = "open" | TaskStatus;
const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: "open", label: "Abertas" },
  ...(["pending", "in_progress", "internal_review", "client_review", "changes", "completed"] as TaskStatus[])
    .map((value) => ({ value, label: TASK_STATUS[value] })),
];

type Props = { onOpenTask: (clientId: string, taskId: string) => void };

/** Minhas Tarefas: tudo em que a pessoa é responsável, em todas as empresas, agrupado pelo prazo. */
export default function MyTasks({ onOpenTask }: Props) {
  const [clientId, setClientId] = useState("");
  const [status, setStatus] = useState<StatusFilter>("open");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [data, setData] = useState<MyTasksResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // A busca vai ao servidor só depois de a pessoa parar de digitar.
  useEffect(() => {
    const handle = window.setTimeout(() => setSearch(query), 350);
    return () => window.clearTimeout(handle);
  }, [query]);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      setData(await listMyTasks({ clientId: clientId || undefined, status, q: search }));
    } catch (err) {
      setData(null);
      setError(err instanceof Error && err.message ? err.message : "Não foi possível carregar suas tarefas agora.");
    } finally { setLoading(false); }
  }, [clientId, status, search]);
  useEffect(() => { void load(); }, [load]);

  const tasks = useMemo(() => data?.tasks ?? [], [data]);
  const groups = useMemo(() => groupMyTasks(tasks), [tasks]);
  const filtered = Boolean(clientId || search.trim() || status !== "open");

  return <Shell title="Minhas Tarefas" variant="editorial"><div className="ds-page myTasksPage">
    <PageHeader title="Minhas Tarefas" controls={<button type="button" className="ds-button" onClick={() => void load()}>Atualizar</button>} />
    <p className="myTasksHint">Tudo em que você é responsável, em todas as empresas. Clique para abrir no quadro da empresa.</p>
    <div className="myTasksFilters">
      <input type="search" placeholder="Buscar tarefa" aria-label="Buscar tarefa" value={query} onChange={(e) => setQuery(e.target.value)} />
      <select aria-label="Empresa" value={clientId} onChange={(e) => setClientId(e.target.value)}>
        <option value="">Todas as empresas</option>
        {(data?.clients ?? []).map((c) => <option key={c.client_id} value={c.client_id}>{c.name}</option>)}
      </select>
      <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}>
        {STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>

    {loading && !data ? <p className="myTasksState" role="status">Carregando suas tarefas…</p>
      : error ? <div className="myTasksState is-error" role="alert">
          <p>{error}</p>
          <button type="button" className="ds-button" onClick={() => void load()}>Tentar de novo</button>
        </div>
      : !tasks.length ? <p className="myTasksState">
          {filtered ? "Nenhuma tarefa com esses filtros." : "Você não tem tarefas abertas. 🎉"}
        </p>
      : status === "open" ? MY_TASK_GROUPS.filter((g) => groups[g.key].length).map((g) =>
          <section key={g.key} className={`myTasksGroup is-${g.key}`} aria-label={g.label}>
            <h2>{g.label} <span>{groups[g.key].length}</span></h2>
            <ul>{groups[g.key].map((t) => <TaskRow key={`${t.client_id}:${t.id}`} task={t} onOpen={onOpenTask} />)}</ul>
          </section>)
      : <section className="myTasksGroup" aria-label={TASK_STATUS[status as TaskStatus]}>
          <h2>{TASK_STATUS[status as TaskStatus]} <span>{tasks.length}</span></h2>
          <ul>{tasks.map((t) => <TaskRow key={`${t.client_id}:${t.id}`} task={t} onOpen={onOpenTask} />)}</ul>
        </section>}
    {data?.truncated ? <p className="myTasksHint">Mostrando as primeiras 500. Use os filtros para ver as demais.</p> : null}
  </div></Shell>;
}

function TaskRow({ task, onOpen }: { task: MyTask; onOpen: (clientId: string, taskId: string) => void }) {
  const due = dueInfo(task.due_date);
  const done = task.status === "completed" || task.status === "cancelled";
  return <li>
    <button type="button" className="myTaskRow" onClick={() => onOpen(task.client_id, task.id)}>
      <span className="myTaskClient">{task.client_name}</span>
      <strong className="myTaskTitle">{task.title}</strong>
      <span className="myTaskMeta">
        {task.category ? <span>{task.category}</span> : null}
        <span className={due.late && !done ? "is-late" : ""}>{task.due_date ? `${due.label}${task.due_time ? ` · ${task.due_time}` : ""}` : "Sem prazo"}</span>
        <span className="myTaskStatus" data-status={task.status}>{TASK_STATUS[task.status] ?? task.status}</span>
        {task.priority ? <span className={`myTaskPriority is-${task.priority}`}>{TASK_PRIORITY[task.priority] ?? task.priority}</span> : null}
      </span>
      <ArrowRight size={16} aria-hidden="true" />
    </button>
  </li>;
}
