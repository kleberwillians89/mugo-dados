import { useEffect, useState } from "react";
import { CRM_UNAVAILABLE_TEXT, TASK_STATUS, dueInfo, listClientTasks, type ClientTask, type CrmUnavailable } from "../../app/crm";

/**
 * "Em andamento com a Mugô": tarefas que a Mugô marcou com a etiqueta "cliente" no CRM.
 * O cliente vê só isso; a agência vê o mesmo bloco (para conferir o que o cliente enxerga).
 */
export default function ClientTasks({ isAgency, clientId, standalone = false }: { isAgency: boolean; clientId: string; standalone?: boolean }) {
  const [tasks, setTasks] = useState<ClientTask[] | null>(null);
  const [unavailable, setUnavailable] = useState<CrmUnavailable["reason"] | null>(null);

  useEffect(() => {
    let alive = true;
    listClientTasks()
      .then((res) => {
        if (!alive) return;
        if (res.available) { setTasks(res.tasks || []); setUnavailable(null); } else { setTasks([]); setUnavailable(res.reason); }
      })
      .catch(() => { if (alive) setTasks([]); });
    return () => { alive = false; };
  }, [clientId]);

  if (tasks === null) return null;
  const open = tasks.filter((t) => t.status !== "completed");
  const done = tasks.filter((t) => t.status === "completed").slice(0, 3);
  // Na Aprovação, sem tarefas (ou sem ligação com o CRM) o bloco some; na página própria, avisa.
  if (!isAgency && !tasks.length) return standalone ? <p className="studioEmpty">Nenhuma tarefa em andamento com a Mugô no momento.</p> : null;

  return <section className="clientTasks" aria-label="Em andamento com a Mugô">
    <h2 className="crmGroupTitle">Em andamento com a Mugô {open.length ? <span>{open.length}</span> : null}</h2>
    {isAgency ? <p className="libHint">{unavailable ? CRM_UNAVAILABLE_TEXT[unavailable] : "O cliente vê aqui só as tarefas com a etiqueta \"cliente\" no CRM, sem observações nem nomes da equipe."}</p> : null}
    {tasks.length ? <ul className="crmTaskList">{[...open, ...done].map((t) => {
      const due = dueInfo(t.due_date);
      const late = due.late && t.status !== "completed";
      return <li key={t.id} className={`crmTask is-${t.status}${late ? " is-late" : ""}`}>
        <div className="crmTaskMain"><b>{t.title}</b><small>{TASK_STATUS[t.status]}</small></div>
        <div className="crmTaskSide">{t.status === "completed" ? <span className="crmDue">✓ Concluída</span> : <span className={late ? "crmDue is-late" : "crmDue"}>{due.label}</span>}</div>
      </li>;
    })}</ul> : isAgency && !unavailable ? <p className="studioEmpty">Nenhuma tarefa com a etiqueta "cliente" para esta empresa.</p> : null}
  </section>;
}
