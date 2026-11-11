import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { ArrowUpRight, BarChart3, Plus, RefreshCw } from "lucide-react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { addBenchmarkCompetitor, addBenchmarkEvidence, getBenchmarkOverview, type BenchmarkCategory, type BenchmarkOverview } from "../app/benchmark";
import PageHeader from "../components/data/PageHeader";
import Shell from "../components/Shell";

const CATEGORIES: { id: BenchmarkCategory; label: string; note: string }[] = [
  { id: "ads", label: "Anúncios", note: "Bibliotecas de anúncios e criativos públicos; sem gasto ou ROAS privado." },
  { id: "search", label: "Busca", note: "Termos, resultados e notícias documentados; sem volume estimado sem fonte." },
  { id: "ecommerce", label: "E-commerce", note: "Preços, ofertas e lançamentos disponíveis publicamente." },
  { id: "content", label: "Conteúdo", note: "Publicações e formatos com links verificáveis." },
];
const OWN_GROUPS = [
  { name: "Meta Ads", fields: [["meta_spend", "Investimento"], ["meta_attributed_revenue", "Receita atribuída"], ["meta_impressions", "Impressões"], ["meta_clicks", "Cliques"]] },
  { name: "Google Ads", fields: [["google_ads_spend", "Investimento"], ["google_ads_conversion_value", "Valor de conversão atribuído"], ["google_ads_impressions", "Impressões"], ["google_ads_clicks", "Cliques"]] },
  { name: "GA4", fields: [["ga4_sessions", "Sessões"], ["ga4_revenue", "Receita GA4"], ["ga4_purchases", "Compras GA4"]] },
  { name: "E-commerce", fields: [["shopify_net_revenue", "Receita líquida Shopify"], ["shopify_orders", "Pedidos Shopify"]] },
  { name: "Instagram", fields: [["instagram_reach", "Alcance"], ["instagram_interactions", "Interações"]] },
] as const;
const MONEY = new Set(["meta_spend", "meta_attributed_revenue", "google_ads_spend", "google_ads_conversion_value", "ga4_revenue", "shopify_net_revenue"]);
const format = (value: number | null | undefined, money = false) => value == null ? "Sem dados" : money
  ? new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 2 }).format(value)
  : new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 }).format(value);
function publicUrl(raw: string | null | undefined): string | null {
  if (!raw) return null;
  try { const u = new URL(raw); return u.protocol === "https:" ? u.href : null; } catch { return null; }
}

export default function Benchmark() {
  const clientId = getActiveClientId();
  const company = getActiveClientName() || "Empresa";
  const [days, setDays] = useState<30 | 60 | 90>(30);
  const [data, setData] = useState<BenchmarkOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [instagram, setInstagram] = useState("");
  const [youtube, setYoutube] = useState("");
  const [competitor, setCompetitor] = useState("");
  const [category, setCategory] = useState<BenchmarkCategory>("ads");
  const [title, setTitle] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [observation, setObservation] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getBenchmarkOverview(days);
      if (clientId !== getActiveClientId()) return;
      setData(result);
    } catch (cause) {
      if (clientId === getActiveClientId()) setError(cause instanceof Error ? cause.message : "Erro na consulta.");
    } finally {
      if (clientId === getActiveClientId()) setLoading(false);
    }
  }, [clientId, days]);
  useEffect(() => { void load(); }, [load]);

  const addCompetitor = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setNotice(null); setError(null);
    try {
      await addBenchmarkCompetitor({
        name: name.trim(), website: website.trim() || null,
        instagram_handle: instagram.trim().replace(/^@/, "") || null,
        youtube_handle: youtube.trim().replace(/^@/, "") || null,
      });
      setName(""); setWebsite(""); setInstagram(""); setYoutube("");
      setNotice("Concorrente cadastrado."); await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível salvar."); }
    finally { setSaving(false); }
  };
  const addEvidence = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setNotice(null); setError(null);
    try {
      await addBenchmarkEvidence({ competitor_id: competitor, category, title: title.trim(),
        source_url: sourceUrl.trim(), observation: observation.trim() || null });
      setTitle(""); setSourceUrl(""); setObservation("");
      setNotice("Evidência registrada com fonte."); await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível salvar."); }
    finally { setSaving(false); }
  };

  const byCategory = useMemo(() => CATEGORIES.map(item => ({
    ...item, rows: data?.evidence.filter(e => e.category === item.id) || [],
  })), [data]);
  const linkedCompetitor = (id: string) => data?.competitors.find(c => c.id === id)?.name || "Concorrente";

  return <Shell title="" variant="editorial">
    <PageHeader company={company} title="Benchmarking"
      dateline={<span>Indicadores próprios conectados + evidências públicas de concorrentes · Cada empresa isolada</span>}
      controls={<div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <label htmlFor="benchmark-days" className="sr-only">Período de comparação</label>
        <select id="benchmark-days" className="input" value={days} onChange={e => setDays(Number(e.target.value) as 30 | 60 | 90)}>
          <option value={30}>Últimos 30 dias</option><option value={60}>Últimos 60 dias</option><option value={90}>Últimos 90 dias</option>
        </select>
        <button className="btn btnPrimary" type="button" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={16} aria-hidden="true" /> Atualizar
        </button>
      </div>} />
    <div style={{ display: "grid", gap: 20, paddingBottom: 40 }}>
      {error ? <p role="alert" style={{ padding: 12, border: "1px solid currentColor", borderRadius: 10 }}>{error}</p> : null}
      {notice ? <p role="status">{notice}</p> : null}
      <section className="ds-section" aria-labelledby="bench-own">
        <h2 className="ds-sectionTitle" id="bench-own"><BarChart3 size={18} aria-hidden="true" /> Dados da própria marca</h2>
        <p style={{ opacity: .74 }}>Leituras dos módulos existentes; receitas atribuídas por canal não são somadas à receita da loja. Dados ausentes não viram zero.</p>
        {loading && !data ? <p>Consultando os indicadores...</p> : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(225px,1fr))", gap: 12 }}>
            {OWN_GROUPS.map(group => <article key={group.name} style={{ border: "1px solid var(--border,#d9dfe2)", borderRadius: 12, padding: 16 }}>
              <h3 style={{ margin: "0 0 12px" }}>{group.name}</h3>
              {group.fields.map(([field, label]) => <div key={field} style={{ marginBottom: 9 }}>
                <p style={{ margin: 0, opacity: .72, fontSize: 12 }}>{label}</p>
                <strong>{format(data?.own.totals[field], MONEY.has(field))}</strong>
                <p style={{ fontSize: 11, margin: "3px 0 0", opacity: .65 }}>Cobertura: {data?.own.days_with_data[field] || 0} dias</p>
              </div>)}
            </article>)}
          </div>
        )}
        <p style={{ fontSize: 12, opacity: .72 }}>{data?.own.methodology || "Aguardando dados do read model."}</p>
      </section>

      <section className="ds-section" aria-labelledby="bench-watchlist">
        <h2 className="ds-sectionTitle" id="bench-watchlist">Concorrentes monitorados ({data?.competitors.length ?? "—"})</h2>
        <p style={{ opacity: .74 }}>Cadastre os concorrentes desta empresa. A inclusão não concede acesso a métricas privadas dos perfis.</p>
        {data?.competitors.length ? <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 10 }}>
          {data.competitors.map(c => <article key={c.id} style={{ border: "1px solid var(--border,#d9dfe2)", borderRadius: 10, padding: 14 }}>
            <strong>{c.name}</strong>
            <p style={{ fontSize: 12, opacity: .75 }}>{c.instagram_handle ? `Instagram: @${c.instagram_handle}` : "Instagram não cadastrado"}</p>
            {publicUrl(c.website) ? <a href={publicUrl(c.website)!} target="_blank" rel="noopener noreferrer">Ver site <ArrowUpRight size={14} aria-hidden="true" /></a> : null}
          </article>)}
        </div> : <p>Sem concorrentes cadastrados nesta empresa.</p>}
        <form onSubmit={e => void addCompetitor(e)} style={{ display: "grid", gap: 10, maxWidth: 700, marginTop: 18 }}>
          <h3>Adicionar concorrente</h3>
          <input className="input" aria-label="Nome do concorrente" placeholder="Nome do concorrente" required minLength={2} maxLength={120} value={name} onChange={e => setName(e.target.value)} />
          <input className="input" aria-label="Site público" placeholder="Site HTTPS (opcional)" value={website} onChange={e => setWebsite(e.target.value)} />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))", gap: 8 }}>
            <input className="input" aria-label="Instagram público" placeholder="@instagram (opcional)" value={instagram} onChange={e => setInstagram(e.target.value)} />
            <input className="input" aria-label="YouTube público" placeholder="@youtube (opcional)" value={youtube} onChange={e => setYoutube(e.target.value)} />
          </div>
          <button className="btn btnPrimary" disabled={saving} type="submit"><Plus size={16} aria-hidden="true" /> Salvar concorrente</button>
        </form>
      </section>

      <section className="ds-section" aria-labelledby="bench-evidence">
        <h2 className="ds-sectionTitle" id="bench-evidence">Anúncios · Busca · E-commerce · Conteúdo</h2>
        <p style={{ opacity: .74 }}>Evidências públicas auditáveis. Links de bibliotecas de anúncios, resultados de busca, páginas de produto e conteúdos. A coleta automatizada dependerá de APIs e permissões adicionais.</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(210px,1fr))", gap: 12 }}>
          {byCategory.map(section => <article key={section.id} style={{ border: "1px solid var(--border,#d9dfe2)", borderRadius: 12, padding: 14 }}>
            <h3 style={{ margin: "0 0 4px" }}>{section.label} · {section.rows.length}</h3>
            <p style={{ fontSize: 12, opacity: .7 }}>{section.note}</p>
            {section.rows.slice(0, 8).map(e => <div key={e.id} style={{ borderTop: "1px solid var(--border,#d9dfe2)", paddingTop: 9, marginTop: 9 }}>
              <strong>{e.title}</strong>
              <p style={{ fontSize: 12, opacity: .75, margin: "4px 0" }}>{linkedCompetitor(e.competitor_id)}</p>
              {e.observation ? <p style={{ fontSize: 13 }}>{e.observation}</p> : null}
              {publicUrl(e.source_url) ? <a href={publicUrl(e.source_url)!} target="_blank" rel="noopener noreferrer">Ver evidência <ArrowUpRight size={14} aria-hidden="true" /></a> : null}
            </div>)}
            {section.rows.length === 0 ? <p style={{ opacity: .7, fontSize: 13 }}>Sem evidências neste período.</p> : null}
          </article>)}
        </div>
        {data?.competitors.length ? <form onSubmit={e => void addEvidence(e)} style={{ display: "grid", gap: 10, maxWidth: 700, marginTop: 18 }}>
          <h3>Registrar evidência pública</h3>
          <label>Concorrente
            <select className="input" value={competitor} onChange={e => setCompetitor(e.target.value)} required>
              <option value="">Selecione</option>{data.competitors.map(c => <option value={c.id} key={c.id}>{c.name}</option>)}
            </select>
          </label>
          <label>Canal
            <select className="input" value={category} onChange={e => setCategory(e.target.value as BenchmarkCategory)}>
              {CATEGORIES.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
          </label>
          <input className="input" aria-label="Título da evidência" placeholder="O que foi observado?" required minLength={3} maxLength={240} value={title} onChange={e => setTitle(e.target.value)} />
          <input className="input" aria-label="Link original da evidência" type="url" placeholder="https://... (link original)" required value={sourceUrl} onChange={e => setSourceUrl(e.target.value)} />
          <textarea className="input" aria-label="Análise da evidência" placeholder="Por que essa evidência importa? (opcional)" maxLength={2000} rows={3} value={observation} onChange={e => setObservation(e.target.value)} />
          <button className="btn btnPrimary" type="submit" disabled={saving}>Registrar evidência</button>
        </form> : null}
      </section>

      <section className="ds-section" aria-labelledby="bench-mentions">
        <h2 className="ds-sectionTitle" id="bench-mentions">Concorrentes no Clipping</h2>
        <p style={{ opacity: .74 }}>Notícias existentes, automaticamente reutilizadas do Clipping da empresa.</p>
        {data?.public_mentions.length ? data.public_mentions.slice(0, 12).map(m => <article key={m.id} style={{ borderBottom: "1px solid var(--border,#d9dfe2)", padding: "10px 0" }}>
          <strong>{m.title}</strong><p style={{ fontSize: 12, opacity: .72 }}>{m.term} · {m.source || "Fonte não informada"}</p>
          {publicUrl(m.url) ? <a href={publicUrl(m.url)!} target="_blank" rel="noopener noreferrer">Ler notícia <ArrowUpRight size={14} aria-hidden="true" /></a> : null}
        </article>) : <p>Nenhuma menção concorrente registrada no período.</p>}
      </section>
      <section className="ds-section">
        <h2 className="ds-sectionTitle">Metodologia e limites</h2>
        <ul>{(data?.limitations || ["Não há acesso a métricas privadas de concorrentes."]).map(x => <li key={x}>{x}</li>)}</ul>
      </section>
    </div>
  </Shell>;
}
