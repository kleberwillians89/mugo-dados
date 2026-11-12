import { useCallback, useEffect, useMemo, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { getPathForRoute } from "../app/routes";
import { BUDGET_LABELS, PROJECT_COLUMNS, brl, chatProject, createProject, deleteProject, generateProject, listProjects, projectToBrief,
  updateProject, type BudgetCategory, type ProductionPlan, type Project, type ProjectInputs, type ProjectKind, type ProjectStatus } from "../app/projects";
import Shell from "../components/Shell";
import EventRadar from "../components/projects/EventRadar";
import { EventSuppliers, SupplierBook } from "../components/projects/Suppliers";
import PageHeader from "../components/data/PageHeader";
import { CalendarClock, CopyPlus, DollarSign, Download, Eye, Handshake, ListChecks, Plus, Printer, Save, Send, ShieldAlert, Trash2, Users, type LucideIcon } from "lucide-react";
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
  const [pageTab, setPageTab] = useState<"producoes" | "fornecedores">("producoes");

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

  return <Shell title={copy.title} variant="editorial"><div className="ds-page studioPage projPage">
    <PageHeader company={getActiveClientName() || "empresa"} title={copy.title}
      controls={<button type="button" className="ds-button is-primary" onClick={() => { setCreating(true); setOpenId(null); }}>{copy.newLabel}</button>} />
    <p className="libIntro">{copy.lead}</p>
    {kind === "evento" ? <div className="studioTabs projPageTabs" role="tablist" aria-label="Evento">
      {([["producoes", "Produções"], ["fornecedores", "Fornecedores"]] as const).map(([key, label]) => <button key={key} type="button" role="tab"
        aria-selected={pageTab === key} className={pageTab === key ? "is-active" : ""} onClick={() => setPageTab(key)}>{label}</button>)}
    </div> : null}
    {error ? <div className="ds-notice is-negative" role="alert"><p className="ds-noticeTitle">{error}</p></div> : null}
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

    {current ? <ProjectDetail key={current.id} kind={kind} project={current} projects={projects} formats={formats} busy={busy} run={run} onChange={replace}
      onOpen={(id) => { setOpenId(id); setCreating(false); }} onCreated={(p) => { replace(p); setOpenId(p.id); }}
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

function ProjectDetail({ kind, project, projects, formats, busy, run, onChange, onOpen, onCreated, onDeleted, onClose }: { kind: ProjectKind; project: Project;
  projects: Project[]; formats: string[]; busy: string | null; run: Run; onChange: (p: Project) => void; onOpen: (id: string) => void; onCreated: (p: Project) => void;
  onDeleted: () => void; onClose: () => void }) {
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
        {hasPlan && kind === "planejamento" ? <button type="button" className="ds-button" onClick={() => window.print()}>Imprimir</button> : null}
        <button type="button" className="ds-button" onClick={onClose}>Fechar</button>
      </div>
    </header>
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
          : kind === "planejamento" ? <StrategyView project={project} /> : <ProductionView project={project} projects={projects} busy={busy} run={run} onChange={onChange} onOpen={onOpen} onCreated={onCreated} />}
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

type Tab = "cronograma" | "equipe" | "fornecedores" | "orcamento" | "riscos" | "checklist";
const TABS: { key: Tab; label: string; icon: LucideIcon }[] = [
  { key: "cronograma", label: "Cronograma", icon: CalendarClock }, { key: "equipe", label: "Equipe", icon: Users },
  { key: "fornecedores", label: "Fornecedores", icon: Handshake }, { key: "orcamento", label: "Orçamento", icon: DollarSign },
  { key: "riscos", label: "Riscos", icon: ShieldAlert }, { key: "checklist", label: "Checklist", icon: ListChecks },
];
const IMPACT: Record<string, string> = { baixo: "Baixo", medio: "Médio", alto: "Alto" };
type Draft = {
  timeline: NonNullable<ProductionPlan["timeline"]>; staff: NonNullable<ProductionPlan["staff"]>; budget: NonNullable<ProductionPlan["budget"]>;
  risks: NonNullable<ProductionPlan["risks"]>; checklist: string[];
};
const toDraft = (p: Project["plan"]): Draft => ({
  timeline: p.timeline || [], staff: p.staff || [], budget: p.budget || [],
  risks: ((p.risks || []) as ProductionPlan["risks"] & object).filter((r) => r && typeof r === "object"), checklist: p.checklist || [],
});
const sumBudget = (b: Draft["budget"]) => b.reduce((s, x) => s + (Number(x.value) || 0), 0);
const fmtTime = (iso?: string) => { const d = iso ? new Date(iso) : null; return d && !Number.isNaN(d.getTime()) ? d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : ""; };

/** Excel abre CSV com ; e BOM direto, com acento. */
function exportPlanCsv(project: Project, d: Draft) {
  const cell = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const rows: unknown[][] = [[project.title], [project.format || "", project.target_date || ""], [],
    ["CRONOGRAMA"], ["Data", "Fase", "Tarefa"], ...d.timeline.map((t) => [t.date, t.phase, t.task]), [],
    ["EQUIPE"], ["Função", "Qtd.", "Observação"], ...d.staff.map((s) => [s.role, s.qty, s.note]), [],
    ["ORÇAMENTO"], ["Item", "Categoria", "Valor (R$)"], ...d.budget.map((b) => [b.item, BUDGET_LABELS[b.category] || b.category, b.value]), ["Total", "", sumBudget(d.budget)], [],
    ["RISCOS"], ["Risco", "Impacto", "Como evitar"], ...d.risks.map((r) => [r.risk, IMPACT[r.impact] || r.impact, r.mitigation]), [],
    ["CHECKLIST"], ...d.checklist.map((c) => [c])];
  const blob = new Blob(["﻿" + rows.map((r) => r.map(cell).join(";")).join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = `${project.title.replace(/[^\p{L}\p{N} _-]/gu, "").trim() || "producao"}.csv`;
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}

function ProductionView({ project, projects, busy, run, onChange, onOpen, onCreated }: { project: Project; projects: Project[]; busy: string | null; run: Run;
  onChange: (p: Project) => void; onOpen: (id: string) => void; onCreated: (p: Project) => void }) {
  const p = project.plan;
  const [tab, setTab] = useState<Tab>("cronograma");
  const [draft, setDraft] = useState<Draft>(() => toDraft(p));
  const [pick, setPick] = useState(project.id);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  // Plano novo (IA refez, fornecedores lançaram no orçamento): o rascunho acompanha.
  const [syncedPlan, setSyncedPlan] = useState(project.plan);
  if (syncedPlan !== project.plan) { setSyncedPlan(project.plan); setDraft(toDraft(project.plan)); }
  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(p));
  const total = sumBudget(draft.budget);
  const byCat = (Object.keys(BUDGET_LABELS) as BudgetCategory[]).map((c) => ({ c, v: draft.budget.filter((b) => b.category === c).reduce((s, b) => s + (Number(b.value) || 0), 0) })).filter((x) => x.v > 0);
  const edit = <K extends keyof Draft>(key: K, n: number, patch: Partial<Draft[K][number]>) =>
    setDraft((d) => ({ ...d, [key]: (d[key] as Draft[K][number][]).map((x, k) => (k === n ? (typeof x === "object" ? { ...x, ...patch } : patch) : x)) }));
  const drop = (key: keyof Draft, n: number) => setDraft((d) => ({ ...d, [key]: (d[key] as unknown[]).filter((_, k) => k !== n) }));
  const add = () => setDraft((d) => {
    if (tab === "cronograma") return { ...d, timeline: [...d.timeline, { date: "", phase: d.timeline.at(-1)?.phase || "Pré-produção", task: "" }] };
    if (tab === "equipe") return { ...d, staff: [...d.staff, { role: "", qty: 1, note: "" }] };
    if (tab === "orcamento") return { ...d, budget: [...d.budget, { category: "outros", item: "Novo item", value: 0 }] };
    if (tab === "riscos") return { ...d, risks: [...d.risks, { risk: "", impact: "medio", mitigation: "" }] };
    if (tab === "checklist") return { ...d, checklist: [...d.checklist, ""] };
    return d;
  });
  const fullPlan = () => ({ ...p, ...draft, budget_total: sumBudget(draft.budget) });

  async function save() {
    const r = await run("save", () => updateProject("evento", project.id, { plan: fullPlan() }), "Não foi possível salvar o plano.");
    if (r) onChange(r.project);
  }
  async function saveAsNew() {
    const c = await run("saveNew", async () => {
      const created = await createProject("evento", { title: `${project.title} (cópia)`, format: project.format || undefined, target_date: project.target_date || undefined, inputs: project.inputs || {} });
      return updateProject("evento", created.project.id, { plan: fullPlan() });
    }, "Não foi possível salvar como novo.");
    if (c) onCreated(c.project);
  }
  async function sendToApproval() {
    const r = await run("approval", () => updateProject("evento", project.id, { plan: fullPlan(), status: "aprovacao_interna" }), "Não foi possível enviar para aprovação.");
    if (r) onChange(r.project);
  }
  const inApproval = project.status === "aprovacao_interna";
  const current = TABS.find((t) => t.key === tab)!;
  const SectionIcon = current.icon;

  return <div className="projProduction">
    <div className="prodToolbar" aria-label="Ações do plano">
      <div className="prodToolbarRow">
        <select className="prodPicker" value={pick} aria-label="Produções salvas" onChange={(e) => setPick(e.target.value)}>
          {projects.map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}</select>
        <button type="button" className="ds-button" disabled={pick === project.id} onClick={() => onOpen(pick)}><Eye size={16} aria-hidden="true" />Abrir</button>
        <span className={`prodSaveState${dirty ? " is-dirty" : ""}`} role="status">{dirty ? "Alterações não salvas" : `Salvo no banco${fmtTime(project.updated_at) ? ` · ${fmtTime(project.updated_at)}` : ""}`}</span>
      </div>
      <div className="prodToolbarRow">
        <button type="button" className="ds-button is-primary" disabled={busy !== null || !dirty} onClick={() => void save()}>
          <Save size={16} aria-hidden="true" />{busy === "save" ? "Salvando…" : "Salvar plano"}</button>
        <button type="button" className="ds-button" disabled={busy !== null} onClick={() => void saveAsNew()}>
          <CopyPlus size={16} aria-hidden="true" />{busy === "saveNew" ? "Salvando…" : "Salvar como novo"}</button>
        <button type="button" className="ds-button prodApprove" disabled={busy !== null || (inApproval && !dirty)} onClick={() => void sendToApproval()}>
          <Send size={16} aria-hidden="true" />{busy === "approval" ? "Enviando…" : inApproval ? "Em aprovação" : "Enviar para aprovação"}</button>
        <span className="prodToolbarSpacer" />
        <button type="button" className="ds-button" onClick={() => exportPlanCsv(project, draft)}><Download size={16} aria-hidden="true" />Excel</button>
        <button type="button" className="ds-button" onClick={() => window.print()}><Printer size={16} aria-hidden="true" />PDF</button>
      </div>
    </div>

    {p.summary ? <p className="briefLead">{p.summary}</p> : null}

    <div className="prodTabs" role="tablist" aria-label="Plano de produção">{TABS.map((t) => { const Icon = t.icon; return <button key={t.key} type="button" role="tab"
      aria-selected={tab === t.key} className={tab === t.key ? "is-active" : ""} onClick={() => setTab(t.key)}><Icon size={20} aria-hidden="true" /><span>{t.label}</span></button>; })}</div>

    <section className="prodSection" aria-label={current.label}>
      <header>
        <h3><SectionIcon size={22} aria-hidden="true" />{current.label}</h3>
        {tab !== "fornecedores" ? <button type="button" className="ds-button prodAdd" onClick={add}><Plus size={16} aria-hidden="true" />Adicionar</button> : null}
      </header>

      {tab === "cronograma" ? <ol className="prodRows">{draft.timeline.length ? draft.timeline.map((t, n) => <li key={n} className="prodRow">
        <input className="prodDate" value={t.date} placeholder="dd/mm" aria-label="Data" onChange={(e) => edit("timeline", n, { date: e.target.value })} />
        <div className="prodRowBody">
          <input className="prodPhase" value={t.phase} placeholder="FASE" aria-label="Fase" onChange={(e) => edit("timeline", n, { phase: e.target.value })} />
          <input className="prodText" value={t.task} placeholder="O que acontece" aria-label="Tarefa" onChange={(e) => edit("timeline", n, { task: e.target.value })} />
        </div>
        <RowTrash label={t.task || "etapa"} onClick={() => drop("timeline", n)} />
      </li>) : <li className="prodEmpty">Nenhuma etapa. Clique em Adicionar.</li>}</ol> : null}

      {tab === "equipe" ? <ol className="prodRows">{draft.staff.length ? draft.staff.map((s, n) => <li key={n} className="prodRow">
        <input className="prodDate" type="number" min={0} value={s.qty} aria-label="Quantidade" onChange={(e) => edit("staff", n, { qty: Number(e.target.value) })} />
        <div className="prodRowBody">
          <input className="prodPhase" value={s.role} placeholder="FUNÇÃO" aria-label="Função" onChange={(e) => edit("staff", n, { role: e.target.value })} />
          <input className="prodText" value={s.note} placeholder="Observação" aria-label="Observação" onChange={(e) => edit("staff", n, { note: e.target.value })} />
        </div>
        <RowTrash label={s.role || "função"} onClick={() => drop("staff", n)} />
      </li>) : <li className="prodEmpty">Ninguém na equipe ainda. Clique em Adicionar.</li>}</ol> : null}

      {tab === "fornecedores" ? <EventSuppliers project={project} busy={busy} run={run} onProjectChange={onChange} /> : null}

      {tab === "orcamento" ? <div className="projBudget">
        <div className="projBudgetTotal"><small>Total estimado</small><b>{brl(total)}</b>
          {byCat.length ? <span className="projBudgetBar" aria-label="Divisão por categoria">{byCat.map((x) => <i key={x.c} title={`${BUDGET_LABELS[x.c]}: ${brl(x.v)}`} style={{ flexGrow: x.v }} />)}</span> : null}
          <span className="projBudgetLegend">{byCat.map((x) => <small key={x.c}>{BUDGET_LABELS[x.c]} {brl(x.v)}</small>)}</span></div>
        <ol className="prodRows">{draft.budget.map((b, n) => <li key={n} className="prodRow">
          <input className="prodDate is-money" type="number" min={0} step={50} value={b.value} aria-label="Valor" onChange={(e) => edit("budget", n, { value: Number(e.target.value) })} />
          <div className="prodRowBody">
            <select className="prodPhase" value={b.category} aria-label="Categoria" onChange={(e) => edit("budget", n, { category: e.target.value as BudgetCategory })}>
              {(Object.keys(BUDGET_LABELS) as BudgetCategory[]).map((c) => <option key={c} value={c}>{BUDGET_LABELS[c]}</option>)}</select>
            <input className="prodText" value={b.item} aria-label="Item" onChange={(e) => edit("budget", n, { item: e.target.value })} />
          </div>
          <RowTrash label={b.item} onClick={() => drop("budget", n)} />
        </li>)}</ol>
      </div> : null}

      {tab === "riscos" ? <ol className="prodRows">{draft.risks.length ? draft.risks.map((r, n) => <li key={n} className="prodRow">
        <select className={`prodDate prodImpact is-${r.impact}`} value={r.impact} aria-label="Impacto" onChange={(e) => edit("risks", n, { impact: e.target.value as "baixo" | "medio" | "alto" })}>
          {Object.entries(IMPACT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <div className="prodRowBody">
          <input className="prodPhase" value={r.risk} placeholder="RISCO" aria-label="Risco" onChange={(e) => edit("risks", n, { risk: e.target.value })} />
          <input className="prodText" value={r.mitigation} placeholder="Como evitar" aria-label="Como evitar" onChange={(e) => edit("risks", n, { mitigation: e.target.value })} />
        </div>
        <RowTrash label={r.risk || "risco"} onClick={() => drop("risks", n)} />
      </li>) : <li className="prodEmpty">Nenhum risco mapeado. Clique em Adicionar.</li>}</ol> : null}

      {tab === "checklist" ? <ol className="prodRows">{draft.checklist.length ? draft.checklist.map((c, n) => <li key={n} className={`prodRow is-check${checked.has(n) ? " is-done" : ""}`}>
        <input type="checkbox" className="prodCheck" checked={checked.has(n)} aria-label={`Feito: ${c}`}
          onChange={() => setChecked((s) => { const next = new Set(s); if (next.has(n)) next.delete(n); else next.add(n); return next; })} />
        <div className="prodRowBody"><input className="prodText" value={c} placeholder="Item do checklist" aria-label="Item do checklist"
          onChange={(e) => setDraft((d) => ({ ...d, checklist: d.checklist.map((x, k) => (k === n ? e.target.value : x)) }))} /></div>
        <RowTrash label={c || "item"} onClick={() => drop("checklist", n)} />
      </li>) : <li className="prodEmpty">Checklist vazio. Clique em Adicionar.</li>}</ol> : null}
    </section>
  </div>;
}

function RowTrash({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" className="prodTrash" aria-label={`Tirar ${label}`} title="Tirar" onClick={onClick}><Trash2 size={18} aria-hidden="true" /></button>;
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
