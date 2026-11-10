import { useCallback, useEffect, useState, type FormEvent } from "react";
import BrandContextPanel from "../components/studio/BrandContextPanel";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  CRITICALITY_LABEL, KIND_LABEL, RADAR_FIELDS, SENTIMENT_LABEL, clippingToCalendar, exportClipping, suggestClippingSettings, getClipping, getClippingInsights,
  getClippingReport, refreshClipping, saveClippingSettings, setClippingStatus,
  type Clipping as Item, type ClippingInsights, type ClippingReport, type ClippingView, type Count, type Sentiment,
} from "../app/contentOps";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import Drawer from "../components/Drawer";
import BrandHealth from "../components/clipping/BrandHealth";
import BrandHealthAlerts from "../components/clipping/BrandHealthAlerts";
import "../styles/studio.css";

type Kind = "" | "marca" | "concorrente" | "pessoa" | "tema";
type RadarDraft = Record<string, string>;
type ClipTab = "saude" | "alertas" | "materias";
const CLIP_TABS: [ClipTab, string][] = [["saude", "Saúde da marca"], ["alertas", "Alertas"], ["materias", "Matérias"]];

function Bars({ title, rows, label }: { title: string; rows: Count[]; label?: (key: string) => string }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return <div className="clipBars"><h3>{title}</h3>{rows.length ? <ul>{rows.slice(0, 6).map((r) => <li key={r.key}>
    <span>{label ? label(r.key) : r.key}</span><i style={{ width: `${(r.count / max) * 100}%` }} aria-hidden="true" /><b>{r.count}</b>
  </li>)}</ul> : <p className="libHint">Sem dados no período.</p>}</div>;
}
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }) : "");
const toList = (text: string) => text.split(/[\n,]/).map((t) => t.trim()).filter(Boolean).slice(0, 6);

/** Clipping da marca e dos concorrentes (Google Notícias), com a leitura da IA. O cliente só lê; a equipe Mugô configura e trata. */
export default function Clipping({ canManage = false, initialTab = "saude" }: { canManage?: boolean; initialTab?: ClipTab }) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "empresa";
  const [tab, setTab] = useState<ClipTab>(initialTab);
  const [view, setView] = useState<ClippingView | null>(null);
  const [kind, setKind] = useState<Kind>("");
  const [sentiment, setSentiment] = useState<"" | Sentiment>("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<RadarDraft | null>(null);
  const [search, setSearch] = useState("");
  const [minRelevance, setMinRelevance] = useState("");
  const [insights, setInsights] = useState<ClippingInsights | null>(null);
  const [report, setReport] = useState<ClippingReport | null>(null);
  const [reportOpts, setReportOpts] = useState<{ period: "diario" | "semanal" | "mensal"; focus: "cobertura" | "concorrentes" | "setor" | "riscos" }>({ period: "semanal", focus: "cobertura" });

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [data, stats] = await Promise.all([getClipping({ kind, sentiment, q: search.trim(), min_relevance: minRelevance }), getClippingInsights(30).catch(() => null)]);
      if (getActiveClientId() !== clientId) return;
      setView(data); setInsights(stats);
    } catch (cause) { setError(message(cause, "Não foi possível carregar o clipping.")); }
    finally { setLoading(false); }
  }, [kind, sentiment, search, minRelevance, clientId]);
  useEffect(() => { void load(); }, [load]);

  async function run<T>(key: string, fn: () => Promise<T>, fallback: string): Promise<T | null> {
    setBusy(key); setError(null); setNotice(null);
    try { return await fn(); } catch (cause) { setError(message(cause, fallback)); return null; } finally { setBusy(null); }
  }

  async function refresh() {
    const r = await run("refresh", refreshClipping, "Não foi possível buscar notícias agora.");
    if (r) { setNotice(r.new ? `${r.new} notícia(s) nova(s).` : "Nenhuma notícia nova desde a última busca."); await load(); }
  }

  async function saveSettings(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    const lists = Object.fromEntries(RADAR_FIELDS.map(([key]) => [key, toList(editing[key] || "")]));
    const ok = await run("settings", () => saveClippingSettings({
      ...(lists as Record<(typeof RADAR_FIELDS)[number][0], string[]>), active: true,
      feeds: (editing.feeds || "").split(/[\n,]/).map((t) => t.trim()).filter(Boolean).slice(0, 10),
      region: editing.region?.trim() || null, relevance_criteria: editing.criteria?.trim() || null,
      min_relevance: Math.max(0, Math.min(100, Number(editing.min_relevance) || 40)),
    }), "Não foi possível salvar o radar.");
    if (ok) { setEditing(null); await load(); }
  }

  async function mark(item: Item, status: "lido" | "arquivado") {
    const ok = await run(`s:${item.id}`, () => setClippingStatus(item.id, status), "Não foi possível atualizar.");
    if (ok) setView((v) => v && { ...v, items: status === "arquivado" ? v.items.filter((i) => i.id !== item.id) : v.items.map((i) => (i.id === item.id ? { ...i, status } : i)) });
  }

  async function toCalendar(item: Item) {
    const r = await run(`c:${item.id}`, () => clippingToCalendar(item.id), "Não foi possível criar a pauta.");
    if (r) { setNotice(r.already ? "Essa notícia já tinha virado pauta." : "Pauta criada como rascunho no Calendário."); setView((v) => v && { ...v, items: v.items.map((i) => (i.id === item.id ? { ...i, status: "pauta", calendar_item_id: r.calendar_item_id } : i)) }); }
  }

  const settings = view?.settings;
  const week = view?.week;
  const openSettings = () => setEditing({
    ...Object.fromEntries(RADAR_FIELDS.map(([key]) => [key, ((settings?.[key] as string[] | undefined) || []).join(", ")])),
    feeds: (settings?.feeds || []).join("\n"), region: settings?.region || "", criteria: settings?.relevance_criteria || "",
    min_relevance: String(settings?.min_relevance ?? 40),
  });
  async function fillRadar() {
    const r = await run("radar", () => suggestClippingSettings(), "Não foi possível sugerir os termos agora.");
    if (!r) return;
    setEditing((current) => {
      if (!current) return current;
      const next = { ...current };
      for (const [key] of RADAR_FIELDS) if (!(next[key] || "").trim() && r[key]?.length) next[key] = r[key].join(", ");
      if (!(next.region || "").trim() && r.region) next.region = r.region;
      if (!(next.criteria || "").trim() && r.relevance_criteria) next.criteria = r.relevance_criteria;
      return next;
    });
    setNotice("A IA preencheu os campos vazios do radar. Revise e clique em Salvar.");
  }
  async function download() {
    const blob = await run("export", () => exportClipping(30), "Não foi possível exportar.");
    if (!blob) return;
    const url = URL.createObjectURL(blob); const a = document.createElement("a");
    a.href = url; a.download = `clipping-${clientName}-30d.csv`; a.click(); URL.revokeObjectURL(url);
  }

  return <Shell title="Clipping" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={clientName} title="Clipping da marca" controls={canManage ? <div className="studioControls">
      <button type="button" className="ds-button" onClick={openSettings}>Radar</button>
      <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void download()}>Exportar CSV</button>
      <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || !settings?.saved} onClick={() => void refresh()}>{busy === "refresh" ? "Buscando…" : "Atualizar agora"}</button>
    </div> : undefined} />
    <nav className="clipTabs" aria-label="Clipping">
      {CLIP_TABS.filter(([key]) => canManage || key !== "alertas").map(([key, label]) => <button key={key} type="button" aria-pressed={tab === key} className={tab === key ? "is-on" : ""} onClick={() => setTab(key)}>{label}</button>)}
    </nav>
    {tab === "saude" ? <BrandHealth canManage={canManage} onOpenAlerts={() => setTab("alertas")} /> : null}
    {tab === "alertas" && canManage ? <BrandHealthAlerts /> : null}
    {tab === "materias" ? <>
    {canManage ? <BrandContextPanel clientId={clientId} /> : null}
    <p className="libHint">Notícias do Google Notícias sobre a marca e os concorrentes, buscadas todo dia às 7h40. A IA lê só a manchete e a fonte.{canManage ? " O cliente vê só as notícias relevantes, sem os termos nem as ações." : ""}{settings?.last_run_at ? ` Última busca: ${new Date(settings.last_run_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}.` : ""}</p>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {notice ? <p className="studioOk">{notice}</p> : null}

    {view && !settings?.saved ? <div className="studioEmpty">
      {canManage ? <><p>Configure os termos para começar: o nome da marca, produtos e os concorrentes.</p>
        <button type="button" className="ds-button is-primary" onClick={openSettings}>Configurar termos</button></>
        : <p>O clipping da sua marca ainda não foi ativado pela Mugô.</p>}
    </div> : null}

    {week && settings?.saved ? <section className="clipWeek" aria-label="Resumo da semana">
      <div><b>{week.current.marca}</b><span>menções da marca em 7 dias</span><small className={week.marca_variacao > 0 ? "is-up" : week.marca_variacao < 0 ? "is-down" : ""}>{week.marca_variacao > 0 ? `+${week.marca_variacao}` : week.marca_variacao} vs. semana anterior</small></div>
      <div><b className="is-positivo">{week.current.positivo}</b><span>positivas</span></div>
      <div><b>{week.current.neutro}</b><span>neutras</span></div>
      <div><b className="is-negativo">{week.current.negativo}</b><span>negativas</span></div>
      <div><b>{week.current.concorrente}</b><span>dos concorrentes</span></div>
    </section> : null}

    {insights && insights.total ? <section className="clipInsights" aria-label="Painel do período">
      {insights.critical.length ? <div className="clipCritical" role="alert"><b>{insights.critical.length} matéria(s) crítica(s){canManage ? " aguardando revisão" : ""}</b>
        <ul>{insights.critical.map((c) => <li key={c.id}><a href={c.url} target="_blank" rel="noreferrer noopener">{c.title}</a> · {c.source || "fonte"}{c.criticality ? ` · ${CRITICALITY_LABEL[c.criticality]}` : ""}</li>)}</ul></div> : null}
      <div className="clipInsightsGrid">
        <Bars title="Sentimento" rows={insights.sentiment} label={(k) => SENTIMENT_LABEL[k as Sentiment] || k} />
        <Bars title="Marca x concorrentes" rows={insights.mentions} label={(k) => { const [kindKey, term] = k.split(":"); return `${term} (${KIND_LABEL[kindKey] || kindKey})`; }} />
        <Bars title="Assuntos" rows={insights.themes} />
        <Bars title="Veículos com mais matérias" rows={insights.sources} />
      </div>
      <div className="clipTimeline" aria-label="Matérias por dia (30 dias)">{insights.timeline.map((d) => {
        const max = Math.max(1, ...insights.timeline.map((t) => t.count));
        return <i key={d.day} title={`${d.day.split("-").reverse().join("/")}: ${d.count}`} style={{ height: `${Math.max(4, (d.count / max) * 48)}px` }} />;
      })}</div>
      <p className="libHint">{insights.total} matéria(s) em 30 dias · {insights.analyzed} com análise da IA.</p>
    </section> : null}

    {canManage && settings?.saved ? <section className="clipReport" aria-label="Relatório de clipping">
      <div className="studioControls">
        <select value={reportOpts.period} aria-label="Período" onChange={(e) => setReportOpts({ ...reportOpts, period: e.target.value as typeof reportOpts.period })}>
          <option value="diario">Resumo diário</option><option value="semanal">Clipping semanal</option><option value="mensal">Clipping mensal</option></select>
        <select value={reportOpts.focus} aria-label="Foco" onChange={(e) => setReportOpts({ ...reportOpts, focus: e.target.value as typeof reportOpts.focus })}>
          <option value="cobertura">Cobertura da marca</option><option value="concorrentes">Concorrentes</option><option value="setor">Setor</option><option value="riscos">Riscos e oportunidades</option></select>
        <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={async () => { const r = await run("report", () => getClippingReport(reportOpts.period, reportOpts.focus), "Não foi possível gerar o relatório."); if (r) setReport(r); }}>
          {busy === "report" ? "Gerando…" : "Gerar relatório"}</button>
      </div>
      {report ? <div className="clipReportBody"><p>{report.summary}</p>
        {([["Destaques", report.highlights], ["Riscos", report.risks], ["Oportunidades", report.opportunities]] as const).map(([title, list]) => list.length ? <div key={title}>
          <h3>{title}</h3><ul>{list.map((r, i) => <li key={i}>{r.text} <a href={r.url} target="_blank" rel="noreferrer noopener">fonte ↗</a></li>)}</ul></div> : null)}
        <small className="libHint">Somente matérias coletadas e verificadas ({report.items}). {report.ai === false ? "Sem IA: lista das mais relevantes." : ""}</small>
      </div> : null}
    </section> : null}

    {settings?.saved ? <div className="studioFilters">
      <div className="studioTabs" role="tablist" aria-label="Origem">
        {([["", "Todas"], ["marca", "Marca"], ["concorrente", "Concorrentes"], ["pessoa", "Pessoas"], ["tema", "Temas"]] as [Kind, string][]).map(([k, l]) => <button key={k || "all"} role="tab" aria-selected={kind === k} className={kind === k ? "is-active" : ""} onClick={() => setKind(k)}>{l}</button>)}
      </div>
      <div className="studioTabs" role="tablist" aria-label="Sentimento">
        {([["", "Qualquer"], ["positivo", "Positivas"], ["neutro", "Neutras"], ["negativo", "Negativas"], ["misto", "Mistas"]] as ["" | Sentiment, string][]).map(([k, l]) => <button key={k || "any"} role="tab" aria-selected={sentiment === k} className={sentiment === k ? "is-active" : ""} onClick={() => setSentiment(k)}>{l}</button>)}
      </div>
      <input type="search" value={search} placeholder="Buscar título, resumo ou veículo" aria-label="Buscar notícias" onChange={(e) => setSearch(e.target.value)} />
      <select value={minRelevance} aria-label="Relevância mínima" onChange={(e) => setMinRelevance(e.target.value)}>
        <option value="">Qualquer relevância</option><option value="40">Relevância 40+</option><option value="60">60+</option><option value="80">80+</option></select>
    </div> : null}

    {loading && !view ? <p>Carregando…</p> : null}
    {view && settings?.saved && !view.items.length ? <div className="studioEmpty"><p>Nenhuma notícia com esse filtro ainda.{canManage ? <> Clique em <b>Atualizar agora</b> para buscar.</> : null}</p></div> : null}

    <ul className="clipList">{(view?.items || []).map((item) => <li key={item.id} className={`clipItem is-${item.sentiment || "sem"}${item.relevant === false ? " is-irrelevant" : ""}${item.status === "lido" ? " is-read" : ""}`}>
      <div className="clipMeta">
        <span className="studioChip">{KIND_LABEL[item.kind] || item.kind} · {item.term}</span>
        {item.relevance != null ? <span className="studioChip">Relevância {item.relevance}</span> : null}
        {item.criticality && item.criticality !== "baixa" ? <span className={`studioChip clipCrit is-${item.criticality}`}>{CRITICALITY_LABEL[item.criticality]}</span> : null}
        {item.main_theme ? <span className="studioChip">{item.main_theme}</span> : null}
        {item.sentiment ? <span className={`studioChip clipSentiment is-${item.sentiment}`}>{SENTIMENT_LABEL[item.sentiment]}</span> : <span className="studioChip">Sem leitura da IA</span>}
        <small>{item.source || "Fonte"} · {when(item.published_at || item.created_at)}</small>
      </div>
      <a className="clipTitle" href={item.url} target="_blank" rel="noreferrer noopener">{item.title} ↗</a>
      {item.summary ? <p>{item.summary}</p> : null}
      {item.opportunities?.length || item.risks?.length || item.justification ? <details className="clipAnalysis"><summary>Análise</summary>
        {item.opportunities?.length ? <p><b>Oportunidades:</b> {item.opportunities.join(" · ")}</p> : null}
        {item.risks?.length ? <p><b>Riscos:</b> {item.risks.join(" · ")}</p> : null}
        {item.entities?.length ? <p><b>Entidades:</b> {item.entities.join(", ")}</p> : null}
        {item.justification ? <p><b>Por quê:</b> {item.justification}</p> : null}
        {item.evidence?.length ? <p><b>Evidências:</b> {item.evidence.map((e) => `"${e}"`).join(" · ")}</p> : null}
      </details> : null}
      {item.relevant === false ? <p className="clipWarn">A IA acha que não é sobre a marca (homônimo ou citação de passagem).</p> : null}
      {canManage ? <div className="studioActions">
        {item.status === "pauta" ? <span className="studioOk">Virou pauta no Calendário</span>
          : <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void toCalendar(item)}>{busy === `c:${item.id}` ? "Criando…" : "Virar pauta"}</button>}
        {item.status === "novo" ? <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => void mark(item, "lido")}>Marcar como lida</button> : null}
        <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => void mark(item, "arquivado")}>Arquivar</button>
      </div> : null}
    </li>)}</ul>

    </> : null}

    <Drawer open={Boolean(editing)} title="Radar de notícias" description="Até 6 termos por campo, separados por vírgula. Use o nome exato (ex.: Curavino, vinho natural Curavino)." onClose={() => { if (!busy) setEditing(null); }}>
      {editing ? <form className="studioForm" onSubmit={saveSettings}>
        <div className="studioActions"><button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void fillRadar()}>{busy === "radar" ? "Lendo os dados da marca…" : "✦ Preencher com IA"}</button>
          <small>Preenche só os campos vazios com o nome, o contexto de negócio, o perfil e os posts da marca. Revise antes de salvar.</small></div>
        {error ? <p className="studioError" role="alert">{error}</p> : notice ? <p role="status">{notice}</p> : null}
        {RADAR_FIELDS.map(([key, label]) => <label key={key}>{label}<textarea rows={2} required={key === "brand_terms"} value={editing[key] || ""} onChange={(e) => setEditing({ ...editing, [key]: e.target.value })} /></label>)}
        <label>Fontes próprias (RSS/Atom, uma por linha, https)<textarea rows={3} value={editing.feeds || ""} onChange={(e) => setEditing({ ...editing, feeds: e.target.value })} placeholder="https://www.revistaadega.com.br/feed/" /></label>
        <label>Região de interesse<input value={editing.region || ""} onChange={(e) => setEditing({ ...editing, region: e.target.value })} placeholder="São Paulo, Brasil" /></label>
        <label>Critérios de relevância<textarea rows={3} value={editing.criteria || ""} onChange={(e) => setEditing({ ...editing, criteria: e.target.value })} placeholder="Importa: lançamentos, preço, varejo de vinhos. Não importa: receitas." /></label>
        <label>Relevância mínima para contar (0 a 100)<input type="number" min={0} max={100} value={editing.min_relevance || "40"} onChange={(e) => setEditing({ ...editing, min_relevance: e.target.value })} /></label>
        <div className="studioActions"><button type="button" className="ds-button" onClick={() => setEditing(null)}>Cancelar</button>
          <button className="ds-button is-primary" disabled={Boolean(busy)}>{busy === "settings" ? "Salvando…" : "Salvar"}</button></div>
      </form> : null}
    </Drawer>
  </div></Shell>;
}
