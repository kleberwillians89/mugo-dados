import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { getActiveClientId, getActiveClientName } from "../../app/activeClient";
import { CRM_UNAVAILABLE_TEXT, TASK_EVENT, TASK_PRIORITY, TASK_STATUS, createTask, deleteTask, dueInfo, listAssignees, listCrmTasks, taskApproval, taskHistory, updateTask, type CrmTask, type CrmUnavailable, type Person, type TaskScope, type TaskAction, type TaskEvent, type TaskInput, type TaskStatus } from "../../app/crm";
import Drawer from "../Drawer";
import { getPathForRoute } from "../../app/routes";
import { STUDIO_FORMATS, decideCalendarItem, getPipeline, listContacts, localParts, sendForApproval, updateCalendarItem, type PipelineItem, type Stage, type StudioStatus } from "../../app/studio";
import PostReview from "./PostReview";
import AssigneePicker from "./AssigneePicker";
import { OPEN, displayName, handleFromName, monthKey, sortTasks } from "./taskBoard.helpers";
import { OPEN_TASK_EVENT } from "../shell/workKanban.helpers";
import "../../styles/studio.css";  // o quadro também aparece no Início, fora das telas do Studio

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const DEPARTMENTS = ["Desenvolvimento", "Design", "Mídia", "Social Media", "Criação", "Redação", "Dados", "CRM", "Operações", "Estratégia", "Atendimento"];




// Etapas que se escolhem à mão; as de aprovação só mudam pelas ações (enviar, aprovar, pedir ajuste).
const MANUAL: TaskStatus[] = ["pending", "in_progress", "completed", "cancelled"];
type Draft = { id?: string; title: string; notes: string; status: TaskStatus; priority: string; due_date: string; due_time: string;
  category: string; assignee_name: string; assignee_user_id: string; assignee_user_ids: string[]; visible_to_client: boolean; needs_client_approval: boolean; send_whatsapp: boolean; deliverable_url: string };
const emptyDraft = (isAgency: boolean): Draft => ({ title: "", notes: "", status: "pending", priority: "", due_date: "", due_time: "",
  category: "", assignee_name: "", assignee_user_id: "", assignee_user_ids: [], visible_to_client: !isAgency, needs_client_approval: false, send_whatsapp: true, deliverable_url: "" });
const toDraft = (t: CrmTask): Draft => ({ id: t.id, title: t.title, notes: t.notes || "", status: t.status, priority: t.priority || "",
  due_date: t.due_date || "", due_time: t.due_time || "", category: t.category || "", assignee_name: t.assignee?.name || "", assignee_user_id: t.assignee?.user_id || "",
  assignee_user_ids: (t.assignees || (t.assignee ? [t.assignee] : [])).map((a) => a.user_id).filter((id): id is string => Boolean(id)),
  visible_to_client: Boolean(t.visible_to_client), needs_client_approval: t.needs_client_approval === true, send_whatsapp: false, deliverable_url: t.deliverable_url || "" });

export type Quick = { label: string; run: () => void; tone?: "primary" | "quiet" };

// Posts do Fluxo de aprovação do Calendário no mesmo quadro (etapa do post → coluna da tarefa).
const STAGE_COLUMN: Record<Stage, TaskStatus> = { rascunho: "in_progress", revisao_interna: "internal_review", com_cliente: "client_review",
  ajuste: "changes", aprovado: "completed", publicado: "completed" };
const ACTION_DONE: Partial<Record<TaskAction, string>> = {
  submit: "Enviada para a aprovação interna.", internal_approve: "Aprovada internamente.", internal_changes: "Ajuste pedido.",
  client_approve: "Aprovada.", client_changes: "Ajuste pedido.", comment: "Comentário salvo.",
};

/**
 * Tarefas da empresa em quadro (mesmo modelo do Fluxo de aprovação do Calendário), guardadas no Mugoverso.
 * Equipe Mugô vê todas; o cliente vê as visíveis a ele. Quem tem "Gerenciar tarefas" cria, edita e move.
 */
export default function TaskBoard({ onRefreshRef, canManage = false, isAgency = false }: { onRefreshRef?: (fn: () => void) => void; canManage?: boolean; isAgency?: boolean }) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "empresa";
  const [tasks, setTasks] = useState<CrmTask[]>([]);
  const openedNotificationTask = useRef<string | null>(null);
  const [showCancelled, setShowCancelled] = useState(false);
  const [who, setWho] = useState<string>("");
  const [department, setDepartment] = useState("");
  const [taskView, setTaskView] = useState<"all" | "team" | "content">("team");
  const [dragging, setDragging] = useState<string | null>(null);
  const [dropColumn, setDropColumn] = useState<TaskStatus | null>(null);
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [allPeople, setAllPeople] = useState(false);  // Nova tarefa: mostrar todos os responsáveis, não só os da área
  const [busy, setBusy] = useState(false);
  const [unavailable, setUnavailable] = useState<CrmUnavailable["reason"] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [history, setHistory] = useState<{ id: string; events: TaskEvent[] } | null>(null);
  const [comment, setComment] = useState("");
  const [internalNote, setInternalNote] = useState(false);
  const [posts, setPosts] = useState<PipelineItem[]>([]);
  const [review, setReview] = useState<PipelineItem | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [sentLink, setSentLink] = useState<{ href: string; label: string } | null>(null);
  const [scope, setScope] = useState<TaskScope>({ mine_only: false, can_approve: false });
  const [team, setTeam] = useState<Person[] | null>(null);
  // Aprovação interna: equipe Mugô ou quem recebeu "Aprovar internamente". Enviar p/ aprovação: também o responsável.
  const approver = isAgency || scope.can_approve;
  const submitter = approver || scope.mine_only;

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
      const first = results.find((r) => r.available && "scope" in r) as { scope?: TaskScope } | undefined;
      if (first?.scope) setScope(first.scope);
      // Posts do Calendário (este mês e o próximo): sem eles o quadro de tarefas continua funcionando.
      try {
        const months = await Promise.all([getPipeline(monthKey(0)), getPipeline(monthKey(1))]);
        if (getActiveClientId() === clientId) setPosts(months.flatMap((m) => m.items || []));
      } catch { setPosts([]); }
    } catch (cause) { setError(message(cause, "Não foi possível carregar as tarefas.")); }
    finally { setLoading(false); }
  }, [clientId, showCancelled]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { onRefreshRef?.(() => void load()); }, [load, onRefreshRef]);
  // Integrantes da empresa para escolher o responsável (sem a lista, volta ao nome digitado).
  useEffect(() => {
    let alive = true;
    listAssignees().then((r) => { if (alive) setTeam(r.available ? r.people : []); }).catch(() => { if (alive) setTeam([]); });
    return () => { alive = false; };
  }, [clientId]);

  const people = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of tasks) for (const person of (t.assignees?.length ? t.assignees : t.assignee ? [t.assignee] : [])) {
      if (person.name) map.set(person.name, person.color || "#9aa3ad");
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [tasks]);

  const departments = useMemo(() => [...new Set([...DEPARTMENTS, ...tasks.map((t) => t.category).filter((v): v is string => Boolean(v))])].sort((a, b) => a.localeCompare(b)), [tasks]);
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return tasks.filter((t) => (!who || (who === "-" ? !(t.assignees?.length || t.assignee) :
      (t.assignees?.length ? t.assignees : t.assignee ? [t.assignee] : []).some((a) => a.name === who)))
      && (!department || t.category === department)
      && (taskView !== "content" || Boolean(t.calendar_item_id))
      && (!q || `${t.title} ${t.notes || ""} ${t.category || ""}`.toLowerCase().includes(q)));
  }, [tasks, who, department, taskView, query]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft || busy) return;
    if (draft.due_time && !draft.due_date) { setError("Escolha a data do prazo para usar a hora."); return; }
    const assignees = team?.length ? {
      // Legacy Render versions still accept only the primary assignee.
      // Send the new array only when it is needed for multiple people,
      // or when editing a previously multi-assigned task (including removal).
      assignee_user_id: draft.assignee_user_ids[0] || null,
      assignee_name: team.find((person) => person.user_id === draft.assignee_user_ids[0])?.name || null,
      ...((draft.assignee_user_ids.length > 1 ||
        (tasks.find((task) => task.id === draft.id)?.assignees?.length || 0) > 1)
        ? { assignee_user_ids: draft.assignee_user_ids } : {}),
    } : {};
    const base: TaskInput = { title: draft.title.trim(), notes: draft.notes.trim() || null, priority: draft.priority || null,
      due_date: draft.due_date || null, due_time: draft.due_time || null, category: draft.category.trim() || null,
      assignee_name: draft.assignee_name.trim() || null, deliverable_url: draft.deliverable_url.trim() || null, ...assignees };
    // Nova tarefa: sempre Pendente, interna (o cliente não vê) e sem WhatsApp. Editar nunca mexe em etapa, visibilidade
    // nem aprovação: isso muda só pelas ações da tarefa.
    const input: TaskInput = draft.id ? base
      : { ...base, status: "pending", send_whatsapp: false, ...(isAgency ? { visible_to_client: false, needs_client_approval: false } : {}) };
    setBusy(true); setError(null);
    try {
      if (draft.id) {
        await updateTask(draft.id, input);
        setNotice("Tarefa atualizada.");
      } else {
        await createTask(input);
        setNotice(draft.assignee_user_ids.length ? "Tarefa criada em Pendente. Os responsáveis foram avisados no chat de tarefas." : "Tarefa criada em Pendente.");
      }
      setDraft(null);
      await load();
    }
    catch (cause) { setError(message(cause, "Não foi possível salvar a tarefa.")); }
    finally { setBusy(false); }
  }

  async function move(task: CrmTask, status: TaskStatus) {
    setError(null);
    setTasks((current) => current.map((t) => (t.id === task.id ? { ...t, status } : t)));
    try { await updateTask(task.id, { status }); } catch (cause) { setError(message(cause, "Não foi possível mudar a etapa.")); await load(); }
  }

  /** Iniciar / Concluir de dentro da tarefa (mesma regra do arrastar: só etapas de execução). */
  async function stepTo(task: CrmTask, status: TaskStatus) {
    await move(task, status);
    setDraft((cur) => (cur && cur.id === task.id ? { ...cur, status } : cur));
    setNotice(status === "in_progress" ? "Tarefa iniciada: está Em produção." : "Tarefa concluída.");
  }

  async function dropTask(taskId: string, status: TaskStatus) {
    setDragging(null); setDropColumn(null);
    const task = tasks.find((t) => t.id === taskId);
    if (!task || task.status === status || !canManage || task.calendar_item_id ||
      !MANUAL.includes(task.status) || !MANUAL.includes(status)) return;
    await move(task, status);
  }

  async function openTask(task: CrmTask) {
    setDraft(toDraft(task)); setAllPeople(false); setComment(""); setInternalNote(false); setHistory(null); setNotice(null); setSentLink(null);
    try { const out = await taskHistory(task.id); setHistory({ id: task.id, events: out.events }); } catch { setHistory({ id: task.id, events: [] }); }
  }

  // Aviso de tarefa clicado no Kanban: abre aqui mesmo, só se a tarefa estiver no que este quadro carregou.
  const tasksRef = useRef(tasks);
  useEffect(() => { tasksRef.current = tasks; }, [tasks]);
  useEffect(() => {
    const onOpen = (event: Event) => {
      const id = (event as CustomEvent<{ taskId?: string }>).detail?.taskId;
      const task = id ? tasksRef.current.find((item) => item.id === id) : undefined;
      if (task) { openedNotificationTask.current = id!; void openTask(task); }
    };
    window.addEventListener(OPEN_TASK_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_TASK_EVENT, onOpen);
  });

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("task");
    if (!requested || openedNotificationTask.current === requested) return;
    const task = tasks.find((item) => item.id === requested);
    if (!task) return; // never fetch a task outside the viewer's authorized task scope
    openedNotificationTask.current = requested;
    void openTask(task);
  }, [tasks]);

  async function act(task: CrmTask, action: TaskAction, text?: string) {
    const needsText = action === "internal_changes" || action === "client_changes" || action === "comment";
    if (needsText && !(text || "").trim()) { await openTask(task); setError("Escreva o que precisa mudar e clique de novo."); return; }
    setBusy(true); setError(null); setNotice(null);
    try {
      const out = await taskApproval(task.id, action, text, internalNote && approver);
      setTasks((current) => current.map((t) => (t.id === task.id ? out.task : t)));
      if (draft?.id === task.id) { setDraft(toDraft(out.task)); setHistory({ id: task.id, events: out.events }); setComment(""); }
      setNotice(ACTION_DONE[action] || null);
    } catch (cause) { setError(message(cause, "Não foi possível concluir a ação.")); await load(); }
    finally { setBusy(false); }
  }

  /**
   * Tarefa ligada a um post do Calendário: a equipe move o POST (mesmo fluxo de aprovação) e a tarefa acompanha.
   * send = ajuste feito, manda ao cliente (WhatsApp do contato principal ou link); internal = volta à revisão interna;
   * approve = marca o post aprovado; changes = pede novo ajuste com o comentário.
   */
  async function calendarStep(task: CrmTask, step: "send" | "internal" | "approve" | "changes", note?: string) {
    const itemId = task.calendar_item_id;
    if (!itemId) return;
    if (step === "changes" && !(note || "").trim()) { await openTask(task); setError("Escreva o que precisa mudar e clique de novo."); return; }
    const post = posts.find((p) => p.id === itemId);
    setBusy(true); setError(null); setNotice(null); setSentLink(null);
    try {
      if (step === "send") {
        if (!post || post.status === "rejeitado" || post.status === "rascunho") await updateCalendarItem(itemId, { status: "em_revisao" });
        const month = (post?.scheduled_at || task.due_date || "").slice(0, 7) || monthKey(0);
        const { contacts, whatsapp_channel } = await listContacts().catch(() => ({ contacts: [], whatsapp_channel: "nao_configurado" as const }));
        const contact = contacts.find((c) => c.is_primary && c.receives.includes("conteudo")) || contacts.find((c) => c.receives.includes("conteudo")) || contacts.find((c) => c.is_primary);
        const viaWhatsapp = Boolean(contact) && whatsapp_channel === "mugozap";
        const out = await sendForApproval({ month, item_ids: [itemId],
          ...(contact ? { contact_id: contact.id, send_whatsapp: viaWhatsapp, notify_team: viaWhatsapp } : {}) });
        const delivered = viaWhatsapp && out.whatsapp?.status === "enviado";
        setNotice(delivered ? `Enviado ao cliente: ${contact!.name} recebeu o link no WhatsApp.` : "Link de aprovação criado. Envie ao cliente:");
        if (!delivered) setSentLink({ href: out.whatsapp_url || out.link, label: out.whatsapp_url ? "Abrir no WhatsApp ↗" : "Abrir o link ↗" });
      } else if (step === "internal") {
        await updateCalendarItem(itemId, { status: "em_revisao" });
        setNotice("Enviado para a aprovação interna.");
      } else if (step === "approve") {
        await updateCalendarItem(itemId, { status: "aprovado" });
        setNotice("Post aprovado.");
      } else {
        await updateCalendarItem(itemId, { status: "rejeitado", review_note: note!.trim() });
        setNotice("Ajuste pedido."); setComment("");
      }
      await load();
      if (draft?.id === task.id) {
        try { const h = await taskHistory(task.id); setHistory({ id: task.id, events: h.events }); } catch { /* histórico é opcional */ }
      }
    } catch (cause) { setError(message(cause, "Não foi possível concluir a ação no Calendário.")); await load(); }
    finally { setBusy(false); }
  }

  async function decidePost(post: PipelineItem, status: Extract<StudioStatus, "aprovado" | "rejeitado">, note?: string) {
    setBusy(true); setReviewError(null);
    try {
      await decideCalendarItem(post.id, status, note);
      setReview(null); setNotice(status === "aprovado" ? "Post aprovado." : "Ajuste pedido: a equipe foi avisada.");
      await load();
    } catch (cause) { setReviewError(message(cause, "Não foi possível salvar a decisão.")); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!draft?.id || busy || !window.confirm(`Excluir a tarefa "${draft.title}"?`)) return;
    setBusy(true); setError(null);
    try { await deleteTask(draft.id); setDraft(null); await load(); }
    catch (cause) { setError(message(cause, "Não foi possível excluir.")); }
    finally { setBusy(false); }
  }

  const flow: TaskStatus[] = submitter ? ["pending", "in_progress", "changes", "internal_review", "client_review", "completed"]
    : ["pending", "in_progress", "changes", "client_review", "completed"];
  const columns = (showCancelled ? [...flow, "cancelled"] : flow) as TaskStatus[];
  const current = draft?.id ? tasks.find((t) => t.id === draft.id) : undefined;
  // Post que já virou tarefa (ajuste) aparece só como tarefa; o resto entra como card de post.
  const linked = new Set(tasks.map((t) => t.calendar_item_id).filter(Boolean) as string[]);
  const q = query.trim().toLowerCase();
  const postCards = taskView !== "all" || department || who ? [] : posts.filter((p) => !linked.has(p.id) && (!q || `${p.title} ${p.caption_draft || ""}`.toLowerCase().includes(q)));
  const postsIn = (status: TaskStatus) => postCards.filter((p) => {
    const column = STAGE_COLUMN[p.stage];
    return (column === "internal_review" && !submitter ? "in_progress" : column) === status;
  }).slice(0, status === "completed" ? 8 : 40);
  const changeAction: TaskAction | null = current?.status === "internal_review" && approver ? "internal_changes" : current?.status === "client_review" ? "client_changes" : null;
  const late = visible.filter((t) => OPEN.includes(t.status) && dueInfo(t.due_date).late).length;

  return <div className="taskBoardWrap">
    <div className="taskWorkstreamNav" role="group" aria-label="Visão de tarefas">
      <button type="button" className={taskView === "team" ? "is-active" : ""} aria-pressed={taskView === "team"} onClick={() => setTaskView("team")}>Equipe e projetos</button>
      <button type="button" className={taskView === "all" ? "is-active" : ""} aria-pressed={taskView === "all"} onClick={() => setTaskView("all")}>Tudo + Calendário</button>
      <button type="button" className={taskView === "content" ? "is-active" : ""} aria-pressed={taskView === "content"} onClick={() => setTaskView("content")}>Conteúdo</button>
    </div>
    <div className="taskToolbar">
      <input type="search" placeholder="Buscar tarefa" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Buscar tarefa" />
      <select value={who} onChange={(e) => setWho(e.target.value)} aria-label="Responsável">
        <option value="">Todos os responsáveis</option>
        {people.map(([name]) => <option key={name} value={name}>{name}</option>)}
        <option value="-">Sem responsável</option>
      </select>
      <select value={department} onChange={(e) => setDepartment(e.target.value)} aria-label="Departamento">
        <option value="">Todos os departamentos</option>
        {departments.map((area) => <option key={area} value={area}>{area}</option>)}
      </select>
      <label className="taskToggle"><input type="checkbox" checked={showCancelled} onChange={(e) => setShowCancelled(e.target.checked)} /> Mostrar canceladas</label>
      {late ? <span className="taskLateBadge">{late} atrasada{late > 1 ? "s" : ""}</span> : null}
      {canManage ? <button type="button" className="ds-button is-primary taskNew" onClick={() => setDraft(emptyDraft(isAgency))}>+ Nova tarefa</button> : null}
    </div>
    {scope.mine_only ? <p className="libHint taskMineOnly">Você vê as tarefas em que é responsável (ou que criou). Ao terminar, envie para a aprovação interna.</p> : null}
    <p className="libHint">{isAgency ? "Quadro independente de tarefas para todas as áreas. Arraste os cartões entre as colunas de execução ou abra para editar e comentar. Itens em aprovação seguem seu próprio fluxo." : "Tarefas da sua empresa, com responsáveis, prazos e etapas."}</p>
    <div className="taskSummary" role="status"><strong>{visible.length}</strong> tarefas nesta visão <span>·</span> <strong>{visible.filter((t) => OPEN.includes(t.status)).length}</strong> abertas <span>·</span> <strong>{late}</strong> atrasadas</div>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {notice && !draft ? <p role="status" className="studioOk">{notice}{sentLink ? <> <a href={sentLink.href} target="_blank" rel="noreferrer noopener">{sentLink.label}</a></> : null}</p> : null}
    {unavailable ? <div className="studioEmpty"><p>{CRM_UNAVAILABLE_TEXT[unavailable]}</p></div> : null}
    {loading && !tasks.length ? <p>Carregando…</p> : null}
    {!loading && !unavailable && !error && !tasks.length && !postCards.length ? <div className="studioEmpty"><p>Nenhuma tarefa para {clientName} ainda.{canManage ? " Clique em + Nova tarefa." : ""}</p></div> : null}
    {!unavailable && (tasks.length || postCards.length) ? <div className="kanban is-compact taskBoard" aria-label="Quadro de tarefas">
      {columns.map((status) => {
        const list = sortTasks(visible.filter((t) => t.status === status));
        const colPosts = who ? [] : postsIn(status);
        return <section key={status} className={`kanbanCol is-task-${status}${dropColumn === status ? " is-drop-target" : ""}`} aria-label={TASK_STATUS[status]}
          onDragOver={(event) => { if (dragging && MANUAL.includes(status) && canManage) { event.preventDefault(); event.dataTransfer.dropEffect = "move"; setDropColumn(status); } }}
          onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDropColumn(null); }}
          onDrop={(event) => { event.preventDefault(); const id = event.dataTransfer.getData("text/plain") || dragging; if (id) void dropTask(id, status); }}>
          <header><b>{TASK_STATUS[status]}</b><span>{list.length + colPosts.length}</span></header>
          {list.map((t) => <div key={t.id}
            draggable={canManage && !busy && !t.calendar_item_id && MANUAL.includes(t.status)}
            onDragStart={(event) => { setDragging(t.id); event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("text/plain", t.id); }}
            onDragEnd={() => { setDragging(null); setDropColumn(null); }}
            className={dragging === t.id ? "is-task-dragging" : ""}>
            <TaskCard task={t} onOpen={() => void openTask(t)} />
          </div>)}
          {colPosts.map((p) => <PostCard key={`post-${p.id}`} post={p} onOpen={() => { setReviewError(null); setReview(p); }} />)}
          {!list.length && !colPosts.length ? <p className="taskColEmpty">Nada aqui.</p> : null}
          {canManage && status === "pending" ? <button type="button" className="taskAddCard"
            onClick={() => setDraft({ ...emptyDraft(isAgency), category: department })}>+ Nova tarefa</button> : null}
        </section>;
      })}
    </div> : null}
    {review ? <PostReview item={review} handle={handleFromName(clientName)} busy={busy}
      error={reviewError} onClose={() => setReview(null)} onDecide={(status, note) => decidePost(review, status, note)} /> : null}
    <Drawer open={Boolean(draft)} title={draft?.id ? (canManage ? "Editar tarefa" : draft.title) : "Nova tarefa"} onClose={() => { if (!busy) setDraft(null); }}>
      {draft ? <form className="taskForm" onSubmit={save}>
        <fieldset disabled={!canManage || busy}>
          <label className="ds-field">Título<input required maxLength={200} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} placeholder="Ex.: Criar peças para campanha de dezembro" /></label>
          <label className="ds-field">Tarefa<textarea rows={6} maxLength={4000} value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
            placeholder="Descreva o que precisa ser feito, orientações e informações necessárias." /></label>
          <label className="ds-field">Link da entrega (Drive, Canva, Figma…) <small>opcional</small><input type="url" maxLength={1000} placeholder="https://" value={draft.deliverable_url} onChange={(e) => setDraft({ ...draft, deliverable_url: e.target.value })} /></label>
          <label className="ds-field">Departamento<select value={draft.category} onChange={(e) => { setDraft({ ...draft, category: e.target.value }); setAllPeople(false); }}>
            <option value="">Selecione a área</option>
            {draft.category && !departments.includes(draft.category) ? <option value={draft.category}>{draft.category}</option> : null}
            {departments.map((area) => <option key={area} value={area}>{area}</option>)}
          </select></label>
          {team?.length ? <AssigneePicker team={team} area={draft.category} all={allPeople} onAll={() => setAllPeople(true)}
            selected={draft.assignee_user_ids} disabled={scope.mine_only && !approver}
            onChange={(ids) => setDraft((cur) => cur ? { ...cur, assignee_user_ids: ids } : cur)} />
            : <label className="ds-field">Responsável<input maxLength={80} value={draft.assignee_name} onChange={(e) => setDraft({ ...draft, assignee_name: e.target.value })} placeholder="Nome" /></label>}
          <div className="taskFormRow taskFormOptional">
            <label className="ds-field">Prioridade <small>opcional</small><select value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: e.target.value })}>
              <option value="">Sem prioridade</option>{Object.entries(TASK_PRIORITY).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
            <label className="ds-field">Prazo <small>opcional</small><input type="date" value={draft.due_date} onChange={(e) => setDraft({ ...draft, due_date: e.target.value })} /></label>
            <label className="ds-field">Hora <small>opcional</small><input type="time" value={draft.due_time} onChange={(e) => setDraft({ ...draft, due_time: e.target.value })} /></label>
          </div>
          {draft.due_time && !draft.due_date ? <p className="libHint" role="status">Para usar a hora, escolha também a data do prazo.</p> : null}
          {!draft.id ? <p className="libHint">A tarefa nasce em <b>Pendente</b>, só para a equipe. Os responsáveis recebem o aviso no chat de tarefas.</p> : null}
        </fieldset>
        {current ? <section className="taskApproval" aria-label="Aprovação">
          <p className={`taskStage is-${current.status}`}><b>{TASK_STATUS[current.status]}</b>{current.approval_round ? ` · rodada ${current.approval_round}` : ""}</p>
          {current.deliverable_url ? <a href={current.deliverable_url} target="_blank" rel="noreferrer noopener">Abrir a entrega ↗</a> : null}
          {current.calendar_item_id ? <p className="libHint">Ligada a um post do <b>Calendário</b>: o que fizer aqui vale lá também (e vice-versa). <a href={getPathForRoute("calendar")}>Abrir no Calendário →</a></p> : null}
          {current.calendar_item_id && isAgency ? <div className="taskApprovalActions">
            {current.status === "changes" || current.status === "in_progress" ? <>
              <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => void calendarStep(current, "send")}>Ajuste feito: enviar ao cliente</button>
              <button type="button" className="ds-button" disabled={busy} onClick={() => void calendarStep(current, "internal")}>Mandar para aprovação interna</button>
            </> : null}
            {current.status === "internal_review" ? <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => void calendarStep(current, "send")}>Aprovar e enviar ao cliente</button> : null}
            {current.status === "client_review" ? <>
              <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => void calendarStep(current, "approve")}>Cliente aprovou ✓</button>
              <button type="button" className="ds-button" disabled={busy} onClick={() => void calendarStep(current, "send")}>Reenviar ao cliente</button>
            </> : null}
          </div> : null}
          {!current.calendar_item_id && canManage && (current.status === "pending" || current.status === "in_progress") ? <div className="taskApprovalActions">
            {current.status === "pending" ? <button type="button" className="ds-button" disabled={busy} onClick={() => void stepTo(current, "in_progress")}>Iniciar</button> : null}
            {current.status === "in_progress" ? <button type="button" className="ds-button" disabled={busy} onClick={() => void stepTo(current, "completed")}>Concluir ✓</button> : null}
          </div> : null}
          {!current.calendar_item_id ? <div className="taskApprovalActions">
            {(current.status === "in_progress" || current.status === "changes" || current.status === "pending") && submitter ? <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => void act(current, "submit")}>Enviar para aprovação interna</button> : null}
            {current.status === "internal_review" && approver ? <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => void act(current, "internal_approve")}>{current.visible_to_client && current.needs_client_approval !== false ? "Aprovar e enviar ao cliente" : "Aprovar"}</button> : null}
            {current.status === "client_review" ? <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => void act(current, "client_approve")}>Aprovar</button> : null}
          </div> : null}
          <label className="ds-field">{changeAction ? "O que precisa mudar (ou um comentário)" : "Comentário"}<textarea rows={3} maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} /></label>
          {approver ? <label className="taskCheck"><input type="checkbox" checked={internalNote} onChange={(e) => setInternalNote(e.target.checked)} /> Comentário interno (o cliente não vê)</label> : null}
          <div className="taskApprovalActions">
            {changeAction && !current.calendar_item_id ? <button type="button" className="ds-button" disabled={busy || !comment.trim()} onClick={() => void act(current, changeAction, comment)}>Pedir ajuste</button> : null}
            {current.calendar_item_id && isAgency && (current.status === "internal_review" || current.status === "client_review") ? <button type="button" className="ds-button" disabled={busy || !comment.trim()} onClick={() => void calendarStep(current, "changes", comment)}>Pedir ajuste</button> : null}
            <button type="button" className="ds-button" disabled={busy || !comment.trim()} onClick={() => void act(current, "comment", comment)}>Comentar</button>
          </div>
          {notice ? <p role="status" className="studioOk">{notice}{sentLink ? <> <a href={sentLink.href} target="_blank" rel="noreferrer noopener">{sentLink.label}</a></> : null}</p> : null}
          <ol className="taskHistory" aria-label="Histórico">
            {history?.id === current.id ? (history.events.length ? [...history.events].reverse().map((e) => <li key={e.id} className={e.internal ? "is-internal" : ""}>
              <b>{e.actor_name || (e.actor_side === "mugo" ? "Equipe Mugô" : "Cliente")}</b> {TASK_EVENT[e.kind].toLowerCase()}{e.internal ? " (interno)" : ""}
              <small>{new Date(e.created_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</small>
              {e.comment ? <p>{e.comment}</p> : null}</li>) : <li className="taskHistoryEmpty">Sem histórico ainda.</li>) : <li className="taskHistoryEmpty">Carregando…</li>}
          </ol>
        </section> : null}
        {canManage ? <div className="taskFormActions">
          {draft.id ? <button type="button" className="ds-link is-quiet taskDanger" disabled={busy} onClick={() => void remove()}>Excluir</button> : <span />}
          <span className="taskFormButtons"><button type="button" className="ds-button" onClick={() => setDraft(null)}>Cancelar</button>
            <button className="ds-button is-primary" disabled={busy || !draft.title.trim()}>{busy ? "Salvando…" : draft.id ? "Salvar" : "Criar tarefa"}</button></span>
        </div> : null}
      </form> : null}
    </Drawer>
  </div>;
}

function TaskCard({ task: t, onOpen }: { task: CrmTask; onOpen: () => void }) {
  const due = dueInfo(t.due_date);
  const late = due.late && OPEN.includes(t.status);
  const urgent = t.priority === "urgent" || t.priority === "high";
  const people = t.assignees?.length ? t.assignees : t.assignee ? [t.assignee] : [];
  // Cartão só informativo: o que é, de quem, até quando. Para agir, abre a tarefa (clique em qualquer parte).
  return <article className={`kanbanCard taskCard${late ? " is-late" : ""}`} onClick={onOpen}>
    <button type="button" className="kanbanTitle" onClick={(e) => { e.stopPropagation(); onOpen(); }}>{t.title}</button>
    {t.status === "changes" && t.change_note ? <p className="taskChangeNote" title={t.change_note}>Ajustar: {t.change_note}</p> : null}
    {t.due_date || urgent ? <div className="taskMeta">
      {t.due_date ? <span className={late ? "taskDue is-late" : "taskDue"}>{t.status === "completed" ? "✓ " : ""}{due.label}{t.due_time ? ` ${t.due_time.slice(0, 5)}` : ""}</span> : null}
      {urgent ? <span className={`taskPrio is-${t.priority}`}>{TASK_PRIORITY[t.priority || ""]}</span> : null}
    </div> : null}
    {people.length || t.category || t.calendar_item_id ? <small className="taskWho">
      {people.map((person, index) => <span key={person.user_id || index} className="taskAssigneeBadge">
        <i style={{ background: person.color || "#9aa3ad" }} aria-hidden="true" />{displayName(person.name)}
      </span>)}
      {t.category && !(t.calendar_item_id && t.category === "Calendário") ? <span>{t.category}</span> : null}
      {t.calendar_item_id ? <span className="taskFromCalendar is-quiet">Calendário</span> : null}
    </small> : null}
  </article>;
}

export function PostCard({ post: p, onOpen }: { post: PipelineItem; onOpen: () => void }) {
  const when = localParts(p.scheduled_at);
  const feedback = p.client_feedback?.action === "ajuste_solicitado" && p.client_feedback.comment ? p.client_feedback.comment : null;
  return <article className="kanbanCard taskCard taskPostCard" onClick={onOpen}>
    <button type="button" className="kanbanTitle" onClick={(e) => { e.stopPropagation(); onOpen(); }}>{p.title}</button>
    {feedback ? <p className="taskChangeNote">Ajustar: {feedback}</p> : null}
    <small className="taskPostMeta">{when.label} · {when.time}</small>
    {p.stage === "com_cliente" ? <span className="taskWaiting">Esperando aprovação do cliente</span> : null}
    <small className="taskWho"><span className="taskFromCalendar is-quiet">Post · {STUDIO_FORMATS[p.format]}</span></small>
  </article>;
}
