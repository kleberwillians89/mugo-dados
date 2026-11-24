import { ArrowUpRight, BookmarkCheck, Building2, Compass, Search, TrendingUp } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { getPathForRoute } from "../app/routes";
import { BUDGET_LABELS, PROJECT_COLUMNS, brl, chatProject, createProject, deleteProject, generateProject, listProjects, projectToBrief,
  researchProject, updateProject, type ResearchCategory, type BudgetCategory, type ProductionPlan, type Project, type ProjectInputs, type ProjectKind, type ProjectStatus } from "../app/projects";
import { takeGoalsSectionRequest, takeNewProjectRequest } from "../app/newProjectRequest";
import GoalsPanel from "../components/goals/GoalsPanel";
import Shell from "../components/Shell";
import EventRadar from "../components/projects/EventRadar";
import { EventSuppliers, SupplierBook } from "../components/projects/Suppliers";
import PageHeader from "../components/data/PageHeader";
import "../styles/studio.css";

const COPY: Record<ProjectKind, { title: string; lead: string; newLabel: string; copilot: string; generate: string; empty: string }> = {
  planejamento: {
    title: "Planejamento", lead: "Objetivo e público entram; a IA monta o plano com os dados reais da marca. Aprovado, vira Briefing e desce para o time.",
    newLabel: "Novo planejamento", copilot: "Copiloto de estratégia", generate: "Gerar planejamento", empty: "Nenhum planejamento ainda.",
  },
  evento: {
    title: "Evento", lead: "Vídeo, fotos, evento ou podcast: a ideia, a data e o local entram; a IA lê o clima e as notícias da região e os fornecedores da marca e monta cronograma, equipe, orçamento, riscos e plano B.",
    newLabel: "Nova produção", copilot: "Assistente de produção", generate: "Gerar plano de produção", empty: "Nenhuma produção ainda.",
  },
};
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const fmtDate = (iso?: string | null) => (iso ? new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) : "");
type Run = <T>(key: string, fn: () => Promise<T>, fallback: string) => Promise<T | null>;


/** Planejamento (CSO) e Evento (produção RTV e eventos), trazidos da iAgência no layout do MUGOVERSO. Só a equipe. */
export default function ProjectsPage({ kind, goals = null }: { kind: ProjectKind;
  /** Planejamento: seção Metas (mesmos registros de /metas). null = a pessoa não vê Metas. */
  goals?: { canManage: boolean } | null }) {
  const clientId = getActiveClientId();
  const copy = COPY[kind];
  const [projects, setProjects] = useState<Project[]>([]);
  const [formats, setFormats] = useState<string[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [creating, setCreating] = useState(() => takeNewProjectRequest(kind));
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pageTab, setPageTab] = useState<"producoes" | "fornecedores">("producoes");
  const goalsRef = useRef<HTMLElement | null>(null);
  const [focusGoals] = useState(() => kind === "planejamento" && Boolean(goals) && takeGoalsSectionRequest());
  useEffect(() => { if (focusGoals) goalsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, [focusGoals]);

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

  // Estável entre renders: os painéis de fornecedores carregam em useEffect com ela.
  const run: Run = useCallback(async (key, fn, fallback) => {
    setBusy(key); setError(null);
    try { return await fn(); } catch (cause) { setError(message(cause, fallback)); return null; } finally { setBusy(null); }
  }, []) as Run;
  const replace = (p: Project) => setProjects((list) => [p, ...list.filter((x) => x.id !== p.id)]);
  const current = useMemo(() => projects.find((p) => p.id === openId) || null, [projects, openId]);

  async function move(p: Project, status: ProjectStatus) {
    setProjects((list) => list.map((x) => (x.id === p.id ? { ...x, status } : x)));
    const r = await run(`m:${p.id}`, () => updateProject(kind, p.id, { status }), "Não foi possível mover.");
    if (!r) void load();
  }

  return <Shell title={copy.title} variant="editorial"><div className="ds-page studioPage projPage mugoBrand">
    <PageHeader company={getActiveClientName() || "empresa"} title={copy.title}
      controls={<button type="button" className="ds-button is-primary" onClick={() => { setCreating(true); setOpenId(null); }}>{copy.newLabel}</button>} />
    <p className="libIntro">{copy.lead}</p>
    {kind === "evento" ? <div className="studioTabs projPageTabs" role="tablist" aria-label="Evento">
      {([["producoes", "Produções"], ["fornecedores", "Fornecedores"]] as const).map(([key, label]) => <button key={key} type="button" role="tab"
        aria-selected={pageTab === key} className={pageTab === key ? "is-active" : ""} onClick={() => setPageTab(key)}>{label}</button>)}
    </div> : null}
    {error ? <div className="ds-notice is-negative" role="alert"><p className="ds-noticeTitle">{error}</p></div> : null}
    {kind === "planejamento" && goals ? <section id="metas" ref={goalsRef} className="projGoals" aria-labelledby="planning-goals-title" style={{ margin: "8px 0 24px" }}>
      <GoalsPanel canManage={goals.canManage} intro={false} header={(newButton) => <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div><h2 id="planning-goals-title" style={{ margin: 0 }}>Metas</h2><p className="libHint" style={{ margin: "4px 0 0" }}>Indicadores medidos da empresa no período (os mesmos da página Metas).</p></div>
        {newButton}
      </div>} />
    </section> : null}
    {kind === "evento" && pageTab === "fornecedores" ? <SupplierBook busy={busy} run={run} /> : <>
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
    </>}
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
  const [section, setSection] = useState<"plan" | "research">("plan");
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
    <div className="studioTabs projResearchNav" role="group" aria-label="Seções do projeto">
      <button type="button" aria-pressed={section === "plan"} className={section === "plan" ? "is-active" : ""} onClick={() => setSection("plan")}>Plano</button>
      <button type="button" aria-pressed={section === "research"} className={section === "research" ? "is-active" : ""} onClick={() => setSection("research")}>Pesquisa</button>
    </div>
    <div hidden={section !== "research"}><ResearchPanel project={project} busy={busy} run={run} onChange={onChange} /></div>
    <div hidden={section !== "plan"}>
    {kind === "evento" && !project.format ? <label className="projInline">Formato<select value="" onChange={async (e) => { const r = await run("fmt", () => updateProject(kind, project.id, { format: e.target.value }), "Não foi possível salvar."); if (r) onChange(r.project); }}>
      <option value="">Escolha…</option>{formats.map((f) => <option key={f} value={f}>{f}</option>)}</select></label> : null}

    {kind === "evento" ? <label className="projInline">Local<input defaultValue={i.location || ""} maxLength={600} placeholder="Cidade ou endereço (ex.: Rua X, São Paulo)"
      onBlur={async (e) => { const location = e.target.value.trim(); if (location === (i.location || "")) return;
        const r = await run("loc", () => updateProject(kind, project.id, { inputs: { ...i, location } }), "Não foi possível salvar o local."); if (r) onChange(r.project); }} /></label> : null}
    {kind === "evento" ? <EventRadar project={project} busy={busy} run={run} onChange={onChange} /> : null}
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
    </div>
    <button type="button" className="ds-link briefArchive" disabled={busy !== null} onClick={async () => {
      if (!window.confirm(`Apagar "${project.title}"?`)) return;
      const r = await run("del", () => deleteProject(kind, project.id), "Não foi possível apagar."); if (r) onDeleted();
    }}>Apagar</button>
  </article>;
}

const RESEARCH_LABELS: Record<ResearchCategory, string> = {
  references: "Cases e referências", suppliers: "Locais e fornecedores", market: "Sinais de mercado",
};
const RESEARCH_CATEGORIES = Object.keys(RESEARCH_LABELS) as ResearchCategory[];
const RESEARCH_ICONS = { references: Compass, suppliers: Building2, market: TrendingUp };
const RESEARCH_TERMS = { references: "cases e ativações", suppliers: "locais e fornecedores", market: "tendências de mercado" };
const PRICE_LABELS = { published: "Preço publicado", estimate: "Estimativa", quoted: "Cotação confirmada" } as const;
const SOURCE_LABELS: Record<string, string> = {
  ok: "Consulta concluída", empty: "Sem resultados", partial: "Consulta parcial", unavailable: "Consulta indisponível", not_configured: "Busca externa ainda não configurada",
};

function ResearchPanel({ project, busy, run, onChange }: { project: Project; busy: string | null; run: Run; onChange: (p: Project) => void }) {
  const research = project.research || project.plan?.research;
  const [queries, setQueries] = useState(project.research?.queries || {});
  const [topic, setTopic] = useState("");
  const [city, setCity] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [category, setCategory] = useState<ResearchCategory | "all">("all");
  const [days, setDays] = useState(0);
  const [onlySelected, setOnlySelected] = useState(false);
  const [price, setPrice] = useState<{ url: string; value: string; kind: keyof typeof PRICE_LABELS; date: string } | null>(null);
  const selected = project.research?.selected || [];
  const items = research?.items || [];
  const since = days ? Date.now() - days * 86_400_000 : 0;
  const visible = items.filter((item) =>
    (category === "all" || category === (item.category || "references")) &&
    (!onlySelected || selected.includes(item.url)) &&
    (!since || Date.parse(item.researched_at) >= since));
  const categories = category === "all" ? RESEARCH_CATEGORIES : [category];
  const searchDraft = Object.fromEntries(categories.map((key) => [key,
    [topic.trim(), city.trim(), RESEARCH_TERMS[key]].filter(Boolean).join(" ").slice(0, 180)]));
  return <section className="projResearch" aria-label="Pesquisa de mercado">
    <header className="projResearchIntro">
      <Compass size={24} aria-hidden="true" />
      <div><h3>Pesquisa de mercado</h3><p>Encontre cases, fornecedores e sinais para este projeto.</p></div>
    </header>
    <form className="projResearchForm" onSubmit={async (e) => {
      e.preventDefault();
      const submitted = advanced ? queries : searchDraft;
      const result = await run("research", () => researchProject(project.kind, project.id, submitted), "Não foi possível pesquisar.");
      if (result) { setQueries(submitted); setOnlySelected(false); setDays(0); onChange(result.project); }
    }}>
      <div className="projResearchFields">
        <label className="projInline">Tema ou serviço<input value={topic} maxLength={110}
          placeholder="Ex.: ativação de beach tennis" onChange={(e) => {
            setTopic(e.target.value);
            setAdvanced(false);
          }} /></label>
        <label className="projInline">Cidade<input value={city} maxLength={40}
          placeholder="Ex.: São Paulo" onChange={(e) => { setCity(e.target.value); setAdvanced(false); }} /></label>
        <button className="ds-button is-primary" disabled={busy !== null ||
          !(advanced ? Object.values(queries).some((value) => value.trim()) : topic.trim())}>
          <Search size={16} aria-hidden="true" /> {busy === "research" ? "Pesquisando…" : "Pesquisar"}
        </button>
      </div>
      <div className="projResearchOptions">
        <small>Envie ao buscador apenas termos públicos.</small>
        <button type="button" className="ds-link" aria-expanded={advanced} onClick={() => {
          if (!advanced && topic.trim()) setQueries(searchDraft);
          setAdvanced(!advanced);
        }}>{advanced ? "Ocultar consultas" : "Editar consultas"}</button>
      </div>
      {advanced ? <div className="projResearchQueries">{RESEARCH_CATEGORIES.map((key) =>
        <label key={key} className="projInline">{RESEARCH_LABELS[key]}
          <input value={queries[key] || ""} maxLength={180} onChange={(e) => setQueries({ ...queries, [key]: e.target.value })} />
        </label>)}</div> : null}
    </form>
    <div className="projResearchFilters">
      <div className="projResearchCategories" role="group" aria-label="Categoria de pesquisa">
        {(["all", ...RESEARCH_CATEGORIES] as const).map((key) =>
          <button type="button" className="ds-button" key={key} aria-pressed={category === key} onClick={() => setCategory(key)}>
            {key === "all" ? "Todos" : RESEARCH_LABELS[key]}
          </button>)}
      </div>
      <label className="projInline">Data da consulta<select value={days} onChange={(e) => setDays(Number(e.target.value))}>
        <option value={0}>Qualquer data</option><option value={7}>Últimos 7 dias</option><option value={30}>Últimos 30 dias</option>
      </select></label>
      <button type="button" className="ds-button" aria-pressed={onlySelected} onClick={() => setOnlySelected(!onlySelected)}>
        <BookmarkCheck size={16} aria-hidden="true" /> Selecionados ({selected.length})
      </button>
    </div>
    {research ? <div className="projResearchStatus" role="status">
      <strong>{SOURCE_LABELS[research.status]} · {visible.length} {visible.length === 1 ? "resultado" : "resultados"}</strong>
      {RESEARCH_CATEGORIES.filter((key) => research.sources?.[key]).map((key) =>
        <small key={key}>{RESEARCH_LABELS[key]} · {SOURCE_LABELS[research.sources?.[key] || ""]}</small>)}
    </div> : null}
    {!visible.length && busy !== "research" ? <div className="projResearchEmpty">
      {items.length ? "Nenhum resultado corresponde aos filtros." : research ? "Nenhuma fonte disponível nesta consulta." : "Pesquise um tema para começar a reunir referências."}
    </div> : null}
    <div className="projResearchCards">{visible.map((item) => {
      const key = item.category || "references";
      const Icon = RESEARCH_ICONS[key];
      let source = "";
      try { source = new URL(item.url).hostname; } catch { /* fonte sem domínio */ }
      const saved = selected.includes(item.url);
      return <article key={item.url} className="projResearchCard" data-category={key} data-selected={saved}>
      <header><span className="projResearchIcon"><Icon size={19} aria-hidden="true" /></span><small>{RESEARCH_LABELS[key]}</small></header>
      <h4>{item.title}</h4>
      {item.summary ? <p>{item.summary}</p> : null}
      <div className="projResearchSource">
        {item.url.startsWith("https://") ? <a href={item.url} target="_blank" rel="noreferrer">{source || "Abrir fonte"} <ArrowUpRight size={14} aria-hidden="true" /></a> : null}
        {item.researched_at ? <small>Consultado em {fmtDate(item.researched_at)}</small> : null}
      </div>
      {project.research ? <label><input type="checkbox" checked={selected.includes(item.url)}
        disabled={busy !== null || (selected.length >= 10 && !selected.includes(item.url))}
        onChange={async (e) => {
          const next = e.target.checked ? [...selected, item.url] : selected.filter((url) => url !== item.url);
          const result = await run("research-select", () => researchProject(project.kind, project.id, { selected: next }), "Não foi possível salvar a seleção.");
          if (result) onChange(result.project);
        }} /> Usar no plano e briefing</label> : null}
      {item.category === "suppliers" && project.kind === "evento" ? <div>
        <small> · {project.plan?.budget?.some((line) => line.source_url === item.url) ? "Valor registrado no orçamento" : "A cotar"}</small>{" "}
        <button type="button" className="ds-button" disabled={busy !== null || !project.plan?.timeline?.length || ((project.plan.budget?.length || 0) >= 30 && !project.plan.budget?.some((line) => line.source_url === item.url))}
          onClick={() => {
            const existing = project.plan.budget?.find((line) => line.source_url === item.url);
            setPrice({ url: item.url, value: existing ? String(existing.value) : "", kind: existing?.price_kind || "published", date: existing?.price_date || "" });
          }}>{project.plan?.budget?.some((line) => line.source_url === item.url) ? "Editar valor" : "Adicionar ao orçamento"}</button>
        {price?.url === item.url ? <form onSubmit={async (e) => {
          e.preventDefault();
          const value = Number(price.value);
          if (!Number.isFinite(value) || value <= 0 || !price.date) return;
          const budget = project.plan.budget || [];
          const updated = [...budget.filter((line) => line.source_url !== item.url), {
            item: item.title, category: "outros" as const, value, source_url: item.url, price_kind: price.kind, price_date: price.date,
          }];
          const result = await run("research-budget", () => updateProject(project.kind, project.id, { plan: { ...project.plan, budget: updated } }), "Não foi possível salvar o valor.");
          if (result) { onChange(result.project); setPrice(null); }
        }}>
          <label>Valor (R$) <input type="number" value={price.value} min="0.01" step="0.01" required onChange={(e) => setPrice({ ...price, value: e.target.value })} /></label>{" "}
          <label>Origem <select value={price.kind} onChange={(e) => setPrice({ ...price, kind: e.target.value as keyof typeof PRICE_LABELS })}>
            {Object.entries(PRICE_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select></label>{" "}
          <label>Data <input type="date" required value={price.date} onChange={(e) => setPrice({ ...price, date: e.target.value })} /></label>{" "}
          <button className="ds-button" disabled={busy !== null}>Salvar valor</button>
        </form> : null}
      </div> : null}
    </article>; })}</div>
  </section>;
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

type Tab = "cronograma" | "equipe" | "fornecedores" | "orcamento" | "riscos" | "checklist";
const TABS: { key: Tab; label: string }[] = [
  { key: "cronograma", label: "Cronograma" }, { key: "equipe", label: "Equipe" }, { key: "fornecedores", label: "Fornecedores" },
  { key: "orcamento", label: "Orçamento" }, { key: "riscos", label: "Riscos" }, { key: "checklist", label: "Checklist" },
];
const IMPACT: Record<string, string> = { baixo: "Baixo", medio: "Médio", alto: "Alto" };

function ProductionView({ project, busy, run, onChange }: { project: Project; busy: string | null; run: Run; onChange: (p: Project) => void }) {
  const p = project.plan;
  const [tab, setTab] = useState<Tab>("cronograma");
  const [budget, setBudget] = useState(p.budget || []);
  useEffect(() => setBudget(p.budget || []), [p.budget]);
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
    {tab === "fornecedores" ? <EventSuppliers project={project} busy={busy} run={run} onProjectChange={(next) => { onChange(next); setBudget(next.plan?.budget || []); }} /> : null}
    {tab === "orcamento" ? <div className="projBudget">
      <div className="projBudgetTotal"><small>Total estimado</small><b>{brl(total)}</b>
        {byCat.length ? <span className="projBudgetBar" aria-label="Divisão por categoria">{byCat.map((x) => <i key={x.c} title={`${BUDGET_LABELS[x.c]}: ${brl(x.v)}`} style={{ flexGrow: x.v }} />)}</span> : null}
        <span className="projBudgetLegend">{byCat.map((x) => <small key={x.c}>{BUDGET_LABELS[x.c]} {brl(x.v)}</small>)}</span></div>
      <table className="projTable"><thead><tr><th>Item</th><th>Categoria</th><th className="is-num">Valor (R$)</th><th /></tr></thead>
        <tbody>{budget.map((b, n) => <tr key={n}>
          <td><input value={b.item} aria-label="Item" onChange={(e) => setBudget(budget.map((x, k) => (k === n ? { ...x, item: e.target.value } : x)))} />
            <small>{b.supplier_link_id ? PRICE_LABELS.quoted : PRICE_LABELS[b.price_kind || "estimate"]}{b.price_date ? ` · ${fmtDate(b.price_date)}` : ""} {b.source_url?.startsWith("https://") ? <a href={b.source_url} target="_blank" rel="noreferrer">Fonte</a> : null}</small></td>
          <td><select value={b.category} aria-label="Categoria" onChange={(e) => setBudget(budget.map((x, k) => (k === n ? { ...x, category: e.target.value as BudgetCategory } : x)))}>
            {(Object.keys(BUDGET_LABELS) as BudgetCategory[]).map((c) => <option key={c} value={c}>{BUDGET_LABELS[c]}</option>)}</select></td>
          <td className="is-num"><input type="number" min={0} step="0.01" value={b.value} readOnly={Boolean(b.source_url)} aria-label="Valor" onChange={(e) => setBudget(budget.map((x, k) => (k === n ? { ...x, value: Number(e.target.value) } : x)))} /></td>
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
