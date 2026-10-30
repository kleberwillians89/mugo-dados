import { useCallback, useEffect, useMemo, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { CRM_UNAVAILABLE_TEXT, TASK_PRIORITY, TASK_STATUS, dueInfo, listCrmTasks, type CrmTask, type CrmUnavailable, type TaskStatus } from "../app/crm";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import ClientTasks from "../components/studio/ClientTasks";
import "../styles/studio.css";

type Filter = "abertas" | TaskStatus;
const FILTERS: Record<Filter, string> = { abertas: "Abertas", pending: "Pendentes", in_progress: "Em andamento", completed: "Concluídas" , cancelled: "Canceladas" };
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);

/** Painel de tarefas da agência para a empresa ativa, lido do CRM Mugô. Financeiro fica de fora. */
export default function Tasks() {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "empresa";
  const [filter, setFilter] = useState<Filter>("abertas");
  const [tasks, setTasks] = useState<CrmTask[]>([]);
  const [unavailable, setUnavailable] = useState<CrmUnavailable["reason"] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await listCrmTasks(filter === "abertas" ? undefined : filter);
      if (getActiveClientId() !== clientId) return;
      if (!res.available) { setUnavailable(res.reason); setTasks([]); return; }
      setUnavailable(null); setTasks(res.tasks || []);
    } catch (cause) { setError(message(cause, "Não foi possível ler as tarefas do CRM.")); }
    finally { setLoading(false); }
  }, [filter, clientId]);
  useEffect(() => { void load(); }, [load]);

  const groups = useMemo(() => {
    const late: CrmTask[] = [], soon: CrmTask[] = [], later: CrmTask[] = [];
    for (const t of tasks) {
      const info = dueInfo(t.due_date);
      if (info.late && (t.status === "pending" || t.status === "in_progress")) late.push(t);
      else if (t.due_date && !info.late && new Date(t.due_date).getTime() - Date.now() < 7 * 86400000) soon.push(t);
      else later.push(t);
    }
    return [["Atrasadas", late], ["Próximos 7 dias", soon], ["Depois / sem prazo", later]] as const;
  }, [tasks]);

  return <Shell title="Tarefas" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={clientName} title="Tarefas da agência" controls={<button type="button" className="ds-button" onClick={() => void load()} disabled={loading}>Atualizar</button>} />
    <p className="libHint">Lidas do CRM Mugô, que continua sendo onde a tarefa é criada e editada. Financeiro não aparece aqui.</p>
    <div className="studioTabs" role="tablist" aria-label="Filtro">
      {(Object.keys(FILTERS) as Filter[]).map((f) => <button key={f} role="tab" aria-selected={filter === f} className={filter === f ? "is-active" : ""} onClick={() => setFilter(f)}>{FILTERS[f]}</button>)}
    </div>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {unavailable ? <div className="studioEmpty"><p>{CRM_UNAVAILABLE_TEXT[unavailable]}</p></div> : null}
    {loading && !tasks.length ? <p>Carregando…</p> : null}
    {!loading && !unavailable && !error && !tasks.length ? <div className="studioEmpty"><p>Nenhuma tarefa {filter === "abertas" ? "aberta" : FILTERS[filter].toLowerCase()} para {clientName} no CRM.</p></div> : null}
    {groups.map(([label, list]) => list.length ? <section key={label} className="crmGroup">
      <h2 className="crmGroupTitle">{label} <span>{list.length}</span></h2>
      <ul className="crmTaskList">{list.map((t) => {
        const due = dueInfo(t.due_date);
        return <li key={t.id} className={`crmTask is-${t.status}${due.late && t.status !== "completed" && t.status !== "cancelled" ? " is-late" : ""}`}>
          <div className="crmTaskMain">
            <b>{t.title}</b>
            {t.notes ? <p>{t.notes}</p> : null}
            <small>{[TASK_STATUS[t.status] || t.status, t.priority ? TASK_PRIORITY[t.priority] || t.priority : null, t.category].filter(Boolean).join(" · ")}</small>
          </div>
          <div className="crmTaskSide">
            <span className={due.late ? "crmDue is-late" : "crmDue"}>{due.label}{t.due_time ? ` ${t.due_time.slice(0, 5)}` : ""}</span>
            {t.assignee ? <span className="crmWho"><i style={{ background: t.assignee.color || "#9aa3ad" }} aria-hidden="true" />{t.assignee.name}</span> : <span className="crmWho is-none">Sem responsável</span>}
          </div>
        </li>;
      })}</ul>
    </section> : null)}
  </div></Shell>;
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
