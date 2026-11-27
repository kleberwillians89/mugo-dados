import { useEffect, useState, type ReactNode } from "react";
import { dueInfo, TASK_STATUS } from "../../app/crm";
import { getTaskContext, listWorkTasks, type PickableTask, type TaskContext, type WorkModule } from "../../app/taskWork";
import "../../styles/kanban-work.css";

const MODULE_LABEL: Record<WorkModule, string> = {
  email_marketing: "e-mail", social_media: "Social Media", midia_on: "Mídia On", redacao: "Redação", calendar: "Calendário", whatsapp: "WhatsApp",
};

/**
 * "Selecionar tarefa do Kanban" (compartilhado entre módulos): escolhe uma tarefa da empresa ATIVA, mostra o
 * briefing de forma legível e o entregável deste módulo. O que fazer com isso (gerar, escrever, retomar) é do módulo,
 * em ``actions``. Selecionar não muda a tarefa.
 */
export default function KanbanTaskStart({ module, onCancel, actions }: {
  module: WorkModule; onCancel: () => void;
  actions: (ctx: TaskContext, deliverable: string) => ReactNode;
}) {
  const [query, setQuery] = useState("");
  const [tasks, setTasks] = useState<PickableTask[] | null>(null);
  const [clientName, setClientName] = useState("");
  const [ctx, setCtx] = useState<TaskContext | null>(null);
  const [deliverable, setDeliverable] = useState("");
  const [other, setOther] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () => listWorkTasks(query).then((out) => { if (alive) { setTasks(out.tasks); setClientName(out.client_name); setError(""); } })
      .catch((cause) => { if (alive) { setTasks(null); setError(cause instanceof Error ? cause.message : "Não foi possível ler as tarefas."); } });
    // Sem busca, carrega na hora; com busca, espera a pessoa parar de digitar.
    const handle = query ? window.setTimeout(() => void load(), 300) : (void load(), 0);
    return () => { alive = false; if (handle) window.clearTimeout(handle); };
  }, [query]);

  async function pick(task: PickableTask) {
    setLoading(true); setError("");
    try {
      const out = await getTaskContext(task.id, module);
      setCtx(out);
      setDeliverable(out.suggested_deliverable || out.deliverables_for_module[0] || "");
      setOther("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível ler o briefing.");
    } finally { setLoading(false); }
  }

  if (ctx) {
    const c = ctx.context;
    const options = ctx.deliverables_for_module;
    const chosen = deliverable === "__outro" ? other.trim() : deliverable;
    return <div className="kwStart">
      <button type="button" className="ds-link is-quiet kwBack" onClick={() => setCtx(null)}>← Trocar tarefa</button>
      <section className="kwBrief" aria-label="Contexto da tarefa">
        <dl>
          <div><dt>Cliente</dt><dd>{ctx.client_name || clientName}</dd></div>
          <div><dt>Tarefa</dt><dd>{ctx.task.title}</dd></div>
          {c.title && c.title !== ctx.task.title ? <div><dt>Campanha</dt><dd>{c.title}</dd></div> : null}
          {c.objective ? <div><dt>Objetivo</dt><dd>{c.objective}</dd></div> : null}
          {c.key_message ? <div><dt>Mensagem</dt><dd>{c.key_message}</dd></div> : null}
          {c.offer ? <div><dt>Oferta</dt><dd>{c.offer}</dd></div> : null}
          {c.audience ? <div><dt>Público</dt><dd>{c.audience}</dd></div> : null}
          {c.deadline ? <div><dt>Prazo</dt><dd>{/^\d{4}-\d{2}-\d{2}$/.test(c.deadline) ? c.deadline.split("-").reverse().join("/") : c.deadline}</dd></div> : null}
          {c.goal ? <div><dt>Meta</dt><dd>{c.goal}</dd></div> : null}
          {c.your_part ? <div><dt>Sua parte</dt><dd>{c.your_part}</dd></div> : null}
          {c.avoid.length ? <div className="is-warning"><dt>Restrições</dt><dd>{c.avoid.join("; ")}</dd></div> : null}
        </dl>
        {!c.objective && !c.summary && c.notes ? <details><summary>Notas da tarefa</summary><p className="kwNotes">{c.notes}</p></details> : null}
        <small className="kwSource">{ctx.source === "briefing" ? "Do briefing de origem." : "Das notas da tarefa (sem briefing de origem)."}</small>
      </section>
      <fieldset className="kwDeliverable">
        <legend>O que você vai criar em {MODULE_LABEL[module]}?</legend>
        {options.map((d) => <label key={d}><input type="radio" name="kw-deliverable" checked={deliverable === d} onChange={() => setDeliverable(d)} /> {d}</label>)}
        <label><input type="radio" name="kw-deliverable" checked={deliverable === "__outro" || (!options.length && deliverable === "")}
          onChange={() => setDeliverable("__outro")} /> {options.length ? "Outro" : "Descreva o entregável"}</label>
        {deliverable === "__outro" || !options.length ? <input aria-label="Entregável" value={other} maxLength={160}
          placeholder={module === "email_marketing" ? "Ex.: E-mail promocional" : "O que será criado"} onChange={(e) => { setDeliverable("__outro"); setOther(e.target.value); }} /> : null}
      </fieldset>
      {actions(ctx, chosen)}
    </div>;
  }

  return <div className="kwStart">
    <div className="kwHead">
      <strong>Selecionar tarefa do Kanban{clientName ? ` · ${clientName}` : ""}</strong>
      <button type="button" className="ds-link is-quiet" onClick={onCancel}>Cancelar</button>
    </div>
    <input type="search" aria-label="Buscar tarefa" placeholder="Buscar pelo título" value={query} onChange={(e) => setQuery(e.target.value)} />
    {error ? <p className="kwError" role="alert">{error}</p> : null}
    {loading ? <p className="kwMuted" role="status">Lendo o briefing…</p> : null}
    {tasks === null && !error ? <p className="kwMuted">Carregando tarefas…</p>
      : tasks && !tasks.length ? <p className="kwMuted">{query ? "Nenhuma tarefa com esse título." : "Nenhuma tarefa aberta nesta empresa."}</p>
      : <ul className="kwList">{(tasks || []).map((t) => <li key={t.id}>
          <button type="button" onClick={() => void pick(t)} disabled={loading}>
            <strong>{t.title}</strong>
            <small>{[TASK_STATUS[t.status], t.category, t.due_date ? dueInfo(t.due_date).label : null, t.assignees.join(", ")].filter(Boolean).join(" · ")}</small>
          </button>
        </li>)}</ul>}
  </div>;
}
