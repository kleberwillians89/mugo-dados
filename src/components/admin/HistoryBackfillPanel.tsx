import { useCallback, useEffect, useMemo, useState } from "react";
import {
  cancelHistory,
  getHistoryPlan,
  requestHistory,
  runHistoryRound,
  type HistoryPlan,
  type PlatformCompany,
} from "../../app/api";

/**
 * Histórico desde uma data (ex.: 01/01/2026), só administrador da plataforma.
 *
 * Simular é somente leitura. Agendar registra o pedido; o cron da madrugada
 * baixa em blocos pequenos e retoma de onde parou. Nada é apagado e nenhuma
 * regra de cálculo muda: só preenche o passado que falta no banco.
 */

const DEFAULT_START = "2026-01-01";

const STATE_LABEL: Record<string, string> = {
  complete: "Completo",
  pending: "Faltando",
  not_connected: "Não conectado",
};

type Props = { companies: PlatformCompany[] };

function errorText(cause: unknown, fallback: string) {
  if (cause && typeof cause === "object" && "message" in cause) {
    const message = String((cause as { message?: unknown }).message || "").trim();
    if (message) return message;
  }
  return fallback;
}

function day(value?: string | null) {
  if (!value) return "—";
  const [year, month, dayOfMonth] = value.slice(0, 10).split("-");
  return year && month && dayOfMonth ? `${dayOfMonth}/${month}/${year}` : "—";
}

export default function HistoryBackfillPanel({ companies }: Props) {
  const active = useMemo(() => companies.filter((company) => company.status !== "deleted"), [companies]);
  const [clientId, setClientId] = useState("");
  const [start, setStart] = useState(DEFAULT_START);
  const [plan, setPlan] = useState<HistoryPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [confirming, setConfirming] = useState(false);

  const selected = clientId || active[0]?.id || "";

  const load = useCallback(async () => {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const next = await getHistoryPlan(selected, start);
      setPlan(next.client_id === selected ? next : null);
    } catch (cause) {
      setPlan(null);
      setError(errorText(cause, "Não foi possível simular o histórico."));
    } finally {
      setBusy(false);
    }
  }, [selected, start]);

  useEffect(() => {
    setPlan(null);
    setMessage("");
    setConfirming(false);
  }, [selected]);

  async function act(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
      setMessage(success);
      setConfirming(false);
      const next = await getHistoryPlan(selected, start);
      setPlan(next);
    } catch (cause) {
      setError(errorText(cause, "Não foi possível concluir a operação."));
    } finally {
      setBusy(false);
    }
  }

  const scheduled = Boolean(plan?.request);
  const pending = plan?.providers.some((item) => item.state === "pending") ?? false;

  return (
    <section className="companiesCard" data-testid="history-backfill-panel">
      <div className="companiesListTitle">
        <div>
          <h2>Histórico</h2>
          <p className="companiesCardNote">
            Baixa para o banco o passado que falta de cada integração. Roda de madrugada, em blocos pequenos,
            e continua de onde parou. Nada é apagado e nenhum cálculo muda.
          </p>
        </div>
      </div>

      <form className="originProbeForm" onSubmit={(event) => { event.preventDefault(); void load(); }}>
        <label>Empresa
          <select value={selected} onChange={(event) => setClientId(event.target.value)} disabled={busy}>
            {active.map((company) => (
              <option key={company.id} value={company.id}>{company.trade_name || company.name}</option>
            ))}
          </select>
        </label>
        <label>Buscar desde
          <input type="date" value={start} max={new Date().toISOString().slice(0, 10)}
            onChange={(event) => setStart(event.target.value)} disabled={busy || scheduled} />
        </label>
        <span />
        <button className="btn" type="submit" disabled={busy || !selected}>
          {busy ? "Consultando…" : scheduled ? "Atualizar progresso" : "Simular"}
        </button>
      </form>

      {error ? <p className="companiesError" role="alert">{error}</p> : null}
      {message ? <p className="companiesSuccess" role="status">{message}</p> : null}

      {plan ? (
        <div className="originProbeResult" data-testid="history-plan">
          {scheduled ? (
            <p className="originProbeVerdict">
              Busca agendada desde {day(plan.start)}. O próximo bloco roda na madrugada; você pode adiantar uma rodada agora.
            </p>
          ) : null}
          <div className="companiesTableWrap">
            <table className="companiesTable">
              <thead>
                <tr><th>Fonte</th><th>No banco desde</th><th>Falta buscar</th><th>Progresso</th><th>Situação</th></tr>
              </thead>
              <tbody>
                {plan.providers.map((item) => (
                  <tr key={item.provider}>
                    <td>{item.label}</td>
                    <td>{item.connected ? day(item.earliest_in_database) : "—"}</td>
                    <td>{item.missing_start ? `${day(item.missing_start)} a ${day(item.missing_end)}` : "—"}</td>
                    <td>{item.blocks_total ? `${item.blocks_done} de ${item.blocks_total} blocos` : "—"}</td>
                    <td>{STATE_LABEL[item.state] || item.state}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="companiesCardNote">
            Shopify com mais de 60 dias exige a permissão “todos os pedidos”; se faltar, a fonte aparece parada e é
            preciso reconectar a loja. Meta Ads vai para a fila própria do Meta, que processa a cada 5 minutos.
          </p>

          <div className="companiesActions">
            {!scheduled && pending ? (
              confirming ? (
                <>
                  <button className="btn btnPrimary" type="button" disabled={busy}
                    onClick={() => void act(() => requestHistory(selected, start), "Busca agendada. Ela roda de madrugada, em blocos.")}>
                    Confirmar agendamento
                  </button>
                  <button className="btn" type="button" disabled={busy} onClick={() => setConfirming(false)}>Cancelar</button>
                </>
              ) : (
                <button className="btn btnPrimary" type="button" disabled={busy} onClick={() => setConfirming(true)}>
                  Agendar busca
                </button>
              )
            ) : null}
            {scheduled ? (
              <>
                <button className="btn btnPrimary" type="button" disabled={busy}
                  onClick={() => void act(() => runHistoryRound(selected), "Rodada iniciada em segundo plano (até 4 minutos). Atualize o progresso depois.")}>
                  Rodar uma rodada agora
                </button>
                <button className="btn" type="button" disabled={busy}
                  onClick={() => void act(() => cancelHistory(selected), "Busca cancelada. O que já foi baixado continua no banco.")}>
                  Cancelar busca
                </button>
              </>
            ) : null}
          </div>
          {!scheduled && !pending ? (
            <p className="companiesCardNote">Nada a buscar: o banco já tem os dados desde essa data nas fontes conectadas.</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
