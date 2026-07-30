import type { ShopifyTechnicalSummary } from "../../app/types";
import {
  formatShopifyDateTime,
  getShopifyStatusTone,
  getShopifyWebhookStatusLabel,
} from "../../app/shopifyUi";

type Props = {
  technical: ShopifyTechnicalSummary;
};

export default function ShopifyWebhookStatusCard({ technical }: Props) {
  return (
    <article className="shopifyTechnicalCard">
      <div className="shopifyListHead">
        <div>
          <div className="shopifyMiniLabel">Status técnico</div>
          <p className="shopifyChartDescription">
            Bloco de apoio para conferência rápida dos webhooks e da última atividade de processamento.
          </p>
        </div>
      </div>

      <div className="shopifyTechnicalStats">
        <div className="shopifyTechnicalStat">
          <span>Último processamento</span>
          <strong>{formatShopifyDateTime(technical.last_success_at)}</strong>
        </div>
        <div className="shopifyTechnicalStat">
          <span>Último recebimento</span>
          <strong>{formatShopifyDateTime(technical.last_received_at)}</strong>
        </div>
        <div className="shopifyTechnicalStat">
          <span>Webhooks processados</span>
          <strong>{technical.processed_count}</strong>
        </div>
        <div className="shopifyTechnicalStat">
          <span>Erros recentes</span>
          <strong>{technical.error_count}</strong>
        </div>
      </div>

      {technical.recent_webhooks.length ? (
        <div className="shopifyWebhookRows">
          {technical.recent_webhooks.map((event) => {
            const tone = getShopifyStatusTone(event.status);
            return (
              <div key={event.id || event.webhook_id || `${event.topic}-${event.received_at}`} className="shopifyWebhookRow">
                <div className="shopifyWebhookMain">
                  <div className="shopifyTableTitle">{event.topic || "Webhook Shopify"}</div>
                  <div className="shopifyTableSubtle">
                    {event.webhook_id || "Sem webhook_id"} • {event.shop_domain || "shopify"}
                  </div>
                </div>
                <div className="shopifyWebhookMeta">
                  <span className={`shopifyStatusPill is-${tone}`.trim()}>
                    {getShopifyWebhookStatusLabel(event.status)}
                  </span>
                  <span className="shopifyTableSubtle">{formatShopifyDateTime(event.received_at)}</span>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="shopifyEmptyCard">Ainda não há eventos técnicos recentes da Shopify.</div>
      )}

      {technical.recent_errors.length ? (
        <div className="shopifyTechnicalErrors">
          <div className="shopifyMiniLabel">Erros recentes</div>
          {technical.recent_errors.map((event) => (
            <div key={`error-${event.id || event.webhook_id}`} className="shopifyTechnicalError">
              <strong>{event.topic || "Webhook Shopify"}</strong>
              <span>{event.error_message || "Erro não detalhado."}</span>
            </div>
          ))}
        </div>
      ) : null}
    </article>
  );
}
