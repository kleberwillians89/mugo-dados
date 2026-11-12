import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowUpRight, RefreshCw, X } from "lucide-react";
import {
  addBenchmarkProduct, checkBenchmarkProduct, getBenchmarkPrices, getStoreCatalog, removeBenchmarkProduct,
  type BenchmarkCompetitor, type BenchmarkPrices, type CatalogItem,
} from "../../app/benchmark";

const brl = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" }));
const day = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });

function Spark({ points }: { points: { price: number | null }[] }) {
  const values = points.map((p) => p.price).filter((v): v is number => v != null);
  if (values.length < 2) return <span className="bmMuted">—</span>;
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const d = values.map((v, i) => `${i === 0 ? "M" : "L"}${(i / (values.length - 1)) * 100},${28 - ((v - min) / span) * 24}`).join(" ");
  return <svg className="bmSpark" viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true"><path d={d} /></svg>;
}

/** Preços públicos dos concorrentes (e da marca), com histórico diário, e o atalho para a Biblioteca de Anúncios. */
export default function PricesSection({ competitors, canEdit }: { competitors: BenchmarkCompetitor[]; canEdit: boolean }) {
  const [data, setData] = useState<BenchmarkPrices | null>(null);
  const [url, setUrl] = useState("");
  const [owner, setOwner] = useState("");
  const [catalog, setCatalog] = useState<CatalogItem[] | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(() => getBenchmarkPrices(90).then(setData)
    .catch((cause) => setError(cause instanceof Error ? cause.message : "Não foi possível ler os preços.")), []);
  useEffect(() => { void load(); }, [load]);

  async function run(key: string, fn: () => Promise<string | void>) {
    setBusy(key); setError(""); setNotice("");
    try { const done = await fn(); if (done) setNotice(done); await load(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível concluir."); }
    finally { setBusy(""); }
  }
  const add = (target: string) => run(`add:${target}`, async () => {
    const out = await addBenchmarkProduct({ url: target, competitor_id: owner || null });
    setUrl("");
    return out.error ? `Produto salvo, mas o preço não foi lido: ${out.error}` : `Preço lido: ${brl(out.price)}. Ele será conferido todo dia.`;
  });
  const onSubmit = (event: FormEvent) => { event.preventDefault(); void add(url.trim()); };
  const name = (id: string | null) => (id ? competitors.find((c) => c.id === id)?.name || "Concorrente" : "Sua marca");
  const site = competitors.find((c) => c.id === owner)?.website;

  return (
    <>
      <section className="bmCard" aria-labelledby="bm-prices">
        <div className="bmCardHead">
          <div>
            <h2 id="bm-prices">Preços dos concorrentes</h2>
            <p className="bmSub">O MUGOVERSO lê o preço público da página de cada produto todo dia e mostra quando muda.</p>
          </div>
        </div>
        {error ? <p role="alert" className="studioError">{error}</p> : null}
        {notice ? <p role="status" className="studioNotice">{notice}</p> : null}
        {!data ? <p className="bmMuted">Carregando…</p> : data.products.length === 0 ? (
          <p className="bmEmpty">Nenhum produto monitorado. Cole o link de um produto do concorrente abaixo.</p>
        ) : (
          <div className="bmScroll"><table className="ds-table bmTable">
            <thead><tr><th>Produto</th><th>De quem</th><th className="is-number">Preço</th><th>Últimos 90 dias</th><th>Mudou</th><th /></tr></thead>
            <tbody>{data.products.map((p) => (
              <tr key={p.id} className={p.competitor_id ? "" : "is-brand"}>
                <td className="is-primary"><a className="ds-link" href={p.url} target="_blank" rel="noopener noreferrer">{p.title || p.url} <ArrowUpRight size={13} aria-hidden="true" /></a>
                  <small>{p.error ? `Sem leitura: ${p.error}` : `${p.available === false ? "Esgotado · " : ""}conferido ${p.checked_at ? new Date(p.checked_at).toLocaleString("pt-BR") : "—"}`}</small></td>
                <td>{name(p.competitor_id)}</td>
                <td className="is-number"><b>{brl(p.price)}</b>{p.compare_at ? <small className="bmStrike">{brl(p.compare_at)}</small> : null}</td>
                <td className="bmSparkCell"><Spark points={p.history} /></td>
                <td>{p.change ? <span className={`bmChange ${p.change.to < p.change.from ? "is-down" : "is-up"}`}>
                  {p.change.pct != null ? `${p.change.pct > 0 ? "+" : ""}${p.change.pct.toLocaleString("pt-BR")}%` : ""} em {day(p.change.on)}</span> : <span className="bmMuted">sem mudança</span>}</td>
                <td className="bmRowActions">{canEdit ? <>
                  <button type="button" className="bmRemove" aria-label="Ler o preço agora" title="Ler agora" disabled={!!busy}
                    onClick={() => void run(`check:${p.id}`, async () => { await checkBenchmarkProduct(p.id); })}><RefreshCw size={14} aria-hidden="true" className={busy === `check:${p.id}` ? "bmSpin" : ""} /></button>
                  <button type="button" className="bmRemove" aria-label="Parar de acompanhar" title="Parar de acompanhar" disabled={!!busy}
                    onClick={() => void run(`rm:${p.id}`, async () => { await removeBenchmarkProduct(p.id); return "Produto removido do monitoramento."; })}><X size={14} aria-hidden="true" /></button>
                </> : null}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
        {canEdit ? (
          <form className="bmForm" onSubmit={onSubmit}>
            <h3>Acompanhar um produto</h3>
            <div className="bmGrid">
              <select aria-label="De quem é o produto" value={owner} onChange={(e) => { setOwner(e.target.value); setCatalog(null); }}>
                <option value="">Sua marca (para comparar)</option>
                {competitors.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <input aria-label="Link do produto" placeholder="https://loja.com/products/…" value={url} onChange={(e) => setUrl(e.target.value)} />
            </div>
            <div className="bmFormActions">
              <button className="ds-button is-primary" type="submit" disabled={!!busy || !url.trim()}>{busy.startsWith("add") ? "Lendo o preço…" : "Acompanhar"}</button>
              {site ? <button type="button" className="ds-button" disabled={!!busy}
                onClick={() => void run("catalog", async () => { setCatalog((await getStoreCatalog(site)).products); })}>
                {busy === "catalog" ? "Buscando…" : "Escolher da loja do concorrente"}</button> : null}
            </div>
            {catalog ? <ul className="bmCatalog">{catalog.map((item) => (
              <li key={item.url}>
                {item.image ? <img src={item.image} alt="" loading="lazy" /> : <span className="bmThumb" />}
                <span>{item.title}<small>{brl(item.price)}</small></span>
                <button type="button" className="ds-button" disabled={!!busy || data?.products.some((p) => p.url === item.url)} onClick={() => void add(item.url)}>
                  {data?.products.some((p) => p.url === item.url) ? "Acompanhando" : "Acompanhar"}</button>
              </li>
            ))}</ul> : null}
            <p className="bmFoot">Funciona com lojas Shopify e com qualquer site que publique os dados de produto (o mesmo que o Google lê). Sem preço legível, aparece o motivo; nada é estimado.</p>
          </form>
        ) : null}
      </section>

      <section className="bmCard" aria-labelledby="bm-ads">
        <h2 id="bm-ads">Anúncios dos concorrentes</h2>
        <p className="bmSub">A Meta só libera por API os anúncios comerciais que rodaram na Europa; no Brasil, a consulta é na Biblioteca de Anúncios. Os links abaixo já abrem filtrados em cada concorrente.</p>
        {data?.ad_library.length ? <ul className="bmAdLinks">{data.ad_library.map((a) => (
          <li key={a.competitor_id}><a className="ds-button" href={a.url} target="_blank" rel="noopener noreferrer">{a.name} na Biblioteca de Anúncios <ArrowUpRight size={14} aria-hidden="true" /></a></li>
        ))}</ul> : <p className="bmMuted">Cadastre um concorrente para ver o atalho.</p>}
        <p className="bmFoot">Achou algo relevante? Registre como evidência (categoria Anúncios) com o link, e fica no histórico do benchmarking.</p>
      </section>
    </>
  );
}
