import { useState } from "react";
import { Gauge } from "lucide-react";
import Drawer from "../Drawer";
import { USD_BRL, errorLabel, featureLabel, formatBrl, formatTokens, formatUsd, getClientAiUsage, type ClientAiUsage, type UsageBucket } from "../../app/aiUsage";

/** "Consumo da IA" da empresa ativa (modelo do CRM Ruah): tokens e custo de hoje, do mês, por dia e por recurso. */
export default function AiUsageButton({ clientName, isAgency = false }: { clientName: string; isAgency?: boolean }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<ClientAiUsage | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function start() {
    setOpen(true); setLoading(true); setError("");
    try { setData(await getClientAiUsage()); }
    catch (cause) { setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível carregar o consumo da IA."); }
    finally { setLoading(false); }
  }

  const max = Math.max(...(data?.days || []).map((d) => d.cost_usd), 0.000001);
  const tile = (label: string, b: UsageBucket, unit = true) => <div className="aiUsageTile">
    <span>{label}</span>
    <strong>{formatUsd(b.cost_usd)}</strong>
    <small>≈ {formatBrl(b.cost_usd)}{unit ? ` · ${b.calls} ${b.calls === 1 ? "chamada" : "chamadas"}` : ""}</small>
    <small>{formatTokens(b.input_tokens)} tokens lidos · {formatTokens(b.output_tokens)} escritos</small>
  </div>;

  return <>
    <button type="button" className="ds-button aiUsageButton" onClick={() => void start()}><Gauge size={15} aria-hidden="true" /> Consumo da IA</button>
    <Drawer open={open} width="lg" title="Consumo da IA" description={`Quanto ${clientName} gastou de IA (tokens e custo estimado).`} onClose={() => setOpen(false)}>
      <div className="aiUsage">
        {error ? <div className="ds-notice is-negative" role="alert"><p className="ds-noticeTitle">{error}</p></div> : null}
        {loading || !data ? (!error ? <p className="aiUsageHint">Carregando…</p> : null) : <>
          <div className="aiUsageTiles">
            {tile("Hoje", data.today)}
            {tile("Este mês", data.month)}
            {tile("Média por chamada", data.per_call, false)}
          </div>
          {data.month.errors ? <p className="aiUsageHint is-warning">{data.month.errors} chamada(s) com erro este mês{data.last_error ? ` · última: ${errorLabel(data.last_error.code)}` : ""}.</p> : null}
          <h4>Últimos 30 dias</h4>
          {data.days.length ? <ul className="aiUsageDays">{data.days.map((d) => <li key={d.day} title={`${d.calls} chamadas · ${formatTokens(d.total_tokens)} tokens`}>
            <span>{new Date(`${d.day}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })}</span>
            <i style={{ width: `${Math.max(2, (100 * d.cost_usd) / max)}%` }} />
            <b>{formatUsd(d.cost_usd)}</b>
          </li>)}</ul> : <p className="aiUsageHint">Ainda sem uso de IA registrado para esta empresa.</p>}
          {data.features.length ? <>
            <h4>O que mais consumiu no mês</h4>
            <table className="aiUsageTable"><thead><tr><th>Recurso</th><th>Chamadas</th><th>Tokens</th><th>Custo</th></tr></thead>
              <tbody>{data.features.map((f) => <tr key={f.feature}><td>{featureLabel(f.feature)}</td><td>{f.calls}</td><td>{formatTokens(f.total_tokens)}</td><td>{formatUsd(f.cost_usd)}</td></tr>)}</tbody></table>
          </> : null}
          <p className="aiUsageHint">Custo estimado pelo preço de tabela da OpenAI (US$); em reais com câmbio de referência R$ {USD_BRL.toFixed(2).replace(".", ",")}. {isAgency ? " O valor cobrado de fato aparece na fatura da OpenAI. A visão de todos os clientes fica em Administração → Consumo de IA." : ""}</p>
        </>}
      </div>
    </Drawer>
  </>;
}
