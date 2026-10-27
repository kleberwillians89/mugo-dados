import { useMemo, useState } from "react";
import {
  applyOriginReprocess,
  previewOriginReprocess,
  type OriginReprocessSummary,
  type PlatformCompany,
} from "../../app/api";

/**
 * Recalcula a origem dos pedidos que estão como "Origem não identificada",
 * com o que já está salvo (sem chamar a loja). Hoje a regra nova é o clique do
 * Google Ads (gclid): pedido sem UTM mas com gclid passa a "Google Ads".
 * Procurar só lê; aplicar pede confirmação e nunca mexe em pedido que já
 * tem origem.
 */

type Props = { companies: PlatformCompany[] };

const PROVIDER_LABELS: Record<string, string> = { shopify: "Shopify", fbits: "FBITS/Wake" };
const FOUND_LABELS: Record<string, string> = {
  "paid_search:click_id": "Google Ads (clique de anúncio, sem campanha)",
};

function errorText(cause: unknown, fallback: string) {
  if (cause && typeof cause === "object" && "message" in cause) {
    const message = String((cause as { message?: unknown }).message || "").trim();
    if (message) return message;
  }
  return fallback;
}

function totalFound(summary: OriginReprocessSummary | null) {
  return Object.values(summary?.providers || {}).reduce((sum, item) => sum + (item.origin_found || 0), 0);
}

export default function OriginReprocessPanel({ companies }: Props) {
  const active = useMemo(() => companies.filter((company) => company.status !== "deleted"), [companies]);
  const [clientId, setClientId] = useState("");
  const [summary, setSummary] = useState<OriginReprocessSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const selected = clientId || active[0]?.id || "";
  const found = totalFound(summary);

  async function run(action: () => Promise<OriginReprocessSummary>, done?: (result: OriginReprocessSummary) => string) {
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
    <section className="companiesCard" data-testid="origin-reprocess-panel">
      <div className="companiesListTitle">
        <div>
          <h2>Origem das vendas sem identificação</h2>
          <p className="companiesCardNote">
            Pedidos que chegaram sem UTM, mas com o clique do Google Ads (gclid), passam a contar como Google Ads.
            Só pedidos hoje sem origem são analisados; nada é alterado sem confirmação.
          </p>
        </div>
      </div>
      <div className="companiesActions">
        <select value={selected} disabled={busy} onChange={(event) => { setClientId(event.target.value); setSummary(null); setConfirming(false); }}>
          {active.map((company) => <option key={company.id} value={company.id}>{company.trade_name || company.name}</option>)}
        </select>
        <button className="btn" type="button" disabled={busy || !selected} onClick={() => void run(() => previewOriginReprocess(selected))}>
          {busy ? "Analisando…" : "Analisar pedidos sem origem"}
        </button>
      </div>
      {error ? <p className="companiesError" role="alert">{error}</p> : null}
      {message ? <p className="companiesSuccess" role="status">{message}</p> : null}
      {summary && summary.dry_run ? (
        <div data-testid="origin-reprocess-result">
          {Object.entries(summary.providers).map(([provider, item]) => (
            <p key={provider}>
              <strong>{PROVIDER_LABELS[provider] || provider}:</strong>{" "}
              {item.status === "migration_pending"
                ? "migração de origem ainda não aplicada."
                : `${item.scanned_without_origin || 0} pedido(s) sem origem; ${item.origin_found || 0} com origem encontrada.`}
              {Object.entries(item.by_channel || {}).map(([key, count]) => (
                <span key={key} className="companiesCardNote"> {FOUND_LABELS[key] || key}: {count}.</span>
              ))}
            </p>
          ))}
          {found ? (
            confirming ? (
              <div className="companiesActions">
                <button className="btn btnPrimary" type="button" disabled={busy}
                  onClick={() => void run(() => applyOriginReprocess(selected), (r) => `${totalFound(r)} pedido(s) atualizados com a origem encontrada.`)}>
                  Confirmar atualização
                </button>
                <button className="btn" type="button" disabled={busy} onClick={() => setConfirming(false)}>Cancelar</button>
              </div>
            ) : (
              <button className="btn btnPrimary" type="button" disabled={busy} onClick={() => setConfirming(true)}>Aplicar origem encontrada</button>
            )
          ) : <p>Nenhuma origem nova encontrada nos dados salvos.</p>}
        </div>
      ) : null}
    </section>
  );
}
