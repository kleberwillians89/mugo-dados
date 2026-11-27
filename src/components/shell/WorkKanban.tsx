import { useCallback, useEffect, useState } from "react";
import { Bell, ChevronDown, ChevronUp, KanbanSquare } from "lucide-react";
import { dueInfo, listClientTasks, listCrmTasks, listTaskNotifications, markTaskNotificationRead, type TaskAssignmentMessage, type TaskStatus } from "../../app/crm";
import { useWork } from "../../app/WorkContext";
import TaskBoard from "../studio/TaskBoard";
import ClientTasks from "../studio/ClientTasks";
import { KANBAN_ROUTES, OPEN_TASK_EVENT, kanbanCache, type KanbanCounts as Counts } from "./workKanban.helpers";
import "./workKanban.css";


const OPEN_KEY = (userId: string | null) => `mugo:kanban:open:${userId || "anon"}`;
const IN_PROGRESS: TaskStatus[] = ["pending", "in_progress", "changes"];
const IN_APPROVAL: TaskStatus[] = ["internal_review", "client_review"];

/** Primeira vez (nada salvo): expandido. Depois vale a escolha da pessoa. */
function readOpen(userId: string | null): boolean {
  try { return window.localStorage.getItem(OPEN_KEY(userId)) !== "0"; } catch { return true; }
}

/**
 * Kanban integrado e recolhível. Recolhido: uma faixa com as pendências (em andamento, em aprovação, atrasadas).
 * Expandido: o mesmo quadro da página Tarefas (equipe) ou as tarefas visíveis ao cliente. A escolha fica salva por
 * pessoa. Os dados e as permissões são os de /tasks e /client-tasks: nada é duplicado aqui.
 */
export default function WorkKanban({ place = "shell" }: { place?: "shell" | "home" }) {
  const work = useWork();
  // No Início o Kanban vem dentro da página (antes dos processos); nas outras telas, pelo Shell.
  const show = Boolean(work && work.mode && work.clientId && (place === "home" || KANBAN_ROUTES.has(work.route)));
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

  return <section className={`workKanban${open ? " is-open" : ""}${place === "home" ? " is-home" : ""}`} aria-label="Kanban de tarefas">
    <div className="workKanbanBar">
      <span className="workKanbanTitle"><KanbanSquare size={17} aria-hidden="true" /> Kanban</span>
      {counts ? <span className="workKanbanCounts" aria-live="polite">
        <span><b>{counts.progress}</b> em andamento</span>
        <span><b>{counts.approval}</b> em aprovação</span>
        {counts.late ? <span className="is-late"><b>{counts.late}</b> atrasada{counts.late > 1 ? "s" : ""}</span> : null}
      </span> : <span className="workKanbanCounts" />}
      {work.mode === "team" ? <KanbanNotices onOpenTask={(taskId) => {
        if (!open) { setOpen(true); try { window.localStorage.setItem(OPEN_KEY(userId), "1"); } catch { /* sem storage */ } }
        const url = new URL(window.location.href);
        url.searchParams.set("task", taskId);
        window.history.replaceState(window.history.state, "", url);
        window.dispatchEvent(new CustomEvent(OPEN_TASK_EVENT, { detail: { taskId } }));
      }} /> : null}
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


/**
 * Avisos de atribuição (os mesmos do antigo chat flutuante): sino com os não lidos na faixa do Kanban.
 * Abrir um aviso marca como lido e abre a tarefa no próprio quadro. Nada é apagado.
 */
function KanbanNotices({ onOpenTask }: { onOpenTask: (taskId: string) => void }) {
  const [messages, setMessages] = useState<TaskAssignmentMessage[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const out = await listTaskNotifications();
      setMessages(out.messages || []); setUnread(out.unread || 0);
    } catch { /* sem avisos: a faixa segue */ }
  }, []);
  useEffect(() => {
    const first = window.setTimeout(() => void load(), 0);
    const timer = window.setInterval(() => void load(), 60_000);
    return () => { window.clearTimeout(first); window.clearInterval(timer); };
  }, [load]);

  async function view(message: TaskAssignmentMessage) {
    setOpen(false);
    if (!message.read_at) {
      setMessages((cur) => cur.map((m) => m.id === message.id ? { ...m, read_at: new Date().toISOString() } : m));
      setUnread((n) => Math.max(0, n - 1));
      try { await markTaskNotificationRead(message.id); } catch { /* abrir a tarefa não depende de marcar como lido */ }
    }
    onOpenTask(message.task_id);
  }

  return <div className="workKanbanNotices">
    <button type="button" className="workKanbanBell" aria-expanded={open} aria-haspopup="true"
      aria-label={unread ? `Avisos de tarefas: ${unread} não lido${unread > 1 ? "s" : ""}` : "Avisos de tarefas"}
      onClick={() => { setOpen((o) => !o); if (!open) void load(); }}>
      <Bell size={16} aria-hidden="true" />{unread ? <b>{unread}</b> : null}
    </button>
    {open ? <div className="workKanbanNoticeList" role="dialog" aria-label="Avisos de tarefas">
      {!messages.length ? <p>Nenhum aviso recebido ainda.</p> : messages.slice(0, 20).map((m) =>
        <button type="button" key={m.id} className={m.read_at ? "" : "is-unread"} onClick={() => void view(m)}>
          <strong>{m.title}</strong><span>{m.body}</span>
        </button>)}
    </div> : null}
  </div>;
}
