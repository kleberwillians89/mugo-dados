import { useCallback, useEffect, useState, type FormEvent } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { createTask, listAssignees, listCrmTasks, updateTask, TASK_STATUS, type CrmTask, type Person, type TaskStatus } from "../../app/crm";
import { getPathForRoute } from "../../app/routes";
import "./campaignTasks.css";

const linkTag = (id: string) => `[MUGO_MEDIA_DRAFT:${id}]`;
const categories = ["Mídia", "Criação", "Design", "Desenvolvimento", "Dados", "CRM", "Operações"];
const checklist = [
  { title: "Definir objetivo, verba e datas", category: "Mídia" },
  { title: "Revisar públicos e exclusões", category: "Mídia" },
  { title: "Validar pixel, conversões e UTMs", category: "Dados" },
  { title: "Produzir e aprovar os criativos", category: "Criação" },
  { title: "Revisar landing page e links", category: "Desenvolvimento" },
  { title: "Conferir campanha pausada antes da ativação", category: "Mídia" },
] as const;

function errorText(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "Não foi possível atualizar as tarefas.";
}

/** Tasks remain real Mugoverso tasks, searchable in the global task board.
 * The explicit draft tag is a temporary cross-module association without a schema migration.
 * No external campaign is published by this component. */
export default function CampaignTasks({ draftId, campaignName }: { draftId: string; campaignName: string }) {
  const clientId = getActiveClientId();
  const [tasks, setTasks] = useState<CrmTask[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("Mídia");
  const [assigneeId, setAssigneeId] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [priority, setPriority] = useState("medium");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [open, completed, assignees] = await Promise.all([listCrmTasks(), listCrmTasks("completed"), listAssignees()]);
      if (getActiveClientId() !== clientId) return;
      const mine = new Map<string, CrmTask>();
      for (const result of [open, completed]) {
        if (!("available" in result) || !result.available) {
          throw new Error("As tarefas ainda não estão disponíveis para esta empresa.");
        }
        for (const task of result.tasks) {
          if ((task.notes || "").includes(linkTag(draftId))) mine.set(task.id, task);
        }
      }
      setTasks([...mine.values()]);
      setPeople(assignees.available ? assignees.people : []);
      setError(null);
    } catch (cause) { setError(errorText(cause)); }
    finally { if (getActiveClientId() === clientId) setLoading(false); }
  }, [clientId, draftId]);

  useEffect(() => { void load(); }, [load]);

  async function addTask(name: string, area: string) {
    const person = people.find((p) => p.user_id === assigneeId);
    return createTask({
      title: name,
      notes: `Campanha Mídia ON: ${campaignName}\n${linkTag(draftId)}`,
      category: area,
      status: "pending",
      priority,
      due_date: dueDate || null,
      assignee_user_id: person?.user_id || null,
      assignee_name: person?.name || null,
      visible_to_client: false,
      needs_client_approval: false,
    });
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!title.trim() || busy) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      await addTask(title.trim(), category);
      setTitle("");
      await load();
      setNotice("Tarefa criada e disponível no quadro geral.");
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(false); }
  }

  async function createChecklist() {
    if (busy) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      const existing = new Set(tasks.map((t) => t.title));
      let created = 0;
      for (const item of checklist) {
        if (existing.has(item.title)) continue;
        await addTask(item.title, item.category);
        existing.add(item.title);
        created++;
      }
      await load();
      setNotice(created ? `${created} tarefas de lançamento criadas.` : "O checklist já existe nesta campanha.");
    } catch (cause) {
      await load();
      setError(errorText(cause));
    } finally { setBusy(false); }
  }

  async function changeStatus(task: CrmTask, status: TaskStatus) {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      await updateTask(task.id, { status });
      await load();
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(false); }
  }

  return <section className="campaignTasks" aria-label="Tarefas da campanha">
    <div className="campaignTasksHeader">
      <div><h3>Tarefas desta campanha</h3><p>Organize mídia, design, desenvolvimento e toda a equipe. As tarefas aparecem também no quadro geral.</p></div>
      <button type="button" className="ds-button" onClick={() => void createChecklist()} disabled={busy || loading}>
        Criar checklist de lançamento
      </button>
    </div>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {notice ? <p role="status" className="studioOk">{notice}</p> : null}
    <form className="campaignTaskForm" onSubmit={(e) => void create(e)}>
      <label>Tarefa<input required maxLength={200} placeholder="Ex.: Configurar conversões da landing page" value={title} onChange={(e) => setTitle(e.target.value)} /></label>
      <label>Área<select value={category} onChange={(e) => setCategory(e.target.value)}>{categories.map((c) => <option key={c} value={c}>{c}</option>)}</select></label>
      <label>Responsável<select value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)}><option value="">A definir</option>{people.map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}</select></label>
      <label>Prazo<input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} /></label>
      <label>Prioridade<select value={priority} onChange={(e) => setPriority(e.target.value)}><option value="low">Baixa</option><option value="medium">Média</option><option value="high">Alta</option><option value="urgent">Urgente</option></select></label>
      <button type="submit" className="ds-button is-primary" disabled={busy || !title.trim()}>{busy ? "Salvando…" : "+ Criar tarefa"}</button>
    </form>
    {loading ? <p>Carregando tarefas…</p> : tasks.length ? <ul className="campaignTaskList">{tasks.map((t) => <li key={t.id}>
      <div><strong>{t.title}</strong><small>{t.category || "Equipe"} · {t.assignee?.name || "Sem responsável"}{t.due_date ? ` · até ${t.due_date.split("-").reverse().join("/")}` : ""}</small></div>
      <select aria-label={`Etapa de ${t.title}`} value={t.status} disabled={busy || !["pending","in_progress","completed","cancelled"].includes(t.status)}
        onChange={(e) => void changeStatus(t, e.target.value as TaskStatus)}>
        {Object.entries(TASK_STATUS).filter(([key]) => ["pending","in_progress","completed","cancelled"].includes(key) || key === t.status)
          .map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select>
    </li>)}</ul> : <p className="ds-caption">Ainda não há tarefas vinculadas a esta campanha.</p>}
    <a className="ds-link" href={getPathForRoute("tasks")}>Abrir quadro de tarefas completo</a>
  </section>;
}
