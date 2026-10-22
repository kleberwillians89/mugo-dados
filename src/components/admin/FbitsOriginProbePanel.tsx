import { useMemo, useState } from "react";
import {
  getFbitsOriginProbe,
  type FbitsOriginOrderView,
  type FbitsOriginProbeResult,
  type FbitsOriginSummary,
  type PlatformCompany,
} from "../../app/api";

/**
 * Diagnóstico de origem FBITS (somente leitura, só administrador da plataforma).
 *
 * Lê pedidos recentes na API da Wake e mostra em quais campos a origem
 * (UTM, canal, referência) aparece. O servidor já remove nome, e-mail, CPF,
 * telefone, endereço e pagamento antes de responder; aqui só exibimos
 * contagens, nomes de campos e a origem calculada.
 */

const SOURCE_LABELS: Record<string, string> = {
  utm: "Com UTM (campanha identificada)",
  referrer: "Só site de origem",
  platform: "Só origem registrada pela loja",
  none: "Sem origem",
};

const CHANNEL_LABELS: Record<string, string> = {
  paid_social: "Mídia paga · redes sociais",
  paid_search: "Mídia paga · busca",
  paid_other: "Mídia paga · outros",
  organic_social: "Redes sociais (orgânico)",
  organic_search: "Busca orgânica",
  email: "E-mail",
  sms_whatsapp: "SMS / WhatsApp",
  affiliate: "Afiliados e parceiros",
  referral: "Outros sites",
  marketplace: "Marketplace",
  direct: "Direto",
  unknown: "Origem não identificada",
};

const PERIODS = [7, 14, 30];

type Props = { companies: PlatformCompany[] };

function errorText(cause: unknown, fallback: string) {
  if (cause && typeof cause === "object" && "message" in cause) {
    const message = String((cause as { message?: unknown }).message || "").trim();
    if (message) return message;
  }
  return fallback;
}

function entries(record: Record<string, number> | undefined, labels?: Record<string, string>) {
  return Object.entries(record || {})
    .sort((a, b) => b[1] - a[1])
    .map(([key, count]) => ({ key, label: labels?.[key] || key, count }));
}

function formatDate(value: string | null | undefined) {
  const parsed = value ? new Date(value) : null;
  return parsed && !Number.isNaN(parsed.getTime())
    ? parsed.toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "short" })
    : "—";
}

function SummaryBlock({ title, summary }: { title: string; summary: FbitsOriginSummary }) {
  const fields = [
    ...entries(summary.campos_no_topo_encontrados),
    ...entries(summary.metadados_de_origem_encontrados),
    ...entries(summary.outros_campos),
  ];
  return (
    <div className="originProbeBlock">
      <h3>{title}</h3>
      <p className="originProbeVerdict">{summary.veredito}</p>
      <div className="originProbeGrid">
        <div>
          <span className="originProbeLabel">Pedidos analisados</span>
          <strong>{summary.pedidos_analisados}</strong>
        </div>
        <div>
          <span className="originProbeLabel">Tipo de origem</span>
          <ul>
            {entries(summary.origem_por_tipo, SOURCE_LABELS).map((row) => (
              <li key={row.key}><span>{row.label}</span><strong>{row.count}</strong></li>
            ))}
          </ul>
        </div>
        <div>
          <span className="originProbeLabel">Canal calculado</span>
          <ul>
            {entries(summary.canal_calculado, CHANNEL_LABELS).map((row) => (
              <li key={row.key}><span>{row.label}</span><strong>{row.count}</strong></li>
            ))}
          </ul>
        </div>
      </div>
      <div>
        <span className="originProbeLabel">Campos de origem encontrados na API</span>
        {fields.length ? (
          <div className="originProbeChips">
            {fields.map((row) => <code key={row.key}>{row.key} · {row.count}</code>)}
          </div>
        ) : (
          <p className="companiesCardNote">Nenhum campo de origem apareceu nesses pedidos.</p>
        )}
      </div>
    </div>
  );
}

function OrdersTable({ orders }: { orders: FbitsOriginOrderView[] }) {
  if (!orders.length) return null;
  return (
    <div className="companiesTableWrap">
      <table className="companiesTable" data-testid="origin-probe-orders">
        <thead>
          <tr><th>Pedido</th><th>Data</th><th>Origem</th><th>Canal</th><th>Campanha</th></tr>
        </thead>
        <tbody>
          {orders.map((order, index) => {
            const origin = order.origem_calculada_pelo_mugo || {};
            const campaign = origin.utm_campaign || origin.origin_detail || "—";
            return (
              <tr key={`${order.pedidoId ?? "x"}-${index}`}>
                <td>{order.pedidoId ?? "—"}</td>
                <td>{formatDate(order.data)}</td>
                <td>{SOURCE_LABELS[origin.attribution_source || "none"] || origin.attribution_source}</td>
                <td>{CHANNEL_LABELS[origin.origin_channel || "unknown"] || origin.origin_channel}</td>
                <td>{campaign}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function FbitsOriginProbePanel({ companies }: Props) {
  const active = useMemo(() => companies.filter((company) => company.status !== "deleted"), [companies]);
  const [clientId, setClientId] = useState("");
  const [days, setDays] = useState(14);
  const [orderId, setOrderId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<FbitsOriginProbeResult | null>(null);
  const [copied, setCopied] = useState(false);

  const selected = clientId || active[0]?.id || "";

  async function run() {
    if (!selected) return;
    const order = orderId.trim();
    if (order && !/^\d+$/.test(order)) {
      setError("Informe apenas o número do pedido.");
      return;
    }
    setBusy(true);
    setError("");
    setResult(null);
    setCopied(false);
    try {
      setResult(await getFbitsOriginProbe(selected, { days, orderId: order }));
    } catch (cause) {
      setError(errorText(cause, "Não foi possível rodar o diagnóstico."));
    } finally {
      setBusy(false);
    }
  }

  async function copySummary() {
    if (!result || !result.ok) return;
    // Só os resumos: contagens e nomes de campos, sem pedidos.
    const text = JSON.stringify({ resumo_lista: result.resumo_lista, resumo_detalhe: result.resumo_detalhe }, null, 2);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setError("Não foi possível copiar. Selecione o texto do veredito manualmente.");
    }
  }

  const ok = result && result.ok ? result : null;
  const orders = ok ? (ok.pedidos_detalhe.length ? ok.pedidos_detalhe : ok.pedidos_lista) : [];

  return (
    <section className="companiesCard" data-testid="fbits-origin-probe-panel">
      <div className="companiesListTitle">
        <div>
          <h2>Origem das vendas · FBITS</h2>
          <p className="companiesCardNote">
            Confere na API da Wake se cada pedido traz a campanha (UTM), o site de origem ou o canal
            da loja. Somente leitura: nada é gravado e nenhum dado pessoal de comprador é exibido.
          </p>
        </div>
      </div>

      <form
        className="originProbeForm"
        onSubmit={(event) => { event.preventDefault(); void run(); }}
      >
        <label>Empresa
          <select value={selected} onChange={(event) => setClientId(event.target.value)} disabled={busy}>
            {active.map((company) => (
              <option key={company.id} value={company.id}>{company.trade_name || company.name}</option>
            ))}
          </select>
        </label>
        <label>Período
          <select value={days} onChange={(event) => setDays(Number(event.target.value))} disabled={busy}>
            {PERIODS.map((value) => <option key={value} value={value}>Últimos {value} dias</option>)}
          </select>
        </label>
        <label>Pedido específico (opcional)
          <input
            value={orderId}
            inputMode="numeric"
            placeholder="Número do pedido"
            onChange={(event) => setOrderId(event.target.value)}
            disabled={busy}
          />
        </label>
        <button className="btn btnPrimary" type="submit" disabled={busy || !selected}>
          {busy ? "Consultando a FBITS…" : "Rodar diagnóstico"}
        </button>
      </form>

      {error ? <p className="companiesError" role="alert">{error}</p> : null}
      {result && !result.ok ? (
        <p className="companiesError" role="alert">{result.message || "A FBITS recusou a consulta."}</p>
      ) : null}

      {ok ? (
        <div className="originProbeResult" data-testid="origin-probe-result">
          {ok.resumo_detalhe ? <SummaryBlock title="Pedidos abertos um a um" summary={ok.resumo_detalhe} /> : null}
          {ok.resumo_lista ? <SummaryBlock title="Lista de pedidos do período" summary={ok.resumo_lista} /> : null}
          <OrdersTable orders={orders} />
          <div className="companiesActions">
            <button className="btn" type="button" onClick={() => void copySummary()}>
              {copied ? "Resumo copiado" : "Copiar resumo"}
            </button>
            {typeof ok.requisicoes_feitas === "number" ? (
              <span className="companiesCardNote">{ok.requisicoes_feitas} consultas à API da Wake.</span>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
