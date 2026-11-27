import { useCallback, useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { getLiveRead, type LiveRead, type LiveReadNumbers } from "../../app/metaAds";

const VERDICT: Record<string, { label: string; tone: string }> = {
  escalar: { label: "Escalar", tone: "is-positive" }, manter: { label: "Manter", tone: "is-neutral" },
  ajustar: { label: "Ajustar", tone: "is-warning" }, pausar: { label: "Pausar", tone: "is-negative" },
};
const brl = (n: number | null | undefined) => n == null ? "—" : n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const int = (n: number | null | undefined) => n == null ? "—" : Math.round(n).toLocaleString("pt-BR");
const dec = (n: number | null | undefined, digits: number, suffix = "") => n == null ? "—"
  : `${n.toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits })}${suffix}`;

/** Os números que importam para o objetivo de cada campanha (o mesmo critério que a IA usa). */
function keyNumbers(objective: string, n: LiveReadNumbers): [string, string][] {
  const base: [string, string][] = [["Investido", brl(n.investido)]];
  if (objective === "Google Ads") return [...base, ["Conversões", dec(n.conversoes, 0)], ["Custo por conversão", brl(n.custo_por_conversao)],
    ["ROAS", dec(n.roas, 2)], ["CPC", brl(n.cpc)]];
  if (objective === "Alcance") return [...base, ["Pessoas alcançadas", int(n.alcance)], ["CPM", brl(n.cpm)], ["Frequência", dec(n.frequencia, 1)]];
  if (objective === "Tráfego para o site") return [...base, ["Cliques no link", int(n.cliques_no_link)], ["Custo por clique", brl(n.cpc_link)], ["CTR do link", dec(n.ctr_link_pct, 2, "%")]];
  if (n.roas !== undefined || n.compras !== undefined) return [...base, ["Compras", int(n.compras)], ["Vendido", brl(n.valor_de_compras)], ["ROAS", dec(n.roas, 2)]];
  return [...base, ["Resultados", int(n.resultados)], ["Custo por resultado", brl(n.custo_por_resultado)], ["CTR do link", dec(n.ctr_link_pct, 2, "%")]];
}

/** Leitura da IA das campanhas no ar: todas as ativas da Meta (ao vivo) e do Google (sincronização diária). */
export default function MediaLiveRead({ onData }: { onData?: (data: LiveRead) => void }) {
  const [data, setData] = useState<LiveRead | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (refresh: boolean) => {
    setBusy(true); setError(null);
    try { const read = await getLiveRead(refresh); setData(read); onData?.(read); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível ler as campanhas agora."); }
    finally { setBusy(false); }
  }, [onData]);
  useEffect(() => { void load(false); }, [load]);

  return <section className="studioCard mediaLiveRead" aria-labelledby="media-live-read" data-testid="media-live-read">
    <div className="ds-sectionHead"><div className="ds-sectionHeadText">
      <h2 id="media-live-read" className="ds-sectionTitle"><Sparkles size={18} aria-hidden="true" /> Leitura da IA · campanhas no ar</h2>
      <p className="ds-caption">Todas as campanhas ativas: Meta ao vivo e Google pela última sincronização. Cada uma é julgada pelo objetivo
        dela: alcance por CPM e frequência, tráfego por custo do clique, vendas por ROAS.{data?.checked_at ? ` Lido às ${new Date(data.checked_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}.` : ""}</p>
    </div>
      <button type="button" className="ds-button" disabled={busy} onClick={() => void load(true)}>{busy ? "Lendo as campanhas…" : "Atualizar leitura"}</button>
    </div>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {busy && !data ? <p className="libHint" role="status">A IA está lendo as campanhas da Meta e do Google…</p> : null}
    {data?.message ? <p className="libHint">{data.message}</p> : null}
    {data?.resumo ? <p className="mediaLiveReadSummary">{data.resumo}</p> : null}
    {data?.campanhas.length ? <div className="mediaLiveReadGrid">{data.campanhas.map((c) => {
      const verdict = VERDICT[c.veredito] || VERDICT.manter;
      return <article key={c.id} className="mediaLiveReadCard" data-campaign={c.id}>
        <header><span className={`mediaVerdict ${verdict.tone}`}>{verdict.label}</span><b>{c.campanha}</b>
          <small>{c.canal && c.canal !== "Meta" ? `${c.canal} · ` : c.canal ? "Meta · " : ""}{c.objetivo === "Google Ads" ? "Pesquisa, PMax ou Shopping" : c.objetivo}</small></header>
        <dl>{keyNumbers(c.objetivo, c.numeros).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
        <p>{c.leitura}</p>
        <p><strong>Ação:</strong> {c.acao}</p>
        {c.sinais.length ? <ul className="mediaLiveReadSignals">{c.sinais.map((s) => <li key={s}>{s}</li>)}</ul> : null}
      </article>;
    })}</div> : null}
    {data?.proximos_passos.length ? <><h3>Próximos passos</h3><ol>{data.proximos_passos.map((p) => <li key={p}>{p}</li>)}</ol></> : null}
  </section>;
}
