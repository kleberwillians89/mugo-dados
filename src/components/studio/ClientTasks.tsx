import { useCallback, useEffect, useState } from "react";
import { getActiveClientName } from "../../app/activeClient";
import { CRM_UNAVAILABLE_TEXT, TASK_STATUS, dueInfo, listClientTasks, taskApproval, type ClientTask, type CrmUnavailable, type TaskStatus } from "../../app/crm";
import { decideCalendarItem, getPipeline, type PipelineItem, type Stage, type StudioStatus } from "../../app/studio";
import PostReview from "./PostReview";
import { PostCard } from "./TaskBoard";
import { handleFromName, monthKey } from "./taskBoard.helpers";

// Posts do Calendário no quadro do cliente: o cliente só vê do envio para aprovação em diante.
const POST_COLUMN: Partial<Record<Stage, TaskStatus>> = { com_cliente: "client_review", ajuste: "in_progress", aprovado: "completed", publicado: "completed" };

/**
 * "Em andamento com a Mugô": tarefas que a Mugô marcou com a etiqueta "cliente" no CRM.
 * O cliente vê só isso; a agência vê o mesmo bloco (para conferir o que o cliente enxerga).
 */
export default function ClientTasks({ isAgency, clientId, standalone = false }: { isAgency: boolean; clientId: string; standalone?: boolean }) {
  const [tasks, setTasks] = useState<ClientTask[] | null>(null);
  const [unavailable, setUnavailable] = useState<CrmUnavailable["reason"] | null>(null);
  const [posts, setPosts] = useState<PipelineItem[]>([]);
  const [review, setReview] = useState<PipelineItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [asking, setAsking] = useState<string | null>(null);
  const [askNote, setAskNote] = useState("");
  const [taskError, setTaskError] = useState<string | null>(null);

  const loadTasks = useCallback(async (alive: () => boolean = () => true) => {
    try {
      const res = await listClientTasks();
      if (!alive()) return;
      if (res.available) { setTasks(res.tasks || []); setUnavailable(null); } else { setTasks([]); setUnavailable(res.reason); }
    } catch { if (alive()) setTasks([]); }
  }, []);
  useEffect(() => {
    let alive = true;
    void loadTasks(() => alive);
    return () => { alive = false; };
  }, [clientId, loadTasks]);

  /** Tarefa na "Aprovação do cliente": o cliente aprova ou pede ajuste (a equipe Mugô é avisada). */
  async function decideTask(task: ClientTask, action: "client_approve" | "client_changes") {
    if (action === "client_changes" && !askNote.trim()) { setTaskError("Escreva o que precisa mudar."); return; }
    setBusy(true); setTaskError(null); setNotice(null);
    try {
      await taskApproval(task.id, action, action === "client_changes" ? askNote.trim() : undefined);
      setAsking(null); setAskNote("");
      setNotice(action === "client_approve" ? "Tarefa aprovada. Obrigado!" : "Ajuste pedido: a equipe Mugô foi avisada.");
      await loadTasks();
    } catch (cause) { setTaskError(cause instanceof Error && cause.message ? cause.message : "Não foi possível salvar a decisão."); }
    finally { setBusy(false); }
  }

  // Quadro próprio (página Tarefas): entra junto o que está no Fluxo de aprovação do Calendário.
  const loadPosts = useCallback(async () => {
    if (!standalone) return;
    try {
      const months = await Promise.all([getPipeline(monthKey(0)), getPipeline(monthKey(1))]);
      setPosts(months.flatMap((m) => m.items || []).filter((p) => POST_COLUMN[p.stage]));
    } catch { setPosts([]); }
  }, [standalone]);
  useEffect(() => { void loadPosts(); }, [loadPosts, clientId]);

  async function decide(post: PipelineItem, status: Extract<StudioStatus, "aprovado" | "rejeitado">, note?: string) {
    setBusy(true); setReviewError(null);
    try {
      await decideCalendarItem(post.id, status, note);
      setReview(null); setNotice(status === "aprovado" ? "Post aprovado. Obrigado!" : "Ajuste pedido: a equipe Mugô foi avisada.");
      await loadPosts();
    } catch (cause) { setReviewError(cause instanceof Error && cause.message ? cause.message : "Não foi possível salvar a decisão."); }
    finally { setBusy(false); }
  }

  if (tasks === null) return null;
  const open = tasks.filter((t) => t.status !== "completed");
  const done = tasks.filter((t) => t.status === "completed").slice(0, 3);
  // Na Aprovação, sem tarefas (ou sem ligação com o CRM) o bloco some; na página própria, avisa.
  if (!isAgency && !tasks.length && !posts.length) return standalone ? <p className="studioEmpty">Nenhuma tarefa em andamento com a Mugô no momento.</p> : null;

  if (standalone && (tasks.length || posts.length)) {
    const cols = [["pending", open.filter((t) => t.status === "pending")], ["in_progress", open.filter((t) => t.status === "in_progress" || t.status === "changes")],
      ["client_review", open.filter((t) => t.status === "client_review")],
      ["completed", tasks.filter((t) => t.status === "completed").slice(0, 12)]] as const;
    const postsOf = (status: TaskStatus) => posts.filter((p) => POST_COLUMN[p.stage] === status)
      .sort((a, b) => (status === "completed" ? b.scheduled_at.localeCompare(a.scheduled_at) : a.scheduled_at.localeCompare(b.scheduled_at)))
      .slice(0, status === "completed" ? 8 : 40);
    const waiting = posts.filter((p) => p.stage === "com_cliente").length;
    return <>
      {waiting ? <p className="studioOk" role="status">{waiting === 1 ? "1 post esperando a sua aprovação." : `${waiting} posts esperando a sua aprovação.`}</p> : null}
      {notice ? <p className="studioOk" role="status">{notice}</p> : null}
      {review ? <PostReview item={review} handle={handleFromName(getActiveClientName() || "")} busy={busy} error={reviewError}
        onClose={() => setReview(null)} onDecide={(status, note) => decide(review, status, note)} /> : null}
      <div className="kanban is-compact taskBoard" aria-label="Quadro de tarefas">{cols.map(([status, list]) => {
      const cards = postsOf(status);
      return <section key={status} className={`kanbanCol is-task-${status}`} aria-label={TASK_STATUS[status]}>
        <header><b>{TASK_STATUS[status]}</b><span>{list.length + cards.length}</span></header>
        {cards.map((p) => <PostCard key={`post-${p.id}`} post={p} onOpen={() => { setReviewError(null); setNotice(null); setReview(p); }}
          actions={[{ label: p.stage === "com_cliente" ? "Aprovar / ajuste" : "Ver post", tone: p.stage === "com_cliente" ? "primary" : "quiet",
            run: () => { setReviewError(null); setNotice(null); setReview(p); } }]} />)}
        {list.map((t) => {
          const due = dueInfo(t.due_date);
          const late = due.late && t.status !== "completed";
          return <article key={t.id} className={`kanbanCard taskCard${late ? " is-late" : ""}`}>
            <b>{t.title}</b>
            <div className="taskMeta"><span className={late ? "taskDue is-late" : "taskDue"}>{t.status === "completed" ? "✓ " : ""}{due.label}</span></div>
            {t.status === "client_review" && !isAgency ? (asking === t.id ? <div className="taskAsk">
              <textarea rows={3} maxLength={2000} value={askNote} autoFocus placeholder="O que precisa mudar?" aria-label="O que precisa mudar"
                onChange={(e) => { setAskNote(e.target.value); setTaskError(null); }} />
              {taskError ? <p className="studioError" role="alert">{taskError}</p> : null}
              <div className="taskQuick">
                <button type="button" className="ds-link taskAdvance is-primary" disabled={busy} onClick={() => void decideTask(t, "client_changes")}>Enviar ajuste</button>
                <button type="button" className="ds-link taskAdvance is-quiet" disabled={busy} onClick={() => { setAsking(null); setTaskError(null); }}>Cancelar</button>
              </div>
            </div> : <div className="taskQuick">
              <button type="button" className="ds-link taskAdvance is-primary" disabled={busy} onClick={() => void decideTask(t, "client_approve")}>Aprovar ✓</button>
              <button type="button" className="ds-link taskAdvance is-quiet" disabled={busy} onClick={() => { setAsking(t.id); setAskNote(""); setTaskError(null); }}>Pedir ajuste</button>
            </div>) : null}
          </article>;
        })}
        {!list.length && !cards.length ? <p className="taskColEmpty">Nada aqui.</p> : null}
      </section>;
    })}</div></>;
  }

  return <section className="clientTasks" aria-label="Em andamento com a Mugô">
    <h2 className="crmGroupTitle">Em andamento com a Mugô {open.length ? <span>{open.length}</span> : null}</h2>
    {isAgency ? <p className="libHint">{unavailable ? CRM_UNAVAILABLE_TEXT[unavailable] : "O cliente vê aqui só as tarefas marcadas como visíveis ao cliente (em Tarefas), sem observações nem nomes da equipe."}</p> : null}
    {tasks.length ? <ul className="crmTaskList">{[...open, ...done].map((t) => {
      const due = dueInfo(t.due_date);
      const late = due.late && t.status !== "completed";
      return <li key={t.id} className={`crmTask is-${t.status}${late ? " is-late" : ""}`}>
        <div className="crmTaskMain"><b>{t.title}</b><small>{TASK_STATUS[t.status]}</small></div>
        <div className="crmTaskSide">{t.status === "completed" ? <span className="crmDue">✓ Concluída</span> : <span className={late ? "crmDue is-late" : "crmDue"}>{due.label}</span>}</div>
      </li>;
    })}</ul> : isAgency && !unavailable ? <p className="studioEmpty">Nenhuma tarefa visível ao cliente para esta empresa.</p> : null}
  </section>;
}
