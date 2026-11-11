import { useCallback, useEffect, useMemo, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { getPathForRoute } from "../app/routes";
import { BUDGET_LABELS, PROJECT_COLUMNS, brl, chatProject, createProject, deleteProject, generateProject, listProjects, projectToBrief,
  updateProject, type BudgetCategory, type ProductionPlan, type Project, type ProjectInputs, type ProjectKind, type ProjectStatus } from "../app/projects";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import "../styles/studio.css";

const COPY: Record<ProjectKind, { title: string; lead: string; newLabel: string; copilot: string; generate: string; empty: string }> = {
  planejamento: {
    title: "Planejamento", lead: "Objetivo e público entram; a IA monta o plano com os dados reais da marca. Aprovado, vira Briefing e desce para o time.",
    newLabel: "Novo planejamento", copilot: "Copiloto de estratégia", generate: "Gerar planejamento", empty: "Nenhum planejamento ainda.",
  },
  evento: {
    title: "Evento", lead: "Vídeo, fotos, evento ou podcast: a ideia e a data entram; a IA monta cronograma, equipe, orçamento e riscos.",
    newLabel: "Nova produção", copilot: "Assistente de produção", generate: "Gerar plano de produção", empty: "Nenhuma produção ainda.",
  },
};
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const fmtDate = (iso?: string | null) => (iso ? new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) : "");
type Run = <T>(key: string, fn: () => Promise<T>, fallback: string) => Promise<T | null>;

/** Planejamento (CSO) e Evento (produção RTV e eventos), trazidos da iAgência no layout do MUGOVERSO. Só a equipe. */
export default function ProjectsPage({ kind }: { kind: ProjectKind }) {
  const clientId = getActiveClientId();
  const copy = COPY[kind];
  const [projects, setProjects] = useState<Project[]>([]);
  const [formats, setFormats] = useState<string[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await listProjects(kind);
      if (getActiveClientId() !== clientId) return;
      setProjects(r.projects); setFormats(r.formats);
    } catch (cause) { setError(message(cause, "Não foi possível carregar.")); }
    finally { setLoading(false); }
  }, [clientId, kind]);
  useEffect(() => { void load(); }, [load]);

  const run: Run = async (key, fn, fallback) => {
    setBusy(key); setError(null);
    try { return await fn(); } catch (cause) { setError(message(cause, fallback)); return null; } finally { setBusy(null); }
  };
  const replace = (p: Project) => setProjects((list) => [p, ...list.filter((x) => x.id !== p.id)]);
  const current = useMemo(() => projects.find((p) => p.id === openId) || null, [projects, openId]);

  async function move(p: Project, status: ProjectStatus) {
    setProjects((list) => list.map((x) => (x.id === p.id ? { ...x, status } : x)));
    const r = await run(`m:${p.id}`, () => updateProject(kind, p.id, { status }), "Não foi possível mover.");
    if (!r) void load();
  }

  return <Shell title={copy.title} variant="editorial"><div className="ds-page studioPage projPage">
    <PageHeader company={getActiveClientName() || "empresa"} title={copy.title}
      controls={<button type="button" className="ds-button is-primary" onClick={() => { setCreating(true); setOpenId(null); }}>{copy.newLabel}</button>} />
    <p className="libIntro">{copy.lead}</p>
    {error ? <div className="ds-notice is-negative" role="alert"><p className="ds-noticeTitle">{error}</p></div> : null}
    {creating ? <NewProject kind={kind} formats={formats} busy={busy} run={run} onCancel={() => setCreating(false)}
      onCreated={(p) => { replace(p); setCreating(false); setOpenId(p.id); }} /> : null}

    {loading && !projects.length ? <p className="libHint">Carregando…</p> : null}
    {!loading && !projects.length && !creating ? <div className="libEmpty"><p>{copy.empty}</p>
      <button type="button" className="ds-button is-primary" onClick={() => setCreating(true)}>{copy.newLabel}</button></div> : null}
    {projects.length ? <div className="projBoard" aria-label="Quadro">{PROJECT_COLUMNS.map((col) => {
      const cards = projects.filter((p) => p.status === col.key);
      return <section key={col.key} className={`projCol is-${col.key}`} aria-label={col.label}
        onDragOver={(e) => e.preventDefault()} onDrop={(e) => { const id = e.dataTransfer.getData("text/plain"); const p = projects.find((x) => x.id === id); if (p && p.status !== col.key) void move(p, col.key); }}>
        <h3>{col.label}<small>{cards.length}</small></h3>
        {cards.map((p) => <button key={p.id} type="button" draggable className={`projCard${p.id === openId ? " is-open" : ""}`}
          onDragStart={(e) => e.dataTransfer.setData("text/plain", p.id)} onClick={() => { setOpenId(p.id); setCreating(false); }}>
          <b>{p.title}</b>
          <small>{[p.format, p.target_date ? `até ${fmtDate(p.target_date)}` : null, p.plan && Object.keys(p.plan).length ? "plano pronto" : "sem plano",
            p.brief_id ? "no Briefing" : null].filter(Boolean).join(" · ")}</small>
          {kind === "evento" && p.plan?.budget_total ? <span className="projMoney">{brl(p.plan.budget_total)}</span> : null}
        </button>)}
      </section>;
    })}</div> : null}

    {current ? <ProjectDetail key={current.id} kind={kind} project={current} formats={formats} busy={busy} run={run} onChange={replace}
      onDeleted={() => { setProjects((l) => l.filter((x) => x.id !== current.id)); setOpenId(null); }} onClose={() => setOpenId(null)} /> : null}
  </div></Shell>;
}

function NewProject({ kind, formats, busy, run, onCancel, onCreated }: { kind: ProjectKind; formats: string[]; busy: string | null; run: Run;
  onCancel: () => void; onCreated: (p: Project) => void }) {
  const [title, setTitle] = useState("");
  const [format, setFormat] = useState("");
  const [date, setDate] = useState("");
  const [inputs, setInputs] = useState<ProjectInputs>({});
  const set = (k: keyof ProjectInputs) => (e: { target: { value: string } }) => setInputs({ ...inputs, [k]: e.target.value });
  async function submit(generate: boolean) {
    const r = await run("create", () => createProject(kind, { title: title.trim(), format: format || undefined, target_date: date || undefined, inputs }), "Não foi possível criar.");
    if (!r) return;
    if (!generate) { onCreated(r.project); return; }
    const g = await run("gen", () => generateProject(kind, r.project.id), "Criado, mas a IA não conseguiu gerar o plano agora.");
    onCreated(g ? g.project : r.project);
  }
  return <section className="projNew" aria-label="Novo">
    <label>Nome<input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={kind === "planejamento" ? "Ex.: Natal 2026" : "Ex.: Lançamento da coleção na loja"} autoFocus /></label>
    {kind === "planejamento" ? <>
      <label>Objetivo de negócio<textarea rows={2} value={inputs.objective || ""} onChange={set("objective")} placeholder="Ex.: vender 300 kits de presente em dezembro" /></label>
      <label>Público<textarea rows={2} value={inputs.audience || ""} onChange={set("audience")} placeholder="Ex.: quem compra presente de última hora, 25 a 45" /></label>
      <label>Verba (opcional)<input value={inputs.budget || ""} onChange={set("budget")} placeholder="Ex.: R$ 8.000" /></label>
      <label>Prazo (opcional)<input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
    </> : <>
      <label>Formato<select value={format} onChange={(e) => setFormat(e.target.value)}><option value="">Escolha…</option>
        {formats.map((f) => <option key={f} value={f}>{f}</option>)}</select></label>
      <label>Data alvo<input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
      <label className="projWide">Ideia<textarea rows={2} value={inputs.idea || ""} onChange={set("idea")} placeholder="Ex.: ativação na loja com degustação, 80 convidados, fotos e Reels" /></label>
      <label>Local (opcional)<input value={inputs.location || ""} onChange={set("location")} /></label>
      <label>Verba (opcional)<input value={inputs.budget || ""} onChange={set("budget")} placeholder="Ex.: R$ 15.000" /></label>
    </>}
    <div className="postBriefingActions projWide">
      <button type="button" className="ds-button is-primary" disabled={busy !== null || !title.trim()} onClick={() => void submit(true)}>
        {busy === "create" || busy === "gen" ? "Gerando com IA…" : COPY[kind].generate}</button>
      <button type="button" className="ds-button" disabled={busy !== null || !title.trim()} onClick={() => void submit(false)}>Só criar o card</button>
      <button type="button" className="ds-button" onClick={onCancel}>Cancelar</button>
    </div>
  </section>;
}

function ProjectDetail({ kind, project, formats, busy, run, onChange, onDeleted, onClose }: { kind: ProjectKind; project: Project; formats: string[];
  busy: string | null; run: Run; onChange: (p: Project) => void; onDeleted: () => void; onClose: () => void }) {
  const [redo, setRedo] = useState("");
  const [briefId, setBriefId] = useState<string | null>(project.brief_id || null);
  const hasPlan = Boolean(project.plan && Object.keys(project.plan).length);
  const i = project.inputs || {};

  async function generate(useChat = false) {
    const r = await run("gen", () => generateProject(kind, project.id, { use_chat: useChat, instruction: redo.trim() || undefined }), "A IA não conseguiu gerar agora. Tente de novo.");
    if (r) { onChange(r.project); setRedo(""); }
  }
  async function toBrief() {
    const r = await run("brief", () => projectToBrief(kind, project.id), "Não foi possível mandar para o Briefing.");
    if (r) { setBriefId(r.brief.id); onChange({ ...project, brief_id: r.brief.id }); }
  }

  return <article className="briefDetail projDetail" aria-label={project.title}>
    <header className="projHead">
      <div><h2>{project.title}</h2>
        <small className="libHint">{[project.format, project.target_date ? `data alvo ${fmtDate(project.target_date)}` : null,
          i.objective, i.idea].filter(Boolean).join(" · ")}</small></div>
      <div className="projHeadActions">
        <select value={project.status} aria-label="Etapa" disabled={busy !== null}
          onChange={async (e) => { const r = await run("status", () => updateProject(kind, project.id, { status: e.target.value as ProjectStatus }), "Não foi possível mover."); if (r) onChange(r.project); }}>
          {PROJECT_COLUMNS.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}</select>
        {hasPlan ? <button type="button" className="ds-button" onClick={() => window.print()}>Imprimir</button> : null}
        <button type="button" className="ds-button" onClick={onClose}>Fechar</button>
      </div>
    </header>
    {kind === "evento" && !project.format ? <label className="projInline">Formato<select value="" onChange={async (e) => { const r = await run("fmt", () => updateProject(kind, project.id, { format: e.target.value }), "Não foi possível salvar."); if (r) onChange(r.project); }}>
      <option value="">Escolha…</option>{formats.map((f) => <option key={f} value={f}>{f}</option>)}</select></label> : null}

    <div className="projDetailGrid">
      <div className="projPlan">
        {!hasPlan ? <div className="libEmpty"><p>Ainda sem plano.</p>
          <button type="button" className="ds-button is-primary" disabled={busy !== null} onClick={() => void generate()}>{busy === "gen" ? "Gerando…" : COPY[kind].generate}</button></div>
          : kind === "planejamento" ? <StrategyView project={project} /> : <ProductionView project={project} busy={busy} run={run} onChange={onChange} />}
        {hasPlan ? <div className="postBriefingActions">
          <input className="briefRedo" value={redo} onChange={(e) => setRedo(e.target.value)} placeholder="Refazer pedindo… (opcional)" aria-label="Pedido para refazer" />
          <button type="button" className="ds-button" disabled={busy !== null} onClick={() => void generate()}>{busy === "gen" ? "Refazendo…" : "Refazer com IA"}</button>
        </div> : null}
        {hasPlan ? <div className="projToBrief">
          {briefId ? <p><b>Já está no Briefing.</b> Distribua para as telas e crie a tarefa de cada pessoa. <a href={getPathForRoute("briefing")}>Abrir Briefing →</a></p>
            : <p>Plano aprovado? Mande para o Briefing e distribua para Social Media, Mídia On, Redação, Criadores e o time.</p>}
          <button type="button" className={`ds-button${briefId ? "" : " is-primary"}`} disabled={busy !== null} onClick={() => void toBrief()}>
            {busy === "brief" ? "Montando o briefing…" : briefId ? "Mandar de novo" : "Mandar para o Briefing"}</button>
        </div> : null}
      </div>
      <Copilot kind={kind} project={project} busy={busy} run={run} onChange={onChange} onApply={() => void generate(true)} />
    </div>
    <button type="button" className="ds-link briefArchive" disabled={busy !== null} onClick={async () => {
      if (!window.confirm(`Apagar "${project.title}"?`)) return;
      const r = await run("del", () => deleteProject(kind, project.id), "Não foi possível apagar."); if (r) onDeleted();
    }}>Apagar</button>
  </article>;
}

function StrategyView({ project }: { project: Project }) {
  const p = project.plan;
  return <div className="projStrategy">
    {p.big_idea ? <p className="projBigIdea"><small>Grande ideia</small>{p.big_idea}</p> : null}
    <dl className="briefFacts">
      {p.context ? <><dt>Contexto</dt><dd>{p.context}</dd></> : null}
      {p.challenge ? <><dt>Desafio</dt><dd>{p.challenge}</dd></> : null}
      {p.insight ? <><dt>Insight</dt><dd>{p.insight}</dd></> : null}
      {p.strategy ? <><dt>Estratégia</dt><dd>{p.strategy}</dd></> : null}
      {p.messages?.length ? <><dt>Mensagens</dt><dd><ul>{p.messages.map((m) => <li key={m}>{m}</li>)}</ul></dd></> : null}
      {p.channels?.length ? <><dt>Canais</dt><dd><ul>{p.channels.map((c) => <li key={c.channel}><b>{c.channel}</b>: {c.role}</li>)}</ul></dd></> : null}
    </dl>
    {p.phases?.length ? <><h3>Fases</h3><ol className="projPhases">{p.phases.map((f) => <li key={f.phase}><b>{f.phase}</b><small>{f.when}</small><span>{f.what}</span></li>)}</ol></> : null}
    {p.kpis?.length ? <><h3>KPIs</h3><ul className="projKpis">{p.kpis.map((k) => <li key={k.kpi}><small>{k.kpi}</small><b>{k.target}</b></li>)}</ul></> : null}
    {p.risks?.length ? <><h3>Riscos</h3><ul className="projList">{(p.risks as string[]).map((r) => <li key={r}>{r}</li>)}</ul></> : null}
  </div>;
}

type Tab = "cronograma" | "equipe" | "orcamento" | "riscos" | "checklist";
const TABS: { key: Tab; label: string }[] = [
  { key: "cronograma", label: "Cronograma" }, { key: "equipe", label: "Equipe" }, { key: "orcamento", label: "Orçamento" },
  { key: "riscos", label: "Riscos" }, { key: "checklist", label: "Checklist" },
];
const IMPACT: Record<string, string> = { baixo: "Baixo", medio: "Médio", alto: "Alto" };

function ProductionView({ project, busy, run, onChange }: { project: Project; busy: string | null; run: Run; onChange: (p: Project) => void }) {
  const p = project.plan;
  const [tab, setTab] = useState<Tab>("cronograma");
  const [budget, setBudget] = useState(p.budget || []);
  const dirty = JSON.stringify(budget) !== JSON.stringify(p.budget || []);
  const total = budget.reduce((s, b) => s + (Number(b.value) || 0), 0);
  const byCat = (Object.keys(BUDGET_LABELS) as BudgetCategory[]).map((c) => ({ c, v: budget.filter((b) => b.category === c).reduce((s, b) => s + (Number(b.value) || 0), 0) })).filter((x) => x.v > 0);
  return <div className="projProduction">
    {p.summary ? <p className="briefLead">{p.summary}</p> : null}
    <div className="studioTabs" role="tablist">{TABS.map((t) => <button key={t.key} type="button" role="tab" aria-selected={tab === t.key}
      className={tab === t.key ? "is-active" : ""} onClick={() => setTab(t.key)}>{t.label}</button>)}</div>
    {tab === "cronograma" ? <ol className="projTimeline">{(p.timeline || []).map((t, n) => <li key={n}><span className="projDate">{t.date}</span><b>{t.phase}</b><span>{t.task}</span></li>)}</ol> : null}
    {tab === "equipe" ? <table className="projTable"><thead><tr><th>Função</th><th>Qtd.</th><th>Observação</th></tr></thead>
      <tbody>{(p.staff || []).map((s, n) => <tr key={n}><td>{s.role}</td><td>{s.qty}</td><td>{s.note}</td></tr>)}</tbody></table> : null}
    {tab === "orcamento" ? <div className="projBudget">
      <div className="projBudgetTotal"><small>Total estimado</small><b>{brl(total)}</b>
        {byCat.length ? <span className="projBudgetBar" aria-label="Divisão por categoria">{byCat.map((x) => <i key={x.c} title={`${BUDGET_LABELS[x.c]}: ${brl(x.v)}`} style={{ flexGrow: x.v }} />)}</span> : null}
        <span className="projBudgetLegend">{byCat.map((x) => <small key={x.c}>{BUDGET_LABELS[x.c]} {brl(x.v)}</small>)}</span></div>
      <table className="projTable"><thead><tr><th>Item</th><th>Categoria</th><th className="is-num">Valor (R$)</th><th /></tr></thead>
        <tbody>{budget.map((b, n) => <tr key={n}>
          <td><input value={b.item} aria-label="Item" onChange={(e) => setBudget(budget.map((x, k) => (k === n ? { ...x, item: e.target.value } : x)))} /></td>
          <td><select value={b.category} aria-label="Categoria" onChange={(e) => setBudget(budget.map((x, k) => (k === n ? { ...x, category: e.target.value as BudgetCategory } : x)))}>
            {(Object.keys(BUDGET_LABELS) as BudgetCategory[]).map((c) => <option key={c} value={c}>{BUDGET_LABELS[c]}</option>)}</select></td>
          <td className="is-num"><input type="number" min={0} step={50} value={b.value} aria-label="Valor" onChange={(e) => setBudget(budget.map((x, k) => (k === n ? { ...x, value: Number(e.target.value) } : x)))} /></td>
          <td><button type="button" className="ds-link" aria-label={`Tirar ${b.item}`} onClick={() => setBudget(budget.filter((_, k) => k !== n))}>Tirar</button></td>
        </tr>)}</tbody></table>
      <div className="postBriefingActions">
        <button type="button" className="ds-button" onClick={() => setBudget([...budget, { category: "outros", item: "Novo item", value: 0 }])}>Adicionar item</button>
        {dirty ? <button type="button" className="ds-button is-primary" disabled={busy !== null}
          onClick={async () => { const r = await run("budget", () => updateProject("evento", project.id, { plan: { ...p, budget } }), "Não foi possível salvar o orçamento."); if (r) onChange(r.project); }}>Salvar orçamento</button> : null}
      </div>
    </div> : null}
    {tab === "riscos" ? <table className="projTable"><thead><tr><th>Risco</th><th>Impacto</th><th>Como evitar</th></tr></thead>
      <tbody>{((p.risks || []) as ProductionPlan["risks"] & object).map((r, n) => <tr key={n}><td>{r.risk}</td><td><span className={`projImpact is-${r.impact}`}>{IMPACT[r.impact] || r.impact}</span></td><td>{r.mitigation}</td></tr>)}</tbody></table> : null}
    {tab === "checklist" ? <ul className="projChecklist">{(p.checklist || []).map((c) => <li key={c}><label><input type="checkbox" /> {c}</label></li>)}</ul> : null}
  </div>;
}

function Copilot({ kind, project, busy, run, onChange, onApply }: { kind: ProjectKind; project: Project; busy: string | null; run: Run;
  onChange: (p: Project) => void; onApply: () => void }) {
  const [text, setText] = useState("");
  const chat = project.chat || [];
  async function send() {
    const msg = text.trim();
    if (!msg) return;
    const r = await run("chat", () => chatProject(kind, project.id, msg), "O copiloto não respondeu agora.");
    if (r) { onChange(r.project); setText(""); }
  }
  return <aside className="projCopilot" aria-label={COPY[kind].copilot}>
    <h3>{COPY[kind].copilot}</h3>
    <div className="projChat">
      {!chat.length ? <p className="libHint">{kind === "planejamento" ? "Pergunte sobre o plano: canais, verba, mensagem, prazos." : "Pergunte sobre a produção: equipe, custo, prazo, plano B."}</p> : null}
      {chat.map((m, n) => <p key={n} className={`projMsg is-${m.role}`}>{m.content}</p>)}
      {busy === "chat" ? <p className="projMsg is-copiloto is-typing">Pensando…</p> : null}
    </div>
    <form onSubmit={(e) => { e.preventDefault(); void send(); }}>
      <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder="Escreva…" aria-label="Mensagem para o copiloto"
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} />
      <button type="submit" className="ds-button" disabled={busy !== null || !text.trim()}>Enviar</button>
    </form>
    {chat.length && Object.keys(project.plan || {}).length ? <button type="button" className="ds-button is-primary" disabled={busy !== null} onClick={onApply}>
      {busy === "gen" ? "Aplicando…" : "Aplicar a conversa no plano"}</button> : null}
  </aside>;
}
