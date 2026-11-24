import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronUp, KanbanSquare } from "lucide-react";
import { dueInfo, listClientTasks, listCrmTasks, type TaskStatus } from "../../app/crm";
import { getPathForRoute, navigateToAppRoute } from "../../app/routes";
import { useWork } from "../../app/WorkContext";
import TaskBoard from "../studio/TaskBoard";
import ClientTasks from "../studio/ClientTasks";
import { KANBAN_ROUTES, kanbanCache, type KanbanCounts as Counts } from "./workKanban.helpers";
import "./workKanban.css";


const OPEN_KEY = (userId: string | null) => `mugo:kanban:open:${userId || "anon"}`;
const IN_PROGRESS: TaskStatus[] = ["pending", "in_progress", "changes"];
const IN_APPROVAL: TaskStatus[] = ["internal_review", "client_review"];

function readOpen(userId: string | null): boolean {
  try { return window.localStorage.getItem(OPEN_KEY(userId)) === "1"; } catch { return false; }
}

/**
 * Kanban integrado e recolhível. Recolhido: uma faixa com as pendências (em andamento, em aprovação, atrasadas).
 * Expandido: o mesmo quadro da página Tarefas (equipe) ou as tarefas visíveis ao cliente. A escolha fica salva por
 * pessoa. Os dados e as permissões são os de /tasks e /client-tasks: nada é duplicado aqui.
 */
export default function WorkKanban() {
  const work = useWork();
  const show = Boolean(work && work.mode && work.clientId && KANBAN_ROUTES.has(work.route));
  const userId = work?.userId ?? null;
  const [open, setOpen] = useState(() => readOpen(userId));
  const [counts, setCounts] = useState<Counts | null>(null);
  const mode = work?.mode;
  const clientId = work?.clientId;

  useEffect(() => { setOpen(readOpen(userId)); }, [userId]);

  const loadCounts = useCallback(async (fresh = false) => {
    if (!mode || !clientId) return;
    const key = `${clientId}:${mode}:${userId || ""}`;
    const cached = fresh ? null : kanbanCache.get(key);
    if (cached) { setCounts(cached); return; }
    try {
      const r = mode === "team" ? await listCrmTasks() : await listClientTasks();
      if (!r.available) { setCounts(null); return; }
      const tasks = r.tasks as { status: TaskStatus; due_date: string | null }[];
      const next = {
        progress: tasks.filter((t) => IN_PROGRESS.includes(t.status)).length,
        approval: tasks.filter((t) => IN_APPROVAL.includes(t.status)).length,
        late: tasks.filter((t) => t.status !== "completed" && t.status !== "cancelled" && dueInfo(t.due_date).late).length,
      };
      kanbanCache.set(key, next);
      setCounts(next);
    } catch { setCounts(null); }
  }, [mode, clientId, userId]);
  const [touched, setTouched] = useState(false);

  // Pendências na faixa: ao abrir a tela, ao recolher (depois de mexer no quadro) e ao voltar para a aba.
  useEffect(() => {
    if (!show || open) return undefined;
    void loadCounts(touched);
    const onFocus = () => void loadCounts(true);
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [show, open, loadCounts, touched]);

  if (!show || !work) return null;

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (!next) setTouched(true);  // recolheu depois de mexer no quadro: busca as pendências de novo
    try { window.localStorage.setItem(OPEN_KEY(userId), next ? "1" : "0"); } catch { /* sem storage: só nesta tela */ }
  };

  return <section className={`workKanban${open ? " is-open" : ""}`} aria-label="Kanban de tarefas">
    <div className="workKanbanBar">
      <span className="workKanbanTitle"><KanbanSquare size={17} aria-hidden="true" /> Kanban</span>
      {counts ? <span className="workKanbanCounts" aria-live="polite">
        <span><b>{counts.progress}</b> em andamento</span>
        <span><b>{counts.approval}</b> em aprovação</span>
        {counts.late ? <span className="is-late"><b>{counts.late}</b> atrasada{counts.late > 1 ? "s" : ""}</span> : null}
      </span> : <span className="workKanbanCounts" />}
      <a className="workKanbanLink" href={getPathForRoute("tasks")} onClick={(event) => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        navigateToAppRoute("tasks");
        window.dispatchEvent(new PopStateEvent("popstate", { state: window.history.state }));
      }}>Ver página completa</a>
      <button type="button" className="workKanbanToggle" aria-expanded={open} onClick={toggle}>
        {open ? <>Recolher <ChevronUp size={16} aria-hidden="true" /></> : <>Expandir <ChevronDown size={16} aria-hidden="true" /></>}
      </button>
    </div>
    {open ? <div className="workKanbanBoard">
      {work.mode === "team"
        ? <TaskBoard canManage={work.canManage} isAgency={work.isAgency} />
        : <ClientTasks isAgency={false} clientId={work.clientId} standalone />}
    </div> : null}
  </section>;
}
