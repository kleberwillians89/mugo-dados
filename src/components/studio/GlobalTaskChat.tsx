import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { clampTaskChatPosition, defaultTaskChatPosition, taskChatPanelGeometry, TASK_CHAT_STORAGE_KEY, type TaskChatPosition } from "./taskChatPosition";
import { getActiveClientId } from "../../app/activeClient";
import { dueInfo, listCrmTasks, listTaskNotifications, markTaskNotificationRead, TASK_STATUS, type CrmTask, type TaskAssignmentMessage } from "../../app/crm";
import "./globalTaskChat.css";

/** Persistent floating inbox, scoped by the backend to the current tenant and logged-in user. */
export default function GlobalTaskChat() {
  const clientId = getActiveClientId();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dragRef = useRef<{pointerId: number; originX: number; originY: number; initial: TaskChatPosition; moved: boolean} | null>(null);
  const suppressClickRef = useRef(false);
  const [position, setPosition] = useState<TaskChatPosition>(() => {
    const w = window.innerWidth, h = window.innerHeight;
    const defaultPosition = defaultTaskChatPosition(w, h, 173, 48);
    try {
      const stored = JSON.parse(window.localStorage.getItem(TASK_CHAT_STORAGE_KEY) || "null") as TaskChatPosition | null;
      return stored && Number.isFinite(stored.x) && Number.isFinite(stored.y)
        ? clampTaskChatPosition(stored, w, h, 173, 48) : defaultPosition;
    } catch { return defaultPosition; }
  });
  const [viewport, setViewport] = useState({width: window.innerWidth, height: window.innerHeight});
  const [triggerSize, setTriggerSize] = useState({width: 173, height: 48});
  const bounds = useCallback((pos: TaskChatPosition) => clampTaskChatPosition(pos,
    window.innerWidth, window.innerHeight,
    triggerRef.current?.offsetWidth || triggerSize.width, triggerRef.current?.offsetHeight || triggerSize.height
  ), [triggerSize.width, triggerSize.height]);
  useEffect(() => {
    const measure = () => {
      setViewport({width: window.innerWidth, height: window.innerHeight});
      const width = triggerRef.current?.offsetWidth || 173;
      const height = triggerRef.current?.offsetHeight || 48;
      setTriggerSize({width, height});
      setPosition((current) => clampTaskChatPosition(current, window.innerWidth, window.innerHeight, width, height));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  const onDragStart = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return;
    dragRef.current = {pointerId: event.pointerId, originX: event.clientX, originY: event.clientY,
      initial: position, moved: false};
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onDragMove = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const dx = event.clientX - drag.originX, dy = event.clientY - drag.originY;
    if (!drag.moved && Math.hypot(dx,dy) < 7) return;
    if (!drag.moved) setOpen(false);
    drag.moved = true;
    setPosition(bounds({x: drag.initial.x + dx, y: drag.initial.y + dy}));
  };
  const onDragEnd = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragRef.current = null;
    if (drag.moved) {
      suppressClickRef.current = true;
      const next = bounds({x: drag.initial.x + event.clientX - drag.originX,
        y: drag.initial.y + event.clientY - drag.originY});
      setPosition(next);
      try { window.localStorage.setItem(TASK_CHAT_STORAGE_KEY, JSON.stringify(next)); } catch { /* blocked storage */ }
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const onDragCancel = (event: ReactPointerEvent<HTMLButtonElement>) => {
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const [tab, setTab] = useState<"tasks" | "messages">("tasks");
  const [tasks, setTasks] = useState<CrmTask[]>([]);
  const [messages, setMessages] = useState<TaskAssignmentMessage[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    try {
      const [active, completed, notices] = await Promise.all([
        listCrmTasks(), listCrmTasks("completed"), listTaskNotifications(),
      ]);
      if (getActiveClientId() !== clientId) return;
      const byId = new Map<string, CrmTask>();
      for (const response of [active, completed]) {
        if (!response.available) throw new Error("As tarefas não estão disponíveis para este acesso.");
        for (const task of response.tasks || []) byId.set(task.id, task);
      }
      setTasks([...byId.values()].sort((a, b) => {
        const aDone = a.status === "completed" || a.status === "cancelled";
        const bDone = b.status === "completed" || b.status === "cancelled";
        return Number(aDone) - Number(bDone) || (a.due_date || "9999").localeCompare(b.due_date || "9999");
      }));
      setMessages(notices.messages || []);
      setUnread(notices.unread || 0);
      setError(null);
    } catch (cause) {
      if (getActiveClientId() === clientId) setError(cause instanceof Error ? cause.message : "Falha ao carregar tarefas.");
    } finally {
      if (getActiveClientId() === clientId) setLoading(false);
    }
  }, [clientId]);
  useEffect(() => {
    setTasks([]); setMessages([]); setUnread(0); setOpen(false); setError(null);
    void refresh();
    const timer = window.setInterval(() => void refresh(), 60000);
    return () => window.clearInterval(timer);
  }, [refresh]);
  async function view(message: TaskAssignmentMessage) {
    if (!message.read_at) {
      try {
        await markTaskNotificationRead(message.id);
        setMessages((previous) => previous.map((m) => m.id === message.id ? { ...m, read_at: new Date().toISOString() } : m));
        setUnread((n) => Math.max(0, n - 1));
      } catch { /* opening a task must not depend on marking the notice read */ }
    }
    window.location.assign("/tarefas?task=" + encodeURIComponent(message.task_id));
  }
  if (!clientId) return null;
  const pending = tasks.filter((t) => t.status !== "completed" && t.status !== "cancelled").length;
  const panel = taskChatPanelGeometry(position, viewport.width, viewport.height, triggerSize.width, triggerSize.height);
  return <div className="globalTaskChat" style={{left:position.x,top:position.y,right:"auto",bottom:"auto"}}>
    <button ref={triggerRef} type="button" className="globalTaskChatTrigger"
      aria-expanded={open} aria-controls="global-task-chat-panel"
      aria-label={open ? "Fechar chat de tarefas (arraste para mover)" : "Abrir chat de tarefas (arraste para mover)"}
      title="Arraste para posicionar; clique para abrir o chat de tarefas"
      onPointerDown={onDragStart} onPointerMove={onDragMove} onPointerUp={onDragEnd} onPointerCancel={onDragCancel}
      onClick={() => {
        if (suppressClickRef.current) { suppressClickRef.current = false; return; }
        setOpen((o) => !o); void refresh();
      }}>
      <i className="gtcFull">Chat de tarefas</i><i className="gtcShort">Tarefas</i> {pending ? <span>{pending}</span> : null}{unread ? <b>{unread} novas</b> : null}
    </button>
    {open ? <section id="global-task-chat-panel" className="globalTaskChatPanel"
      style={panel} aria-label="Tarefas da empresa ativa">
      <header><strong>Chat de tarefas</strong><div>
        <button type="button" onClick={() => void refresh()}>Atualizar</button>
        <button type="button" onClick={() => setOpen(false)}>Fechar</button>
      </div></header>
      <nav aria-label="Abas de tarefas">
        <button type="button" className={tab === "tasks" ? "selected" : ""} onClick={() => setTab("tasks")}>Todas as tarefas ({tasks.length})</button>
        <button type="button" className={tab === "messages" ? "selected" : ""} onClick={() => setTab("messages")}>Meus avisos ({unread})</button>
      </nav>
      {error ? <p className="globalTaskChatError" role="alert">{error}</p> : null}
      {loading && !tasks.length && !messages.length ? <p className="globalTaskChatEmpty">Carregando…</p> : null}
      {tab === "tasks" ? <div className="globalTaskChatList">
        {!loading && !error && !tasks.length ? <p className="globalTaskChatEmpty">Nenhuma tarefa disponível para este acesso. Confira o responsável e a visibilidade da tarefa.</p> : null}
        {tasks.map((t) => <a key={t.id} className="globalTaskChatItem" href={"/tarefas?task=" + encodeURIComponent(t.id)}>
          <strong>{t.title}</strong><span>{TASK_STATUS[t.status] || t.status} · {dueInfo(t.due_date).label}</span>
          {t.assignees?.length ? <small>{t.assignees.map((a) => a.name).join(", ")}</small> : t.assignee?.name ? <small>{t.assignee.name}</small> : null}
        </a>)}
      </div> : <div className="globalTaskChatList">
        {!loading && !error && !messages.length ? <p className="globalTaskChatEmpty">Nenhum aviso recebido ainda.</p> : null}
        {messages.map((m) => <button type="button" key={m.id} onClick={() => void view(m)} className={"globalTaskChatItem" + (m.read_at ? "" : " unread")}>
          <strong>{m.title}</strong><span>{m.body}</span>
        </button>)}
      </div>}
      <footer><a href="/tarefas">Abrir quadro de tarefas</a></footer>
    </section> : null}
  </div>;
}
