import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { getActiveClientId, getActiveClientName } from "../../app/activeClient";
import { CRM_UNAVAILABLE_TEXT, TASK_EVENT, TASK_PRIORITY, TASK_STATUS, createTask, deleteTask, dueInfo, listAssignees, listCrmTasks, taskApproval, taskHistory, updateTask, type CrmTask, type CrmUnavailable, type Person, type TaskScope, type TaskAction, type TaskEvent, type TaskInput, type TaskStatus } from "../../app/crm";
import Drawer from "../Drawer";
import { getPathForRoute } from "../../app/routes";
import { STUDIO_FORMATS, decideCalendarItem, getPipeline, listContacts, localParts, sendForApproval, updateCalendarItem, type PipelineItem, type Stage, type StudioStatus } from "../../app/studio";
import PostReview from "./PostReview";
import { OPEN, handleFromName, monthKey, sortTasks } from "./taskBoard.helpers";

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);


// Etapas que se escolhem à mão; as de aprovação só mudam pelas ações (enviar, aprovar, pedir ajuste).
const MANUAL: TaskStatus[] = ["pending", "in_progress", "completed", "cancelled"];
type Draft = { id?: string; title: string; notes: string; status: TaskStatus; priority: string; due_date: string; due_time: string;
  category: string; assignee_name: string; assignee_user_id: string; visible_to_client: boolean; needs_client_approval: boolean; deliverable_url: string };
const emptyDraft = (isAgency: boolean): Draft => ({ title: "", notes: "", status: "pending", priority: "", due_date: "", due_time: "",
  category: "", assignee_name: "", assignee_user_id: "", visible_to_client: !isAgency, needs_client_approval: true, deliverable_url: "" });
const toDraft = (t: CrmTask): Draft => ({ id: t.id, title: t.title, notes: t.notes || "", status: t.status, priority: t.priority || "",
  due_date: t.due_date || "", due_time: t.due_time || "", category: t.category || "", assignee_name: t.assignee?.name || "", assignee_user_id: t.assignee?.user_id || "",
  visible_to_client: Boolean(t.visible_to_client), needs_client_approval: t.needs_client_approval !== false, deliverable_url: t.deliverable_url || "" });

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
  const [showCancelled, setShowCancelled] = useState(false);
  const [who, setWho] = useState<string>("");
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
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
      assignee_name: draft.assignee_name.trim() || null, deliverable_url: draft.deliverable_url.trim() || null,
      ...(team?.length ? { assignee_user_id: draft.assignee_user_id || null } : {}),
      ...(isAgency ? { visible_to_client: draft.visible_to_client, needs_client_approval: draft.needs_client_approval } : {}) };
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

  async function openTask(task: CrmTask) {
    setDraft(toDraft(task)); setComment(""); setInternalNote(false); setHistory(null); setNotice(null); setSentLink(null);
    try { const out = await taskHistory(task.id); setHistory({ id: task.id, events: out.events }); } catch { setHistory({ id: task.id, events: [] }); }
  }

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

  /** Ações rápidas do card conforme a etapa e quem está vendo. */
  function quick(t: CrmTask): Quick[] {
    if (t.calendar_item_id) {
      const calendar: Quick = { label: "Calendário →", run: () => window.location.assign(getPathForRoute("calendar")) };
      if (!isAgency) return [{ ...calendar, label: "Abrir no Calendário →" }];
      if (t.status === "changes" || t.status === "in_progress") return [{ label: "Enviar ao cliente →", run: () => void calendarStep(t, "send"), tone: "primary" }, calendar];
      if (t.status === "internal_review") return [{ label: "Aprovar e enviar ao cliente", run: () => void calendarStep(t, "send"), tone: "primary" }, calendar];
      return [calendar];
    }
    if (t.status === "pending" && canManage) return [{ label: "Iniciar →", run: () => void move(t, "in_progress") }];
    if ((t.status === "in_progress" || t.status === "changes") && submitter) return [{ label: "Enviar p/ aprovação →", run: () => void act(t, "submit") }];
    if (t.status === "in_progress" && canManage) return [{ label: "Concluir ✓", run: () => void move(t, "completed") }];
    if (t.status === "internal_review" && approver) return [{ label: "Aprovar ✓", run: () => void act(t, "internal_approve"), tone: "primary" }, { label: "Ajuste", run: () => void openTask(t) }];
    if (t.status === "client_review") return [{ label: "Aprovar ✓", run: () => void act(t, "client_approve"), tone: "primary" }, { label: "Pedir ajuste", run: () => void openTask(t) }];
    return [];
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

  /** Ações do card de post: abrir a revisão (celular + comentário + botões) ou ir ao Calendário. */
  function postQuick(p: PipelineItem): Quick[] {
    const actions: Quick[] = [];
    if (p.stage === "com_cliente" || (isAgency && (p.stage === "revisao_interna" || p.stage === "ajuste"))) {
      actions.push({ label: p.stage === "ajuste" ? "Revisar" : "Aprovar / ajuste", run: () => { setReviewError(null); setReview(p); }, tone: "primary" });
    }
    if (isAgency) actions.push({ label: "Calendário →", run: () => window.location.assign(getPathForRoute("calendar")) });
    return actions;
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
  const postCards = posts.filter((p) => !linked.has(p.id) && (!q || `${p.title} ${p.caption_draft || ""}`.toLowerCase().includes(q)));
  const postsIn = (status: TaskStatus) => postCards.filter((p) => {
    const column = STAGE_COLUMN[p.stage];
    return (column === "internal_review" && !submitter ? "in_progress" : column) === status;
  }).slice(0, status === "completed" ? 8 : 40);
  const changeAction: TaskAction | null = current?.status === "internal_review" && approver ? "internal_changes" : current?.status === "client_review" ? "client_changes" : null;
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
    {scope.mine_only ? <p className="libHint taskMineOnly">Você vê as tarefas em que é responsável (ou que criou). Ao terminar, envie para a aprovação interna.</p> : null}
    <p className="libHint">{isAgency ? "Tarefas da empresa no Mugoverso. Marque \"Visível ao cliente\" para o cliente acompanhar." : "O que está em andamento com a Mugô para a sua empresa."}</p>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {notice && !draft ? <p role="status" className="studioOk">{notice}{sentLink ? <> <a href={sentLink.href} target="_blank" rel="noreferrer noopener">{sentLink.label}</a></> : null}</p> : null}
    {unavailable ? <div className="studioEmpty"><p>{CRM_UNAVAILABLE_TEXT[unavailable]}</p></div> : null}
    {loading && !tasks.length ? <p>Carregando…</p> : null}
    {!loading && !unavailable && !error && !tasks.length && !postCards.length ? <div className="studioEmpty"><p>Nenhuma tarefa para {clientName} ainda.{canManage ? " Clique em + Nova tarefa." : ""}</p></div> : null}
    {!unavailable && (tasks.length || postCards.length) ? <div className="kanban is-compact taskBoard" aria-label="Quadro de tarefas">
      {columns.map((status) => {
        const list = sortTasks(visible.filter((t) => t.status === status));
        const colPosts = who ? [] : postsIn(status);
        return <section key={status} className={`kanbanCol is-task-${status}`} aria-label={TASK_STATUS[status]}>
          <header><b>{TASK_STATUS[status]}</b><span>{list.length + colPosts.length}</span></header>
          {list.map((t) => <TaskCard key={t.id} task={t} onOpen={() => void openTask(t)} actions={busy ? [] : quick(t)} />)}
          {colPosts.map((p) => <PostCard key={`post-${p.id}`} post={p} onOpen={() => { setReviewError(null); setReview(p); }} actions={busy ? [] : postQuick(p)} />)}
          {!list.length && !colPosts.length ? <p className="taskColEmpty">Nada aqui.</p> : null}
        </section>;
      })}
    </div> : null}
    {review ? <PostReview item={review} handle={handleFromName(clientName)} busy={busy}
      error={reviewError} onClose={() => setReview(null)} onDecide={(status, note) => decidePost(review, status, note)} /> : null}
    <Drawer open={Boolean(draft)} title={draft?.id ? (canManage ? "Editar tarefa" : draft.title) : "Nova tarefa"} onClose={() => { if (!busy) setDraft(null); }}>
      {draft ? <form className="taskForm" onSubmit={save}>
        <fieldset disabled={!canManage || busy}>
          <label className="ds-field">Título<input required maxLength={200} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} placeholder="Ex.: Aprovar fotos do lançamento" /></label>
          <div className="taskFormRow">
            <label className="ds-field">Etapa<select value={draft.status} disabled={!MANUAL.includes(draft.status) || Boolean(current?.calendar_item_id)} onChange={(e) => setDraft({ ...draft, status: e.target.value as TaskStatus })}>
              {(MANUAL.includes(draft.status) ? MANUAL : [draft.status]).map((k) => <option key={k} value={k}>{TASK_STATUS[k]}</option>)}</select></label>
            <label className="ds-field">Prioridade<select value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: e.target.value })}>
              <option value="">Sem prioridade</option>{Object.entries(TASK_PRIORITY).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          </div>
          <div className="taskFormRow">
            <label className="ds-field">Prazo<input type="date" value={draft.due_date} onChange={(e) => setDraft({ ...draft, due_date: e.target.value })} /></label>
            <label className="ds-field">Hora<input type="time" value={draft.due_time} onChange={(e) => setDraft({ ...draft, due_time: e.target.value })} /></label>
          </div>
          <div className="taskFormRow">
            {team?.length ? <label className="ds-field">Responsável<select value={draft.assignee_user_id} disabled={scope.mine_only && !approver}
              onChange={(e) => { const p = team.find((x) => x.user_id === e.target.value); setDraft({ ...draft, assignee_user_id: e.target.value, assignee_name: p?.name || "" }); }}>
              <option value="">Sem responsável</option>
              {draft.assignee_user_id && !team.some((p) => p.user_id === draft.assignee_user_id) ? <option value={draft.assignee_user_id}>{draft.assignee_name || "Pessoa"}</option> : null}
              {team.map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}
            </select></label>
            : <label className="ds-field">Responsável<input maxLength={80} value={draft.assignee_name} onChange={(e) => setDraft({ ...draft, assignee_name: e.target.value })} placeholder="Nome" /></label>}
            <label className="ds-field">Categoria<input maxLength={60} value={draft.category} onChange={(e) => setDraft({ ...draft, category: e.target.value })} placeholder="Ex.: Conteúdo" /></label>
          </div>
          <label className="ds-field">Observações<textarea rows={4} maxLength={4000} value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} /></label>
          <label className="ds-field">Link da entrega (Drive, Canva, Figma…)<input type="url" maxLength={1000} placeholder="https://" value={draft.deliverable_url} onChange={(e) => setDraft({ ...draft, deliverable_url: e.target.value })} /></label>
          {isAgency ? <label className="taskCheck"><input type="checkbox" checked={draft.visible_to_client} onChange={(e) => setDraft({ ...draft, visible_to_client: e.target.checked })} /> Visível ao cliente</label> : null}
          {isAgency ? <label className="taskCheck"><input type="checkbox" checked={draft.needs_client_approval} disabled={!draft.visible_to_client} onChange={(e) => setDraft({ ...draft, needs_client_approval: e.target.checked })} /> Precisa da aprovação do cliente (depois da aprovação interna)</label> : null}
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

function TaskCard({ task: t, onOpen, actions }: { task: CrmTask; onOpen: () => void; actions: Quick[] }) {
  const due = dueInfo(t.due_date);
  const late = due.late && OPEN.includes(t.status);
  const urgent = t.priority === "urgent" || t.priority === "high";
  return <article className={`kanbanCard taskCard${late ? " is-late" : ""}`}>
    <button type="button" className="kanbanTitle" onClick={onOpen}>{t.title}</button>
    <div className="taskMeta">
      <span className={late ? "taskDue is-late" : "taskDue"}>{t.status === "completed" ? "✓ " : ""}{due.label}{t.due_time ? ` ${t.due_time.slice(0, 5)}` : ""}</span>
      {urgent ? <span className={`taskPrio is-${t.priority}`}>{TASK_PRIORITY[t.priority || ""]}</span> : null}
    </div>
    {t.calendar_item_id ? <span className="taskFromCalendar">Calendário</span> : null}
    {t.deliverable_url ? <a className="taskLink" href={t.deliverable_url} target="_blank" rel="noreferrer noopener">Entrega ↗</a> : null}
    {actions.length ? <div className="taskQuick">{actions.map((a) => <button key={a.label} type="button" className={`ds-link taskAdvance${a.tone === "primary" ? " is-primary" : " is-quiet"}`} onClick={a.run}>{a.label}</button>)}</div> : null}
    {t.assignee || t.category ? <small className="taskWho">
      {t.assignee ? <><i style={{ background: t.assignee.color || "#9aa3ad" }} aria-hidden="true" />{t.assignee.name}</> : null}
      {t.assignee && t.category ? " · " : ""}{t.category}
    </small> : null}
  </article>;
}

export function PostCard({ post: p, onOpen, actions }: { post: PipelineItem; onOpen: () => void; actions: Quick[] }) {
  const when = localParts(p.scheduled_at);
  const feedback = p.client_feedback?.action === "ajuste_solicitado" && p.client_feedback.comment ? p.client_feedback.comment : null;
  return <article className="kanbanCard taskCard taskPostCard">
    <span className="taskFromCalendar">Post · {STUDIO_FORMATS[p.format]}</span>
    <button type="button" className="kanbanTitle" onClick={onOpen}>{p.title}</button>
    <small className="taskPostMeta">{when.label} · {when.time}{p.request?.contact_name ? ` · com ${p.request.contact_name}` : ""}</small>
    {feedback ? <p className="kanbanNote">“{feedback}”{p.client_feedback?.reviewer_name ? ` — ${p.client_feedback.reviewer_name}` : ""}</p> : null}
    {actions.length ? <div className="taskQuick">{actions.map((a) => <button key={a.label} type="button" className={`ds-link taskAdvance${a.tone === "primary" ? " is-primary" : " is-quiet"}`} onClick={a.run}>{a.label}</button>)}</div> : null}
  </article>;
}
