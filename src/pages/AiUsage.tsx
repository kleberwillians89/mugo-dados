import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import { errorLabel, featureLabel, getAiUsage, type AiUsageReport } from "../app/aiUsage";
import "../styles/studio.css";

const pad = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const int = (n: number) => n.toLocaleString("pt-BR");
const usd = (n: number) => `US$ ${n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: n < 1 ? 4 : 2 })}`;
const when = (value: string | null | undefined) => value ? new Date(value).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";

type Period = "mes" | "7d" | "30d" | "mes_passado";
const PERIOD_LABEL: Record<Period, string> = { mes: "Este mês", "7d": "Últimos 7 dias", "30d": "Últimos 30 dias", mes_passado: "Mês passado" };

function range(period: Period, today = new Date()): { start: string; end: string } {
  if (period === "7d") return { start: iso(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 6)), end: iso(today) };
  if (period === "30d") return { start: iso(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 29)), end: iso(today) };
  if (period === "mes_passado") return { start: iso(new Date(today.getFullYear(), today.getMonth() - 1, 1)), end: iso(new Date(today.getFullYear(), today.getMonth(), 0)) };
  return { start: iso(new Date(today.getFullYear(), today.getMonth(), 1)), end: iso(today) };
}

/** Administração → Consumo de IA: tokens e custo estimado da OpenAI por cliente e por recurso. Só a equipe Mugô. */
export default function AiUsage() {
  const [period, setPeriod] = useState<Period>("mes");
  const [data, setData] = useState<AiUsageReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try { const { start, end } = range(period); setData(await getAiUsage(start, end)); }
    catch (cause) { setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível carregar o consumo."); }
    finally { setLoading(false); }
  }, [period]);
  useEffect(() => { void load(); }, [load]);

  const maxDay = useMemo(() => Math.max(1, ...(data?.daily || []).map((d) => d.total_tokens)), [data]);
  const total = data?.totals.total_tokens || 0;

  return <Shell title="Consumo de IA" variant="editorial"><div className="ds-page studioPage aiUsage">
    <PageHeader company="Mugô" title="Consumo de IA" controls={<div className="studioTabs" role="tablist" aria-label="Período">
      {(Object.keys(PERIOD_LABEL) as Period[]).map((p) => <button key={p} type="button" role="tab" aria-selected={period === p} className={period === p ? "is-active" : ""} onClick={() => setPeriod(p)}>{PERIOD_LABEL[p]}</button>)}
    </div>} />
    <p className="libHint">Tokens que cada cliente gastou com a IA (OpenAI) no Mugoverso: Matriz, Redação, Calendário, Campanhas, Inteligência e demais. O custo é <b>estimado</b> pela tabela de preços da OpenAI; a fatura oficial fica em platform.openai.com → Usage.</p>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {loading && !data ? <p>Carregando…</p> : null}
    {data?.quota_exhausted ? <div className="aiUsageAlert" role="alert"><b>A OpenAI está sem crédito.</b> A última chamada ({when(data.last_error?.at)}, {data.last_error?.client}) voltou "{errorLabel(data.last_error?.code)}". Recarregue em platform.openai.com → Billing; a IA volta a funcionar na hora.</div>
      : data?.last_error ? <p className="clipWarn">Último erro da IA: {errorLabel(data.last_error.code)} · {data.last_error.client} · {featureLabel(data.last_error.feature || "")} · {when(data.last_error.at)}</p> : null}

    {data ? <>
      <div className="aiUsageKpis">
        <div><small>Tokens no período</small><b>{int(total)}</b><span>{int(data.totals.input_tokens)} entrada · {int(data.totals.output_tokens)} saída</span></div>
        <div><small>Custo estimado</small><b>{usd(data.totals.cost_usd)}</b><span>{data.period.start.split("-").reverse().join("/")} a {data.period.end.split("-").reverse().join("/")}</span></div>
        <div><small>Chamadas à IA</small><b>{int(data.totals.calls)}</b><span>{data.totals.errors ? `${int(data.totals.errors)} com erro` : "nenhuma com erro"}</span></div>
        <div><small>Clientes que usaram</small><b>{data.clients.filter((c) => c.client_id).length}</b><span>{data.clients.find((c) => !c.client_id) ? "+ tarefas internas" : " "}</span></div>
      </div>

      <section className="aiUsageCard" aria-label="Consumo por cliente">
        <h3>Por cliente</h3>
        {!data.clients.length ? <p className="libHint">Nenhuma chamada à IA registrada neste período. O registro começou com esta versão: chamadas anteriores não aparecem.</p> : null}
        {data.clients.length ? <div className="matrixGridWrap"><table className="aiUsageTable">
          <thead><tr><th scope="col">Cliente</th><th scope="col">Chamadas</th><th scope="col">Tokens</th><th scope="col">% do total</th><th scope="col">Custo est.</th><th scope="col">Última chamada</th><th scope="col">Último erro</th></tr></thead>
          <tbody>{data.clients.map((c) => {
            const key = c.client_id || "_";
            const share = total ? Math.round((c.total_tokens / total) * 1000) / 10 : 0;
            return <Fragment key={key}><tr>
              <th scope="row"><button type="button" className="studioLink" aria-expanded={open === key} onClick={() => setOpen(open === key ? null : key)}>{open === key ? "▾" : "▸"} {c.name}</button></th>
              <td>{int(c.calls)}</td>
              <td title={`${int(c.input_tokens)} entrada · ${int(c.output_tokens)} saída`}>{int(c.total_tokens)}</td>
              <td><span className="aiUsageShare"><span style={{ width: `${share}%` }} /></span>{share.toLocaleString("pt-BR")}%</td>
              <td>{usd(c.cost_usd)}</td>
              <td>{when(c.last_call)}</td>
              <td>{c.last_error ? <span className="clipWarn">{errorLabel(c.last_error.code)} · {when(c.last_error.at)}</span> : "—"}</td>
            </tr>
            {open === key ? c.features.map((f) => <tr key={`${key}:${f.feature}`} className="aiUsageSub">
              <th scope="row">{featureLabel(f.feature)}</th><td>{int(f.calls)}{f.errors ? ` (${f.errors} erro)` : ""}</td><td>{int(f.total_tokens)}</td><td /><td>{usd(f.cost_usd)}</td><td /><td />
            </tr>) : null}</Fragment>;
          })}</tbody>
        </table></div> : null}
      </section>

      <div className="aiUsageTwo">
        <section className="aiUsageCard" aria-label="Consumo por recurso">
          <h3>Por recurso</h3>
          <ul className="aiUsageList">{data.features.map((f) => <li key={f.feature}><span>{featureLabel(f.feature)}</span><b>{int(f.total_tokens)}</b><small>{usd(f.cost_usd)}</small></li>)}</ul>
        </section>
        <section className="aiUsageCard" aria-label="Consumo por dia">
          <h3>Por dia</h3>
          <ul className="aiUsageDays">{data.daily.map((d) => <li key={d.date} title={`${int(d.total_tokens)} tokens · ${usd(d.cost_usd)}`}>
            <span>{d.date.slice(8, 10)}/{d.date.slice(5, 7)}</span><span className="aiUsageBar"><span style={{ width: `${(d.total_tokens / maxDay) * 100}%` }} /></span><b>{int(d.total_tokens)}</b></li>)}</ul>
        </section>
      </div>
      {data.unpriced_models.length ? <p className="libHint">Sem preço na tabela (custo não estimado): {data.unpriced_models.join(", ")}.</p> : null}
    </> : null}
  </div></Shell>;
}
