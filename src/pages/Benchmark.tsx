import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { ArrowUpRight, RefreshCw, X } from "lucide-react";
import { getActiveClient, getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  addBenchmarkCompetitor, addBenchmarkEvidence, autoBenchmarkCompetitors, getBenchmarkOverview, refreshBenchmarkInstagram, removeBenchmarkCompetitor,
  type BenchmarkCategory, type BenchmarkInstagramRow, type BenchmarkOverview,
} from "../app/benchmark";
import PageHeader from "../components/data/PageHeader";
import PricesSection from "../components/benchmark/PricesSection";
import Shell from "../components/Shell";
import "../styles/benchmark.css";
import PageSkeleton from "../components/data/PageSkeleton";

const CATEGORIES: { id: BenchmarkCategory; label: string; note: string }[] = [
  { id: "ads", label: "Anúncios", note: "Biblioteca de anúncios e criativos públicos. Sem gasto nem ROAS privado." },
  { id: "search", label: "Busca", note: "Termos e resultados documentados. Sem volume estimado sem fonte." },
  { id: "ecommerce", label: "E-commerce", note: "Preços, ofertas e lançamentos públicos." },
  { id: "content", label: "Conteúdo", note: "Publicações e formatos com link verificável." },
];
const OWN_GROUPS = [
  { name: "Meta Ads", fields: [["meta_spend", "Investimento"], ["meta_attributed_revenue", "Receita atribuída"], ["meta_impressions", "Impressões"], ["meta_clicks", "Cliques"]] },
  { name: "Google Ads", fields: [["google_ads_spend", "Investimento"], ["google_ads_conversion_value", "Valor de conversão"], ["google_ads_impressions", "Impressões"], ["google_ads_clicks", "Cliques"]] },
  { name: "GA4", fields: [["ga4_sessions", "Sessões"], ["ga4_revenue", "Receita GA4"], ["ga4_purchases", "Compras"]] },
  { name: "Loja", fields: [["shopify_net_revenue", "Receita líquida"], ["shopify_orders", "Pedidos"]] },
  { name: "Instagram", fields: [["instagram_reach", "Alcance"], ["instagram_interactions", "Interações"]] },
] as const;
const MONEY = new Set(["meta_spend", "meta_attributed_revenue", "google_ads_spend", "google_ads_conversion_value", "ga4_revenue", "shopify_net_revenue"]);
const PERIODS = [30, 60, 90] as const;
const nf = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const fmt = (value: number | null | undefined, money = false) => value == null ? "Sem dado" : money ? brl.format(value) : nf.format(value);
const dash = (value: number | null | undefined, f = nf) => value == null ? "—" : f.format(value);
const message = (cause: unknown, fallback: string) => cause instanceof Error && cause.message ? cause.message : fallback;

function publicUrl(raw: string | null | undefined): string | null {
  if (!raw) return null;
  try { const u = new URL(raw); return u.protocol === "https:" ? u.href : null; } catch { return null; }
}

/** Barra do share de atenção: a marca no azul Mugô, cada concorrente num cinza. */
function ShareBar({ rows }: { rows: BenchmarkInstagramRow[] }) {
  const parts = rows.filter((r) => (r.share ?? 0) > 0);
  if (!parts.length) return null;
  let rival = 0;
  return <div className="bmShare" role="img" aria-label={`Share de atenção: ${parts.map((r) => `${r.name} ${nf1.format(r.share ?? 0)}%`).join(", ")}`}>
    {parts.map((r) => <span key={r.handle} className={r.is_brand ? "is-brand" : `is-rival-${(rival++ % 4) + 1}`}
      style={{ flexBasis: `${r.share}%` }} title={`${r.name}: ${nf1.format(r.share ?? 0)}%`}>
      {(r.share ?? 0) >= 9 ? `${nf.format(r.share ?? 0)}%` : ""}
    </span>)}
  </div>;
}

export default function Benchmark() {
  const clientId = getActiveClientId();
  const company = getActiveClientName() || "Empresa";
  const [days, setDays] = useState<30 | 60 | 90>(30);
  const [data, setData] = useState<BenchmarkOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [instagram, setInstagram] = useState("");
  const [youtube, setYoutube] = useState("");
  const [facebook, setFacebook] = useState("");
  const canEdit = ["agency_admin", "platform_admin", "client_admin", "owner", "admin", "account_manager"].includes(String(getActiveClient()?.role || "").toLowerCase());
  const [competitor, setCompetitor] = useState("");
  const [category, setCategory] = useState<BenchmarkCategory>("ads");
  const [title, setTitle] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [observation, setObservation] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const result = await getBenchmarkOverview(days);
      if (clientId === getActiveClientId()) setData(result);
    } catch (cause) {
      if (clientId === getActiveClientId()) setError(message(cause, "Não foi possível carregar o benchmarking."));
    } finally {
      if (clientId === getActiveClientId()) setLoading(false);
    }
  }, [clientId, days]);
  useEffect(() => { void load(); }, [load]);

  // Benchmarking já abre com concorrentes: lista vazia → a IA cadastra (uma tentativa por marca nesta tela).
  const autoTried = useRef<string | null>(null);
  const autoFill = useCallback(async (force: boolean) => {
    setBusy("auto"); setError(null);
    setNotice(force ? "A IA está procurando mais concorrentes…" : "A IA está montando a lista de concorrentes pelo Clipping e pelo contexto do negócio…");
    try {
      const out = await autoBenchmarkCompetitors(force);
      if (clientId !== getActiveClientId()) return;
      if (out.added.length) {
        setNotice(`A IA cadastrou ${out.added.length} concorrente${out.added.length > 1 ? "s" : ""}: ${out.added.map((c) => c.name).join(", ")}. Confira e tire quem não faz sentido.`);
        try { await refreshBenchmarkInstagram(); } catch { /* números públicos chegam na próxima coleta */ }
        await load();
      } else {
        setNotice(out.status === "limite_do_plano" ? "O plano não comporta mais concorrentes."
          : out.status === "sem_ia" || out.status === "aguardando" ? "A IA não conseguiu sugerir agora. Cadastre manualmente ou tente mais tarde."
          : out.status === "ja_tem" ? null : "A IA não encontrou concorrentes novos.");
      }
    } catch (cause) {
      if (clientId === getActiveClientId()) { setNotice(null); setError(message(cause, "A IA não conseguiu sugerir concorrentes agora.")); }
    } finally { setBusy(null); }
  }, [clientId, load]);
  useEffect(() => {
    if (!canEdit || !data || data.competitors.length || autoTried.current === clientId) return;
    autoTried.current = clientId;
    void autoFill(false);
  }, [autoFill, canEdit, clientId, data]);

  async function act(key: string, run: () => Promise<string | void>, fallback: string) {
    setBusy(key); setNotice(null); setError(null);
    try { const done = await run(); if (done) setNotice(done); await load(); }
    catch (cause) { setError(message(cause, fallback)); }
    finally { setBusy(null); }
  }

  const addCompetitor = (event: FormEvent) => {
    event.preventDefault();
    void act("competitor", async () => {
      await addBenchmarkCompetitor({ name: name.trim(), website: website.trim() || null,
        instagram_handle: instagram.trim().replace(/^@/, "") || null, youtube_handle: youtube.trim().replace(/^@/, "") || null,
        facebook_page: facebook.trim() || null });
      setName(""); setWebsite(""); setInstagram(""); setYoutube(""); setFacebook("");
      return "Concorrente cadastrado. Clique em Atualizar Instagram para trazer os números públicos dele.";
    }, "Não foi possível salvar o concorrente.");
  };
  const addEvidence = (event: FormEvent) => {
    event.preventDefault();
    void act("evidence", async () => {
      await addBenchmarkEvidence({ competitor_id: competitor, category, title: title.trim(), source_url: sourceUrl.trim(), observation: observation.trim() || null });
      setTitle(""); setSourceUrl(""); setObservation("");
      return "Evidência registrada com a fonte.";
    }, "Não foi possível salvar a evidência.");
  };
  const refreshInstagram = () => void act("instagram", async () => {
    const r = await refreshBenchmarkInstagram();
    const failed = r.errors.length ? ` ${r.errors.map((e) => `@${e.handle}`).join(", ")} não respondeu (conta pessoal ou @ errado).` : "";
    return `Instagram atualizado: ${r.updated} perfil(is).${failed}`;
  }, "Não foi possível atualizar o Instagram.");
  const remove = (id: string, label: string) => void act(`remove:${id}`, async () => {
    await removeBenchmarkCompetitor(id);
    return `${label} saiu do monitoramento.`;
  }, "Não foi possível remover.");

  const byCategory = useMemo(() => CATEGORIES.map((item) => ({ ...item, rows: data?.evidence.filter((e) => e.category === item.id) || [] })), [data]);
  const competitorName = (id: string) => data?.competitors.find((c) => c.id === id)?.name || "Concorrente";
  const ig = data?.instagram;
  const igRows = ig?.rows || [];
  const brand = igRows.find((r) => r.is_brand);
  const withHandle = (data?.competitors || []).filter((c) => c.instagram_handle).length;

  return <Shell title="Benchmarking" variant="editorial"><div className="ds-page bmPage">
    <PageHeader company={company} title="Benchmarking"
      dateline={<span>Sua marca contra os concorrentes, só com dado público e verificável</span>}
      controls={<div className="bmControls">
        <div className="ds-segmented" role="group" aria-label="Período">
          {PERIODS.map((p) => <button key={p} type="button" aria-pressed={days === p} onClick={() => setDays(p)}>{p} dias</button>)}
        </div>
        <button type="button" className="ds-button is-primary" onClick={refreshInstagram} disabled={Boolean(busy) || loading}>
          <RefreshCw size={15} aria-hidden="true" className={busy === "instagram" ? "bmSpin" : ""} />
          {busy === "instagram" ? "Buscando no Instagram…" : "Atualizar Instagram"}
        </button>
      </div>} />
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {notice ? <p role="status" className="studioNotice">{notice}</p> : null}

    <section className="bmCard" aria-labelledby="bm-ig">
      <div className="bmCardHead">
        <div>
          <h2 id="bm-ig">Instagram: sua marca x concorrentes</h2>
          <p className="bmSub">Share de atenção = fatia das curtidas e comentários do período que ficou com cada perfil.</p>
        </div>
        {brand?.share != null ? <div className="bmBig"><b>{nf1.format(brand.share)}%</b><span>da atenção é sua</span></div> : null}
      </div>
      {loading && !data ? <PageSkeleton label="Carregando o benchmarking…" />
        : ig && !ig.available ? <p className="bmMuted">Falta aplicar a migração 000106 no Supabase para guardar os números do Instagram.</p>
        : !withHandle ? <p className="bmEmpty">Cadastre o @ do Instagram de um concorrente (abaixo) e clique em Atualizar Instagram.</p>
        : !igRows.length ? <p className="bmEmpty">Ainda sem coleta. Clique em <b>Atualizar Instagram</b> para buscar o perfil público da marca e dos concorrentes.</p>
        : <>
          <ShareBar rows={igRows} />
          <div className="bmScroll"><table className="ds-table bmTable">
            <thead><tr><th>Perfil</th><th className="is-number">Seguidores</th><th className="is-number">Posts/semana</th>
              <th className="is-number">Interações por post</th><th className="is-number">Engajamento</th><th className="is-number">Share de atenção</th><th>Melhor post</th></tr></thead>
            <tbody>{igRows.map((r) => <tr key={r.handle} className={r.is_brand ? "is-brand" : ""}>
              <td className="is-primary"><span className="bmName">{r.name}</span><small>@{r.handle}{r.sampled ? " · amostra" : ""}{r.hidden_likes ? " · curtidas ocultas" : ""}</small></td>
              <td className="is-number">{dash(r.followers)}</td>
              <td className="is-number">{dash(r.posts_per_week, nf1)}</td>
              <td className="is-number">{dash(r.avg_interactions)}</td>
              <td className="is-number">{r.engagement_rate == null ? "—" : `${nf1.format(r.engagement_rate)}%`}</td>
              <td className="is-number"><b>{r.share == null ? "—" : `${nf1.format(r.share)}%`}</b></td>
              <td>{publicUrl(r.top_post?.url) ? <a className="ds-link" href={publicUrl(r.top_post?.url)!} target="_blank" rel="noopener noreferrer">
                {dash(r.top_post?.interactions)} interações <ArrowUpRight size={13} aria-hidden="true" /></a> : "—"}</td>
            </tr>)}</tbody>
          </table></div>
          <p className="bmFoot">
            Coletado em {ig?.collected_at ? new Date(ig.collected_at).toLocaleString("pt-BR") : "—"} pela API pública da Meta (até 30 posts recentes por perfil).
            "Amostra": o perfil posta tanto que os 30 posts não cobrem o período; os números do período são o mínimo. Visualizações de concorrentes não existem nessa API e não são estimadas.
          </p>
        </>}
    </section>

    {data ? <PricesSection competitors={data.competitors} canEdit={canEdit} /> : null}

    <section className="bmCard" aria-labelledby="bm-watch">
      <h2 id="bm-watch">Concorrentes monitorados <span className="bmCount">{data?.competitors.length ?? "—"}</span></h2>
      {data?.competitors.length ? <ul className="bmCompetitors">
        {data.competitors.map((c) => <li key={c.id}>
          <div><b>{c.name}</b>
            <small>{c.instagram_handle ? `@${c.instagram_handle}` : "sem Instagram"}{c.youtube_handle ? ` · YouTube @${c.youtube_handle}` : ""}</small>
            {publicUrl(c.website) ? <a className="ds-link" href={publicUrl(c.website)!} target="_blank" rel="noopener noreferrer">Site <ArrowUpRight size={13} aria-hidden="true" /></a> : null}
          </div>
          <button type="button" className="bmRemove" aria-label={`Remover ${c.name}`} title="Tirar do monitoramento"
            disabled={Boolean(busy)} onClick={() => remove(c.id, c.name)}><X size={15} aria-hidden="true" /></button>
        </li>)}
      </ul> : <p className="bmMuted">{busy === "auto" ? "A IA está buscando os concorrentes da marca…" : "Nenhum concorrente nesta empresa ainda."}</p>}
      {canEdit ? <button type="button" className="ds-button bmAuto" disabled={Boolean(busy)} onClick={() => void autoFill(true)}>
        {busy === "auto" ? "Buscando…" : data?.competitors.length ? "Sugerir mais com IA" : "Buscar concorrentes com IA"}</button> : null}
      <form className="bmForm" onSubmit={addCompetitor}>
        <h3>Adicionar concorrente</h3>
        <div className="bmGrid">
          <input aria-label="Nome do concorrente" placeholder="Nome" required minLength={2} maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
          <input aria-label="Instagram do concorrente" placeholder="@instagram" value={instagram} onChange={(e) => setInstagram(e.target.value)} />
          <input aria-label="Site do concorrente" placeholder="https://site (opcional)" value={website} onChange={(e) => setWebsite(e.target.value)} />
          <input aria-label="YouTube do concorrente" placeholder="@youtube (opcional)" value={youtube} onChange={(e) => setYoutube(e.target.value)} />
          <input aria-label="Página do Facebook do concorrente" placeholder="Página do Facebook ou ID (opcional, para anúncios)" value={facebook} onChange={(e) => setFacebook(e.target.value)} />
        </div>
        <button className="ds-button is-primary" type="submit" disabled={Boolean(busy)}>{busy === "competitor" ? "Salvando…" : "Salvar concorrente"}</button>
      </form>
    </section>

    <section className="bmCard" aria-labelledby="bm-own">
      <h2 id="bm-own">Números da sua marca <span className="bmSub">últimos {days} dias</span></h2>
      <div className="bmOwn">
        {OWN_GROUPS.map((group) => <article key={group.name}>
          <h3>{group.name}</h3>
          {group.fields.map(([field, label]) => <div key={field} className="bmMetric">
            <span>{label}</span><b>{fmt(data?.own.totals[field], MONEY.has(field))}</b>
            <small>{data?.own.days_with_data[field] || 0} dias com dado</small>
          </div>)}
        </article>)}
      </div>
      <p className="bmFoot">{data?.own.methodology || "Aguardando os dados da marca."}</p>
    </section>

    <section className="bmCard" aria-labelledby="bm-evidence">
      <h2 id="bm-evidence">Evidências públicas</h2>
      <p className="bmSub">Links de bibliotecas de anúncios, buscas, páginas de produto e conteúdos dos concorrentes, com a fonte.</p>
      <div className="bmEvidence">
        {byCategory.map((section) => <article key={section.id}>
          <h3>{section.label} <span className="bmCount">{section.rows.length}</span></h3>
          <p className="bmMuted">{section.note}</p>
          {section.rows.slice(0, 8).map((e) => <div key={e.id} className="bmEvidenceItem">
            <b>{e.title}</b><small>{competitorName(e.competitor_id)}</small>
            {e.observation ? <p>{e.observation}</p> : null}
            {publicUrl(e.source_url) ? <a className="ds-link" href={publicUrl(e.source_url)!} target="_blank" rel="noopener noreferrer">Ver fonte <ArrowUpRight size={13} aria-hidden="true" /></a> : null}
          </div>)}
        </article>)}
      </div>
      {data?.competitors.length ? <form className="bmForm" onSubmit={addEvidence}>
        <h3>Registrar evidência</h3>
        <div className="bmGrid">
          <select aria-label="Concorrente" value={competitor} onChange={(e) => setCompetitor(e.target.value)} required>
            <option value="">Concorrente</option>{data.competitors.map((c) => <option value={c.id} key={c.id}>{c.name}</option>)}
          </select>
          <select aria-label="Canal" value={category} onChange={(e) => setCategory(e.target.value as BenchmarkCategory)}>
            {CATEGORIES.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
          <input aria-label="O que foi observado" placeholder="O que foi observado?" required minLength={3} maxLength={240} value={title} onChange={(e) => setTitle(e.target.value)} />
          <input aria-label="Link da fonte" type="url" placeholder="https://… (link da fonte)" required value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} />
        </div>
        <textarea aria-label="Por que importa" placeholder="Por que isso importa? (opcional)" maxLength={2000} rows={2} value={observation} onChange={(e) => setObservation(e.target.value)} />
        <button className="ds-button is-primary" type="submit" disabled={Boolean(busy)}>{busy === "evidence" ? "Salvando…" : "Registrar evidência"}</button>
      </form> : null}
    </section>

    <section className="bmCard" aria-labelledby="bm-news">
      <h2 id="bm-news">Concorrentes no Clipping</h2>
      {data?.public_mentions.length ? <ul className="bmNews">{data.public_mentions.slice(0, 12).map((m) => <li key={m.id}>
        <div><b>{m.title}</b><small>{m.term} · {m.source || "fonte não informada"}</small></div>
        {publicUrl(m.url) ? <a className="ds-link" href={publicUrl(m.url)!} target="_blank" rel="noopener noreferrer">Ler <ArrowUpRight size={13} aria-hidden="true" /></a> : null}
      </li>)}</ul> : <p className="bmMuted">Nenhuma notícia de concorrente no período. Os termos de concorrentes ficam no radar do Clipping.</p>}
    </section>

    <details className="bmCard bmLimits"><summary className="ds-disclosure">Metodologia e limites</summary>
      <ul>{(data?.limitations || []).map((x) => <li key={x}>{x}</li>)}</ul>
    </details>
  </div></Shell>;
}
