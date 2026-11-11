import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowUpRight, BookOpen, RefreshCw, Radar as RadarIcon, TrendingUp } from "lucide-react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { getClipping, getClippingInsights, type Clipping, type ClippingInsights, type ClippingView } from "../app/contentOps";
import PageHeader from "../components/data/PageHeader";
import Shell from "../components/Shell";

function safeLink(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch { return null; }
}

const dateLabel = (value: string | null) => value
  ? new Date(value).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" })
  : "Data não informada";

/**
 * Radar Cultural v1: leitura de evidências já coletadas pelo Clipping por empresa.
 * Não infere crescimento real de tendências nem inventa métricas externas.
 * A API existente resolve o tenant autenticado e aplica suas permissões.
 */
export default function Radar() {
  const clientId = getActiveClientId();
  const company = getActiveClientName() || "Empresa";
  const [view, setView] = useState<ClippingView | null>(null);
  const [insights, setInsights] = useState<ClippingInsights | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<"todos" | "marca" | "concorrente" | "tema">("todos");

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const [nextView, nextInsights] = await Promise.all([
        getClipping(),
        getClippingInsights(30),
      ]);
      if (getActiveClientId() !== clientId) return;
      setView(nextView);
      setInsights(nextInsights);
    } catch (cause) {
      if (getActiveClientId() === clientId) {
        setError(cause instanceof Error ? cause.message : "Não foi possível carregar os sinais.");
      }
    } finally {
      if (getActiveClientId() === clientId) setBusy(false);
    }
  }, [clientId]);

  useEffect(() => { void load(); }, [load]);

  const items = useMemo(() => {
    const all = view?.items || [];
    return all.filter((item) => kind === "todos" || item.kind === kind)
      .sort((a, b) => (b.published_at || b.created_at || "").localeCompare(a.published_at || a.created_at || ""))
      .slice(0, 18);
  }, [view, kind]);

  const signals = useMemo(() => (view?.items || []).filter((item: Clipping) => item.relevant !== false), [view]);
  const evidenceCount = signals.filter(item => Boolean(safeLink(item.url))).length;
  const topics = (insights?.themes || []).filter((topic) => topic.key && topic.count > 0).slice(0, 8);
  const opportunities = signals.filter(item => (item.opportunities || []).length > 0).slice(0, 6);

  return (
    <Shell title="" variant="editorial">
      <PageHeader
        company={company}
        title="Radar Cultural"
        dateline={<span>Sinais com fonte identificada · Clipping existente · Recorte analítico de 30 dias</span>}
        controls={<button type="button" className="btn btnPrimary" disabled={busy} onClick={() => void load()}>
          <RefreshCw size={16} aria-hidden="true" /> {busy ? "Carregando..." : "Atualizar leitura"}
        </button>}
      />
      <div style={{ display: "grid", gap: 18, paddingBottom: 40 }}>
        <section className="ds-section" aria-label="Visão do radar">
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
            <RadarIcon size={21} aria-hidden="true" />
            <div>
              <h2 className="ds-sectionTitle" style={{ margin: 0 }}>O que está acontecendo ao redor da marca</h2>
              <p style={{ margin: "4px 0 0", opacity: .72 }}>Leitura inicial de notícias, temas e oportunidades verificáveis. Não representa a audiência total das redes sociais.</p>
            </div>
          </div>
          {error ? <p role="alert">Erro na leitura: {error}. Confira o acesso ao Clipping e tente novamente.</p> : null}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(185px, 1fr))", gap: 12 }}>
            {[
              ["Sinais coletados", insights?.total, "Clipping no período"],
              ["Sinais analisados", insights?.analyzed, "Classificados na fonte"],
              ["Com evidência", evidenceCount, "Links disponíveis na leitura"],
              ["Temas identificados", topics.length, "Categorias com registros"],
            ].map(([label, number, description]) => (
              <div key={String(label)} style={{ border: "1px solid var(--border, #d9dfe2)", borderRadius: 12, padding: 18 }}>
                <p style={{ margin: "0 0 8px", opacity: .72 }}>{label}</p>
                <strong style={{ fontSize: 28 }}>{busy && !insights ? "—" : (number ?? "—")}</strong>
                <p style={{ margin: "6px 0 0", fontSize: 12, opacity: .7 }}>{description}</p>
              </div>
            ))}
          </div>
        </section>
        <section className="ds-section" aria-labelledby="radar-themes">
          <h2 id="radar-themes" className="ds-sectionTitle"><TrendingUp size={18} aria-hidden="true" /> Temas observados</h2>
          <p style={{ opacity: .75 }}>Frequência de menções encontradas no Clipping. Mais menções não significam necessariamente uma tendência em crescimento.</p>
          {topics.length ? <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
            {topics.map(topic => <span key={topic.key} style={{ border: "1px solid var(--border, #d9dfe2)", borderRadius: 20, padding: "8px 12px" }}>{topic.key} · {topic.count}</span>)}
          </div> : <p>Nenhum tema classificado neste período. Configure e atualize o Clipping para alimentar esta leitura.</p>}
        </section>
        <section className="ds-section" aria-labelledby="radar-opportunities">
          <h2 id="radar-opportunities" className="ds-sectionTitle">Oportunidades com evidências</h2>
          {opportunities.length ? <div style={{ display: "grid", gap: 12 }}>
            {opportunities.map(item => <article key={item.id} style={{ border: "1px solid var(--border, #d9dfe2)", borderRadius: 12, padding: 16 }}>
              <strong>{item.title}</strong>
              <p style={{ opacity: .75 }}>{item.source || "Fonte não identificada"} · {dateLabel(item.published_at)}</p>
              <ul>{(item.opportunities || []).slice(0, 3).map((value, index) => <li key={index}>{value}</li>)}</ul>
              {safeLink(item.url) ? <a href={safeLink(item.url)!} target="_blank" rel="noopener noreferrer">Ver fonte <ArrowUpRight size={14} aria-hidden="true" /></a> : null}
            </article>)}
          </div> : <p>Ainda não há oportunidades classificadas com evidências. O Radar não cria recomendações artificiais quando faltam dados.</p>}
        </section>
        <section className="ds-section" aria-labelledby="radar-evidence">
          <h2 id="radar-evidence" className="ds-sectionTitle"><BookOpen size={18} aria-hidden="true" /> Evidências e concorrência</h2>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 14 }}>
            {(["todos", "marca", "concorrente", "tema"] as const).map(value =>
              <button key={value} className="btn" type="button" aria-pressed={kind === value} onClick={() => setKind(value)}
                style={{ border: "1px solid var(--border, #d9dfe2)", opacity: kind === value ? 1 : .65 }}>
                {{ todos: "Todos", marca: "Marca", concorrente: "Concorrentes", tema: "Temas" }[value]}
              </button>)}
          </div>
          {items.length ? <div style={{ display: "grid", gap: 10 }}>
            {items.map(item => <article key={item.id} style={{ borderBottom: "1px solid var(--border, #d9dfe2)", paddingBottom: 12 }}>
              <strong>{item.title}</strong>
              <p style={{ margin: "5px 0", opacity: .75 }}>{item.kind} · {item.source || "Fonte não identificada"} · {dateLabel(item.published_at)}</p>
              {item.summary ? <p style={{ margin: "6px 0" }}>{item.summary}</p> : null}
              {safeLink(item.url) ? <a href={safeLink(item.url)!} target="_blank" rel="noopener noreferrer">Abrir notícia <ArrowUpRight size={14} aria-hidden="true" /></a> : null}
            </article>)}
          </div> : <p>{busy ? "Carregando evidências..." : "Sem registros para o filtro selecionado."}</p>}
        </section>
        <p style={{ fontSize: 12, opacity: .7 }}>Radar v1 usa exclusivamente as leituras de Clipping já autorizadas para esta empresa. Cobertura social ampla, previsão de tendências e share of attention não estão disponíveis nesta versão.</p>
      </div>
    </Shell>
  );
}
