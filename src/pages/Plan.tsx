import { useEffect, useState } from "react";
import { Check, Circle } from "lucide-react";
import { getActiveClientName } from "../app/activeClient";
import { navigateToAppRoute } from "../app/routes";
import { brl, getMyPlan, STATUS_LABEL, type PlanOverview } from "../app/saas";
import PageHeader from "../components/data/PageHeader";
import Shell from "../components/Shell";
import "../styles/saas.css";

const INVOICE_LABEL = { aberta: "Em aberto", paga: "Paga", vencida: "Vencida", cancelada: "Cancelada" } as const;
const month = (p: string) => new Date(`${p}-15T12:00:00`).toLocaleDateString("pt-BR", { month: "long", year: "numeric" });

/** A empresa vê o passo a passo de implantação, o plano, o uso do mês e as faturas. */
export default function Plan() {
  const [data, setData] = useState<PlanOverview | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { getMyPlan().then(setData).catch((cause) => setError(cause instanceof Error ? cause.message : "Não foi possível ler o plano.")); }, []);

  const sub = data?.subscription;
  const steps = data?.onboarding || [];
  const done = steps.filter((s) => s.done).length;
  return (
    <Shell title="Plano" variant="editorial">
      <div className="ds-page saPage">
        <PageHeader company={getActiveClientName()} title="Plano e implantação" dateline={<span>O que falta para a marca usar o MUGOVERSO inteiro, e o uso do plano no mês.</span>} />
        {error ? <p className="saError" role="alert">{error}</p> : null}
        {!data && !error ? <p className="saMuted">Carregando…</p> : null}
        {data ? (
          <>
            <section className="saCard">
              <header className="saHead">
                <h2>Implantação</h2>
                <span className="saProgress"><b>{done}</b> de {steps.length}</span>
              </header>
              <div className="saBar"><span style={{ width: `${steps.length ? (done / steps.length) * 100 : 0}%` }} /></div>
              <ol className="saSteps">
                {steps.map((s) => (
                  <li key={s.key} className={s.done ? "is-done" : ""}>
                    <span className="saCheck" aria-hidden="true">{s.done ? <Check size={14} /> : <Circle size={14} />}</span>
                    <span className="saStepLabel">{s.label}</span>
                    {!s.done ? <button type="button" className="ds-button" onClick={() => { navigateToAppRoute(s.route); window.dispatchEvent(new PopStateEvent("popstate")); }}>Fazer agora</button> : <small>feito</small>}
                  </li>
                ))}
              </ol>
            </section>

            <section className="saCard">
              <header className="saHead">
                <div>
                  <h2>{sub?.plan ? `Plano ${sub.plan.name}` : "Sem plano"}</h2>
                  <p className="saMuted">{sub?.plan ? `${brl(sub.plan.price_month_cents)} por mês · cobrança todo dia ${sub.billing_day}` : "Esta empresa é atendida diretamente pela Mugô, sem limites de uso."}</p>
                </div>
                {sub ? <span className={`saPill is-${sub.status}`}>{STATUS_LABEL[sub.status]}{sub.status === "teste" && sub.trial_ends_at ? ` até ${new Date(sub.trial_ends_at).toLocaleDateString("pt-BR")}` : ""}</span> : null}
              </header>
              <div className="saMeters">
                {data.meters.map((m) => {
                  const pct = m.limit ? Math.min(100, (m.used / m.limit) * 100) : 0;
                  return (
                    <div key={m.key} className={`saMeter${m.remaining === 0 ? " is-full" : pct >= 80 ? " is-warn" : ""}`}>
                      <div className="saMeterHead"><span>{m.label}</span><b>{m.used.toLocaleString("pt-BR")}{m.limit != null ? ` / ${m.limit.toLocaleString("pt-BR")}` : ""}</b></div>
                      {m.limit != null ? <div className="saBar is-thin"><span style={{ width: `${pct}%` }} /></div> : <small className="saMuted">sem limite</small>}
                    </div>
                  );
                })}
              </div>
              {sub?.status === "atrasada" ? <p className="saNotice">Há fatura vencida. O MUGOVERSO segue funcionando; fale com a Mugô para regularizar.</p> : null}
              {sub?.status === "cancelada" ? <p className="saNotice">Assinatura cancelada: envios de e-mail e WhatsApp estão pausados.</p> : null}
            </section>

            {data.invoices.length ? (
              <section className="saCard">
                <h2>Faturas</h2>
                <table className="saTable">
                  <thead><tr><th>Mês</th><th>Valor</th><th>Vencimento</th><th>Situação</th><th /></tr></thead>
                  <tbody>{data.invoices.map((i) => (
                    <tr key={i.id}>
                      <td>{month(i.period)}</td><td>{brl(i.amount_cents)}</td><td>{new Date(`${i.due_date}T12:00:00`).toLocaleDateString("pt-BR")}</td>
                      <td><span className={`saPill is-${i.status}`}>{INVOICE_LABEL[i.status]}</span></td>
                      <td>{i.payment_url && i.status !== "paga" ? <a className="ds-link" href={i.payment_url} target="_blank" rel="noopener noreferrer">Pagar</a> : null}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </section>
            ) : null}
          </>
        ) : null}
      </div>
    </Shell>
  );
}
