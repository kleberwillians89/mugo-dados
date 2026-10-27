import { useMemo, useState } from "react";
import { cleanupTestOrders, previewTestOrders, type PlatformCompany, type TestOrdersSummary } from "../../app/api";

/**
 * Pedidos de teste (R$ 0 com cupom de 100%, tag "teste" ou teste da Shopify)
 * não são venda. Os novos já não são gravados; aqui saem os antigos.
 * Procurar só lê; remover pede confirmação e recalcula os dias afetados.
 */

type Props = { companies: PlatformCompany[] };

function errorText(cause: unknown, fallback: string) {
  if (cause && typeof cause === "object" && "message" in cause) {
    const message = String((cause as { message?: unknown }).message || "").trim();
    if (message) return message;
  }
  return fallback;
}

export default function TestOrdersPanel({ companies }: Props) {
  const active = useMemo(() => companies.filter((company) => company.status !== "deleted"), [companies]);
  const [clientId, setClientId] = useState("");
  const [summary, setSummary] = useState<TestOrdersSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const selected = clientId || active[0]?.id || "";
  const total = summary ? summary.shopify_test_orders + summary.fbits_test_orders : 0;

  async function run(action: () => Promise<TestOrdersSummary>, done?: (result: TestOrdersSummary) => string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await action();
      setSummary(result);
      setConfirming(false);
      if (done) setMessage(done(result));
    } catch (cause) {
      setError(errorText(cause, "Não foi possível concluir a operação."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="companiesCard" data-testid="test-orders-panel">
      <div className="companiesListTitle">
        <div>
          <h2>Pedidos de teste</h2>
          <p className="companiesCardNote">
            Pedido a R$ 0 com cupom de 100%, com a tag “teste” ou marcado como teste pela Shopify não é venda.
            Os novos já não entram no painel; aqui você remove os que já estavam gravados.
          </p>
        </div>
      </div>
      <div className="companiesActions">
        <select value={selected} disabled={busy} onChange={(event) => { setClientId(event.target.value); setSummary(null); setConfirming(false); }}>
          {active.map((company) => <option key={company.id} value={company.id}>{company.trade_name || company.name}</option>)}
        </select>
        <button className="btn" type="button" disabled={busy || !selected} onClick={() => void run(() => previewTestOrders(selected))}>
          {busy ? "Procurando…" : "Procurar pedidos de teste"}
        </button>
      </div>
      {error ? <p className="companiesError" role="alert">{error}</p> : null}
      {message ? <p className="companiesSuccess" role="status">{message}</p> : null}
      {summary && summary.dry_run ? (
        <div data-testid="test-orders-result">
          <p>
            {total
              ? `${total} pedido(s) de teste encontrados (Shopify: ${summary.shopify_test_orders}, FBITS: ${summary.fbits_test_orders}), em ${summary.days.length} dia(s).`
              : "Nenhum pedido de teste gravado para esta empresa."}
          </p>
          {total ? (
            confirming ? (
              <div className="companiesActions">
                <button className="btn btnPrimary" type="button" disabled={busy}
                  onClick={() => void run(() => cleanupTestOrders(selected), (r) => `${r.shopify_test_orders + r.fbits_test_orders} pedido(s) de teste removido(s); indicadores recalculados.`)}>
                  Confirmar remoção
                </button>
                <button className="btn" type="button" disabled={busy} onClick={() => setConfirming(false)}>Cancelar</button>
              </div>
            ) : (
              <button className="btn btnPrimary" type="button" disabled={busy} onClick={() => setConfirming(true)}>Remover do painel</button>
            )
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
