import { useEffect, useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getActiveClientName } from "../app/activeClient";
import { getCustomerValue, type CustomerValueResponse } from "../app/api";
import { formatDateTimeSaoPaulo } from "../app/dataFormat";
import ClientsSalesTabs from "../components/data/ClientsSalesTabs";
import PageHeader from "../components/data/PageHeader";
import Shell from "../components/Shell";
import type { AppRoute } from "../app/routes";
import "../styles/customerValue.css";

const MONTH = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const label = (m: string) => `${MONTH[Number(m.slice(5, 7)) - 1]}/${m.slice(2, 4)}`;
const money = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 }));
const MARGIN_KEY = "mugo:ltv-margin";

function readMargin(): number | null {
  try { const v = Number(localStorage.getItem(MARGIN_KEY)); return v >= 1 && v <= 100 ? v : null; } catch { return null; }
}

function heat(value: number | undefined, isFirst: boolean): string {
  if (value == null) return "transparent";
  if (isFirst) return "rgba(0,79,110,.12)";
  const alpha = Math.min(0.85, 0.08 + value / 40);
  return `rgba(0,79,110,${alpha.toFixed(2)})`;
}

/** CRM → LTV e CAC: quanto custa trazer um cliente, quanto ele vale ao longo do tempo e quantos voltam. */
export default function CustomerValue({ canView }: { canView?: (route: AppRoute) => boolean }) {
  const [margin, setMargin] = useState<number | null>(readMargin);
  const [data, setData] = useState<CustomerValueResponse | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<"retencao" | "ltv">("retencao");

  useEffect(() => {
    const controller = new AbortController();
    getCustomerValue(margin, { signal: controller.signal }).then((out) => { if (!controller.signal.aborted) { setData(out); setError(""); } })
      .catch((cause) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Não foi possível ler os indicadores."); });
    return () => controller.abort();
  }, [margin]);

  function changeMargin(value: string) {
    const n = Number(value);
    const next = n >= 1 && n <= 100 ? n : null;
    setMargin(next);
    try { if (next) localStorage.setItem(MARGIN_KEY, String(next)); else localStorage.removeItem(MARGIN_KEY); } catch { /* navegador sem storage */ }
  }

  const s = data?.summary;
  const months = data?.months || [];
  const maxAge = Math.max(0, ...(data?.cohorts || []).map((c) => c.retention.length));
  return (
    <Shell title="CRM" variant="editorial">
      <PageHeader company={getActiveClientName()} title="CRM"
        dateline={<span>Quanto custa trazer um cliente, quanto ele vale e quantos voltam a comprar.</span>} />
      <ClientsSalesTabs current="customer_value" canView={canView} />

      {error ? <p className="cvError" role="alert">{error}</p> : null}
      {!data && !error ? <p className="cvMuted" role="status">Calculando… na primeira vez o MUGOVERSO junta os pedidos e as conversas de cada cliente (pode levar até 1 minuto).</p> : null}
      {data?.status === "not_built" ? (
        <p className="cvEmpty">{data.migration_pending ? "A jornada do cliente ainda não foi ativada nesta empresa." : "Ainda não há pedidos suficientes desta loja para calcular LTV e CAC. Assim que os pedidos entrarem, a conta aparece aqui sozinha."}</p>
      ) : null}

      {data?.status === "ok" && s ? (
        <div className="cvPage">
          <div className="cvControls">
            <label>Margem bruta <input type="number" min={1} max={100} placeholder="—" defaultValue={margin ?? ""} aria-label="Margem bruta em %"
              onBlur={(e) => changeMargin(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") changeMargin((e.target as HTMLInputElement).value); }} /> %</label>
            <small>{margin ? "LTV:CAC e payback usam a margem." : "Sem margem, LTV:CAC e payback usam a receita (fica otimista)."}</small>
          </div>
          <dl className="cvKpis">
            <div><dt>CAC (6 meses)</dt><dd>{money(s.cac_6m)}</dd><small>{data.has_spend ? "gasto Meta + Google ÷ clientes novos" : "sem gasto de mídia no período"}</small></div>
            <div><dt>LTV 180 dias</dt><dd>{money(data.ltv?.["180"])}</dd><small>receita média por cliente</small></div>
            <div className="is-accent"><dt>LTV : CAC</dt><dd>{s.ltv_cac == null ? "—" : `${s.ltv_cac.toLocaleString("pt-BR")}x`}</dd><small>{s.ltv_cac == null ? "falta CAC ou LTV" : s.ltv_cac >= 3 ? "saudável (3x ou mais)" : s.ltv_cac >= 1 ? "paga a aquisição, margem apertada" : "aquisição não se paga em 180 dias"}</small></div>
            <div><dt>Payback</dt><dd>{s.payback_months == null ? "—" : s.payback_months === 0 ? "1º mês" : `${s.payback_months + 1}º mês`}</dd><small>quando a coorte paga o CAC</small></div>
            <div><dt>Recompra</dt><dd>{s.repeat_rate == null ? "—" : `${s.repeat_rate.toLocaleString("pt-BR")}%`}</dd><small>{s.median_days_to_second ? `2ª compra em ~${s.median_days_to_second} dias (mediana)` : "compraram 2 vezes ou mais"}</small></div>
          </dl>

          <section className="cvCard">
            <header className="cvHead">
              <h2>Clientes novos, recorrentes e CAC por mês</h2>
              <ul className="cvLegend" aria-label="Legenda">
                <li><span style={{ background: "#004f6e" }} />Novos</li>
                <li><span style={{ background: "#8fb8c8" }} />Recorrentes</li>
                <li><span className="is-line" style={{ background: "#c76b1e" }} />CAC</li>
              </ul>
            </header>
            <div className="cvChart">
              <ResponsiveContainer width="100%" height={300}>
                <ComposedChart data={months.map((m) => ({ ...m, label: label(m.month) }))} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#ece9e3" vertical={false} />
                  <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={12} />
                  <YAxis yAxisId="n" tickLine={false} axisLine={false} fontSize={12} width={40} />
                  <YAxis yAxisId="cac" orientation="right" tickLine={false} axisLine={false} fontSize={12} width={56} tickFormatter={(v) => `R$${v}`} />
                  <Tooltip formatter={(value, name) => (name === "CAC" ? money(Number(value)) : Number(value).toLocaleString("pt-BR"))} />
                  <Bar yAxisId="n" dataKey="new" name="Novos" stackId="c" fill="#004f6e" isAnimationActive={false} />
                  <Bar yAxisId="n" dataKey="returning" name="Recorrentes" stackId="c" fill="#c98a00" radius={[6, 6, 0, 0]} isAnimationActive={false} />
                  <Line yAxisId="cac" dataKey="cac" name="CAC" stroke="#c76b1e" strokeWidth={2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="cvCard">
            <header className="cvHead">
              <div>
                <h2>Coortes por mês da primeira compra</h2>
                <p className="cvMuted">{view === "retencao" ? "% da coorte que comprou de novo em cada mês depois da primeira compra." : "Receita acumulada por cliente (LTV) mês a mês."}</p>
              </div>
              <div className="ds-segmented" role="group" aria-label="Ver coortes por">
                <button type="button" aria-pressed={view === "retencao"} onClick={() => setView("retencao")}>Retenção</button>
                <button type="button" aria-pressed={view === "ltv"} onClick={() => setView("ltv")}>LTV</button>
              </div>
            </header>
            <div className="cvTableWrap">
              <table className="cvCohorts">
                <thead><tr><th>Coorte</th><th>Clientes</th><th>CAC</th>{Array.from({ length: maxAge }, (_, k) => <th key={k}>{k === 0 ? "Mês 0" : `+${k}`}</th>)}</tr></thead>
                <tbody>
                  {(data.cohorts || []).slice().reverse().map((c) => (
                    <tr key={c.month}>
                      <th scope="row">{label(c.month)}</th>
                      <td>{c.size.toLocaleString("pt-BR")}</td>
                      <td>{money(c.cac)}</td>
                      {Array.from({ length: maxAge }, (_, k) => {
                        const value = view === "retencao" ? c.retention[k] : c.ltv[k];
                        const dark = view === "retencao" && value != null && k > 0 && value >= 18;
                        return (
                          <td key={k} className={dark ? "is-dark" : ""} style={{ background: view === "retencao" ? heat(value, k === 0) : "transparent" }}>
                            {value == null ? "" : view === "retencao" ? `${value.toLocaleString("pt-BR")}%` : money(value)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <dl className="cvKpis is-small">
            {(["30", "90", "180", "365"] as const).map((n) => (
              <div key={n}><dt>LTV {n} dias</dt><dd>{money(data.ltv?.[n])}</dd></div>
            ))}
          </dl>
          <p className="cvMuted">
            Pessoa unificada pela jornada (cadastro, e-mail ou telefone). Dados desde {data.data_since ? formatDateTimeSaoPaulo(data.data_since).split(" ")[0] : "—"};
            quem comprou antes disso pode aparecer como novo nos primeiros meses. CAC misturado: todo o gasto Meta + Google dividido por todos os clientes novos.
            {data.built_at ? ` Jornada montada em ${formatDateTimeSaoPaulo(data.built_at)}.` : ""}
          </p>
        </div>
      ) : null}
    </Shell>
  );
}
