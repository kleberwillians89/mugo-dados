import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowUpRight, Lightbulb, RefreshCw, TrendingUp, Users } from "lucide-react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { getClipping, getClippingInsights, type Clipping, type ClippingInsights, type ClippingView } from "../app/contentOps";
import PageHeader from "../components/data/PageHeader";
import { getRadarOverview, type RadarOverview } from "../app/radar";
import Shell from "../components/Shell";
import NewsCard from "../components/clipping/NewsCard";
import "../styles/metaLive.css";

function safeLink(value: string | null | undefined): string | null {
  try {
    const url = new URL(String(value || ""));
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch { return null; }
}

const short = (n: number | null) => n == null ? "—" : n >= 1_000_000 ? `${(n / 1_000_000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mi`
  : n >= 1000 ? `${(n / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mil` : n.toLocaleString("pt-BR");

/**
 * Radar Cultural: o que está acontecendo ao redor da marca, em leitura rápida.
 * 1) frase de resumo; 2) o que está em alta e conversa com a marca (com ideia de pauta);
 * 3) oportunidades e temas (só quando existem); 4) criadores ligados; 5) notícias em cards.
 * Usa só o Clipping desta empresa e as tendências selecionadas para ela; nada é inventado quando falta dado.
 */
export default function Radar({ embedded = false }: { embedded?: boolean } = {}) {
  const clientId = getActiveClientId();
  const company = getActiveClientName() || "Empresa";
  const [view, setView] = useState<ClippingView | null>(null);
  const [overview, setOverview] = useState<RadarOverview | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [insights, setInsights] = useState<ClippingInsights | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<"todos" | "marca" | "concorrente" | "tema">("todos");

  const load = useCallback(async () => {
    setBusy(true); setError(null);
    try {
      const [nextView, nextInsights] = await Promise.all([getClipping(), getClippingInsights(30)]);
      if (getActiveClientId() !== clientId) return;
      setView(nextView); setInsights(nextInsights);
    } catch (cause) {
      if (getActiveClientId() === clientId) setError(cause instanceof Error ? cause.message : "Não foi possível carregar os sinais.");
    } finally {
      if (getActiveClientId() === clientId) setBusy(false);
    }
  }, [clientId]);
  useEffect(() => { void load(); }, [load]);

  const loadOverview = useCallback(async () => {
    try {
      const result = await getRadarOverview();
      if (getActiveClientId() === clientId) { setOverview(result); setOverviewError(null); }
    } catch (cause) {
      if (getActiveClientId() === clientId) setOverviewError(cause instanceof Error ? cause.message : "Fonte externa indisponível.");
    }
  }, [clientId]);
  useEffect(() => { void loadOverview(); }, [loadOverview]);

  const signals = useMemo(() => (view?.items || []).filter((item: Clipping) => item.relevant !== false), [view]);
  const items = useMemo(() => signals.filter((item) => kind === "todos" || item.kind === kind)
    .sort((a, b) => (b.published_at || b.created_at || "").localeCompare(a.published_at || a.created_at || "")).slice(0, 12), [signals, kind]);
  const topics = (insights?.themes || []).filter((t) => t.key && t.count > 0).slice(0, 10);
  const opportunities = signals.filter((item) => (item.opportunities || []).length > 0).slice(0, 4);
  const trends = overview?.trends.items || [];
  const creators = overview?.creators || [];
  const counts = { marca: signals.filter((i) => i.kind === "marca").length, concorrente: signals.filter((i) => i.kind === "concorrente").length,
    tema: signals.filter((i) => i.kind === "tema").length };

  const headline = (() => {
    if (busy && !view) return "Lendo o que está acontecendo ao redor da marca…";
    const parts = [`${signals.length} notícia${signals.length === 1 ? "" : "s"} relevante${signals.length === 1 ? "" : "s"} em 30 dias`];
    if (counts.marca) parts.push(`${counts.marca} sobre ${company}`);
    if (counts.concorrente) parts.push(`${counts.concorrente} sobre concorrentes`);
    if (trends.length) parts.push(`${trends.length} assunto${trends.length === 1 ? "" : "s"} em alta ligado${trends.length === 1 ? "" : "s"} à marca`);
    return parts.join(" · ") + ".";
  })();

  const refresh = <button type="button" className="ds-button is-primary" disabled={busy} onClick={() => { void load(); void loadOverview(); }}>
    <RefreshCw size={15} aria-hidden="true" /> {busy ? "Atualizando…" : "Atualizar leitura"}
  </button>;

  const body = <div className="radarPage">
    <div className="radarTop">
      <p className="clipHeadline" role="status">{headline}</p>
      {embedded ? refresh : null}
    </div>
    {error ? <p className="studioError" role="alert">{error}</p> : null}

    <div className="mlKpis" aria-label="Resumo do radar">
      <div className="mlCard mlKpi"><span className="mlLbl">Sobre {company}</span><b>{counts.marca}</b><small>notícias em 30 dias</small></div>
      <div className="mlCard mlKpi"><span className="mlLbl">Concorrentes</span><b>{counts.concorrente}</b><small>notícias em 30 dias</small></div>
      <div className="mlCard mlKpi"><span className="mlLbl">Em alta e ligado à marca</span><b>{overview ? trends.length : "—"}</b><small>assuntos hoje</small></div>
      <div className="mlCard mlKpi"><span className="mlLbl">Oportunidades</span><b>{opportunities.length}</b><small>com fonte</small></div>
    </div>

    <section className="mlBlock" aria-labelledby="radar-trends">
      <div className="mlRow mlSpread"><h3 id="radar-trends"><TrendingUp size={17} aria-hidden="true" /> Em alta no Brasil e ligado a {company}</h3>
        {overview?.trends.public_count ? <small className="mlMuted">de {overview.trends.public_count} assuntos em alta no Google hoje</small> : null}</div>
      {overviewError ? <p className="mlMuted">Tendências indisponíveis agora ({overviewError}).</p> : null}
      {trends.length ? <div className="radarTrends">{trends.slice(0, 6).map((t) => <article key={t.id} className="mlCard radarTrend">
        <div className="mlRow mlSpread"><b>{t.topic}</b>{t.approx_traffic ? <span className="mlChip is-neu">{t.approx_traffic} buscas</span> : null}</div>
        {t.why ? <p>{t.why}</p> : null}
        {t.idea ? <p className="radarIdea"><Lightbulb size={14} aria-hidden="true" /> {t.idea}</p> : null}
        {safeLink(t.source_url) ? <a className="radarLink" href={safeLink(t.source_url)!} target="_blank" rel="noopener noreferrer">Ver no Google <ArrowUpRight size={13} aria-hidden="true" /></a> : null}
      </article>)}</div>
        : <p className="mlMuted">{overview ? `Nenhum assunto em alta hoje conversa com ${company}. Volta amanhã: a lista muda todo dia.` : "Lendo os assuntos em alta…"}</p>}
    </section>

    {opportunities.length || topics.length ? <section className="mlBlock" aria-labelledby="radar-opps">
      <h3 id="radar-opps"><Lightbulb size={17} aria-hidden="true" /> Oportunidades e temas</h3>
      {opportunities.length ? <div className="radarTrends">{opportunities.map((item) => <article key={item.id} className="mlCard radarTrend">
        <b>{(item.opportunities || [])[0]}</b>
        {(item.opportunities || []).slice(1, 3).map((o, i) => <p key={i}>{o}</p>)}
        <a className="radarLink" href={item.url} target="_blank" rel="noreferrer noopener">{item.source || "Fonte"}: {item.title.slice(0, 70)}{item.title.length > 70 ? "…" : ""} <ArrowUpRight size={13} aria-hidden="true" /></a>
      </article>)}</div> : null}
      {topics.length ? <div className="mlChips radarTopics">{topics.map((t) => <span key={t.key} className="mlChip is-neu">{t.key} · {t.count}</span>)}</div> : null}
    </section> : null}

    {creators.length ? <section className="mlBlock" aria-labelledby="radar-creators">
      <div className="mlRow mlSpread"><h3 id="radar-creators"><Users size={17} aria-hidden="true" /> Criadores ligados à marca</h3><small className="mlMuted">{creators.length} perfis</small></div>
      <div className="radarCreators">{creators.slice(0, 12).map((c) => {
        const link = safeLink(c.profile_url);
        const inner = <>
          {c.avatar_url ? <img src={c.avatar_url} alt="" loading="lazy" referrerPolicy="no-referrer" /> : <span className="radarAvatar">{(c.display_name || c.handle).slice(0, 1).toUpperCase()}</span>}
          <span className="radarCreatorText"><b>{c.display_name || c.handle}</b><small>@{c.handle}</small>
            <small>{short(c.followers)} seguidores{c.engagement_rate != null ? ` · ${c.engagement_rate.toLocaleString("pt-BR")}% engaj.` : ""}</small></span>
        </>;
        return link ? <a key={c.id} className="mlCard radarCreator" href={link} target="_blank" rel="noopener noreferrer">{inner}</a>
          : <div key={c.id} className="mlCard radarCreator">{inner}</div>;
      })}</div>
    </section> : null}

    <section className="mlBlock" aria-labelledby="radar-news">
      <div className="mlRow mlSpread"><h3 id="radar-news">Notícias que alimentam o radar</h3>
        <div className="mlChips" role="group" aria-label="Filtrar notícias">
          {(["todos", "marca", "concorrente", "tema"] as const).map((value) => <button key={value} type="button" aria-pressed={kind === value}
            className={`radarFilter${kind === value ? " is-active" : ""}`} onClick={() => setKind(value)}>
            {{ todos: "Todas", marca: company, concorrente: "Concorrentes", tema: "Temas" }[value]}</button>)}
        </div></div>
      {items.length ? <div className="newsGrid">{items.map((item) => <NewsCard key={item.id} item={item} />)}</div>
        : <p className="mlMuted">{busy ? "Carregando notícias…" : "Sem notícias para este filtro."}</p>}
    </section>

    <p className="mlMuted radarFoot">O radar de {company} usa só o Clipping desta empresa e os assuntos em alta escolhidos para ela. Fatia de atenção nas redes (share of attention) ainda não é calculada: só entra com marcas comparáveis e amostra auditável.</p>
  </div>;

  if (embedded) return body;
  return <Shell title="" variant="editorial">
    <PageHeader company={company} title="Radar Cultural" dateline={<span>Clipping da marca · tendências do dia · 30 dias</span>} controls={refresh} />
    {body}
  </Shell>;
}
