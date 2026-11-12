import { useCallback, useEffect, useRef, useState } from "react";
import {
  getCustomerJourney,
  rebuildCustomerJourney,
  type CustomerJourneyResponse,
  type JourneyEvent,
} from "../../app/api";
import { formatDateTimeSaoPaulo } from "../../app/dataFormat";
import "../../styles/customerJourney.css";

const KIND_LABEL: Record<JourneyEvent["kind"], string> = {
  conversa_whatsapp: "Conversa no WhatsApp",
  pedido: "Primeira compra",
  recompra: "Recompra",
  pedido_cancelado: "Pedido cancelado",
  carrinho_abandonado: "Carrinho abandonado",
  mensagem_enviada: "Mensagem enviada",
  carrinho_recuperado: "Carrinho recuperado",
};

const CHANNEL_LABEL: Record<string, string> = {
  meta_ads: "Meta Ads",
  google_ads: "Google Ads",
  whatsapp: "WhatsApp",
  organic: "Orgânico",
  direct: "Direto",
  email: "E-mail",
  referral: "Indicação",
  instagram: "Instagram",
};

const IDENTITY_LABEL: Record<string, string> = {
  external_id: "cadastro da loja",
  email_hash: "e-mail",
  phone_key: "telefone",
};

function money(value: number | null | undefined): string {
  return Number(value || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function channelName(channel: string | null): string | null {
  if (!channel || channel === "unknown") return null;
  return CHANNEL_LABEL[channel] || channel.replace(/_/g, " ");
}

function eventLine(event: JourneyEvent): string {
  const detail = event.detail || {};
  const parts: string[] = [];
  if (event.kind === "conversa_whatsapp") {
    const origem = typeof detail.origem === "string" ? detail.origem : null;
    if (origem) parts.push(origem);
    if (event.campaign) parts.push(`anúncio “${event.campaign}”`);
  } else {
    if (typeof detail.pedido === "string") parts.push(`Pedido ${detail.pedido}`);
    if (event.value != null) parts.push(money(event.value));
    const channel = channelName(event.channel);
    if (channel) parts.push(`via ${channel}`);
    if (event.campaign) parts.push(`campanha ${event.campaign}`);
  }
  return parts.join(" · ");
}

function evidenceNote(event: JourneyEvent): string | null {
  const after = (event.detail || {}).depois_da_conversa as { em?: string } | undefined;
  if (event.evidence === "regra") return "Ligado à conversa pela regra: mesmo telefone, compra até 7 dias depois.";
  if (after?.em) return "Comprou até 7 dias depois de uma conversa no WhatsApp.";
  return null;
}

export default function CustomerJourney({ customerId, canRebuild }: { customerId: string; canRebuild: boolean }) {
  const [data, setData] = useState<CustomerJourneyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [building, setBuilding] = useState(false);
  const generation = useRef(0);

  const load = useCallback(async (signal?: AbortSignal) => {
    const request = ++generation.current;
    setLoading(true);
    setError("");
    try {
      const payload = await getCustomerJourney(customerId, { signal });
      if (request === generation.current && !signal?.aborted) setData(payload);
    } catch (err) {
      if (request === generation.current && !signal?.aborted) {
        setError(err instanceof Error ? err.message : "A jornada não pôde ser lida agora.");
      }
    } finally {
      if (request === generation.current && !signal?.aborted) setLoading(false);
    }
  }, [customerId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function rebuild() {
    setBuilding(true);
    setError("");
    try {
      await rebuildCustomerJourney();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "A jornada não pôde ser montada agora.");
    } finally {
      setBuilding(false);
    }
  }

  const rebuildButton = canRebuild ? (
    <button type="button" className="ds-button journeyRebuild" onClick={() => void rebuild()} disabled={building}>
      {building ? "Montando…" : data?.built_at ? "Atualizar jornada" : "Montar jornada"}
    </button>
  ) : null;

  const events = [...(data?.events || [])].reverse();
  const summary = data?.summary;

  return (
    <section className="journey" aria-label="Jornada do cliente">
      <header className="journeyHead">
        <div>
          <h3 className="customerDetailHeading">Jornada</h3>
          <p className="journeyLead">
            Do primeiro contato à recompra. Só ligações confirmadas: mesmo cadastro, e-mail ou telefone.
          </p>
        </div>
        {rebuildButton}
      </header>

      {error ? <p className="journeyError" role="alert">{error}</p> : null}
      {loading && !data ? <p className="customerEmpty" role="status">Carregando jornada…</p> : null}

      {data && data.status === "not_built" ? (
        <p className="journeyEmpty">
          {data.migration_pending
            ? "A jornada ainda não foi ativada nesta empresa."
            : "A jornada desta empresa ainda não foi montada."}
          {canRebuild && !data.migration_pending ? " Use “Montar jornada” para juntar pedidos e conversas." : ""}
        </p>
      ) : null}
      {data && data.status === "not_found" ? (
        <p className="journeyEmpty">Este cliente ainda não aparece na última montagem. Atualize a jornada para incluir.</p>
      ) : null}

      {data && data.status === "ok" && summary ? (
        <>
          <dl className="journeyStats">
            <div><dt>Compras</dt><dd>{summary.purchases}</dd></div>
            <div><dt>Receita</dt><dd>{money(summary.revenue)}</dd></div>
            <div>
              <dt>Até a 1ª compra</dt>
              <dd>{summary.days_to_first_purchase == null ? "—" : summary.days_to_first_purchase === 0 ? "No mesmo dia" : `${summary.days_to_first_purchase} dias`}</dd>
            </div>
            <div>
              <dt>Canais</dt>
              <dd>{summary.channels.map(channelName).filter(Boolean).join(", ") || "Sem origem registrada"}</dd>
            </div>
          </dl>

          <ol className="journeyTimeline">
            {events.map((event) => {
              const note = evidenceNote(event);
              return (
                <li key={event.event_key} className={`journeyEvent is-${event.kind}`}>
                  <span className="journeyDot" aria-hidden="true" />
                  <div className="journeyBody">
                    <div className="journeyTitle">
                      <strong>{KIND_LABEL[event.kind] || event.kind}</strong>
                      <time dateTime={event.at}>{formatDateTimeSaoPaulo(event.at)}</time>
                    </div>
                    {eventLine(event) ? <p className="journeyLine">{eventLine(event)}</p> : null}
                    {note ? <p className={`journeyEvidence is-${event.evidence}`}>{note}</p> : null}
                  </div>
                </li>
              );
            })}
          </ol>

          {data.identities && data.identities.length > 1 ? (
            <p className="journeyFoot">
              Unido por {data.identities.map((k) => IDENTITY_LABEL[k] || k).join(" + ")}.
              {data.built_at ? ` Montada em ${formatDateTimeSaoPaulo(data.built_at)}.` : ""}
            </p>
          ) : data.built_at ? (
            <p className="journeyFoot">Montada em {formatDateTimeSaoPaulo(data.built_at)}.</p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
