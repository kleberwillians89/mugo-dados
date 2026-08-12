type Props = {
  channel: "Meta" | "Google";
  store: { revenue: number | null; orders: number | null; ticket: number | null };
  media: { spend: number | null; roas: number | null; attributedRoas?: number | null; attributedRevenue: number | null; attributedOrders: number | null };
  roasBasis?: "attributed" | "shopify";
};

function currency(value: number | null): string {
  return value == null ? "Sem dados" : value.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 2 });
}

function number(value: number | null): string {
  return value == null ? "Sem dados" : value.toLocaleString("pt-BR");
}

export default function StoreMediaSummary({ channel, store, media, roasBasis = "attributed" }: Props) {
  const mediaSource = channel === "Meta" ? "Meta Ads" : "Google Ads";
  const hasStore = store.revenue != null && store.orders != null && store.ticket != null;
  return (
    <section className="storeMediaSummary" aria-label={`Resultado comercial e performance ${channel}`}>
      <div className="storeMediaNarrative">
        <span className="executiveEyebrow">Resultado da loja</span>
        <p>{hasStore
          ? `A loja faturou ${currency(store.revenue)} no período, com ${number(store.orders)} pedidos e ticket médio de ${currency(store.ticket)}.`
          : "O resultado comercial aguarda dados da Shopify para este período."}</p>
      </div>
      <div className="storeMediaGrid is-store">
        <article><span>Receita real</span><strong>{currency(store.revenue)}</strong><small>Fonte: Shopify</small></article>
        <article><span>Pedidos</span><strong>{number(store.orders)}</strong><small>Fonte: Shopify</small></article>
        <article><span>Ticket médio</span><strong>{currency(store.ticket)}</strong><small>Fonte: Shopify</small></article>
      </div>
      <div className="storeMediaNarrative">
        <span className="executiveEyebrow">Performance da mídia</span>
        <p>{media.spend != null
          ? roasBasis === "shopify"
            ? `${mediaSource} recebeu ${currency(media.spend)} de investimento. Comparando esse valor à receita real Shopify, o ROAS é ${media.roas != null ? `${media.roas.toFixed(2)}x` : "indisponível"}; a plataforma atribuiu ${currency(media.attributedRevenue)} em receita.`
            : `${mediaSource} recebeu ${currency(media.spend)} de investimento e atribuiu ${currency(media.attributedRevenue)} em receita, com ROAS de ${media.roas != null ? `${media.roas.toFixed(2)}x` : "indisponível"}.`
          : `A performance de ${mediaSource} aguarda dados atualizados.`}</p>
      </div>
      <div className="storeMediaGrid is-media">
        <article><span>Investimento {channel}</span><strong>{currency(media.spend)}</strong><small>Fonte: {mediaSource}</small></article>
        <article><span>ROAS {channel}</span><strong>{media.roas == null ? "Sem dados" : `${media.roas.toFixed(2)}x`}</strong><small>{roasBasis === "shopify" ? "Receita real Shopify ÷ investimento" : `Atribuição ${channel} ÷ investimento`}</small></article>
        <article><span>Receita atribuída</span><strong>{currency(media.attributedRevenue)}</strong><small>Fonte: {mediaSource}</small></article>
        <article><span>ROAS atribuído {channel}</span><strong>{media.attributedRoas == null ? "Sem dados" : `${media.attributedRoas.toFixed(2)}x`}</strong><small>Atribuição {channel} ÷ investimento</small></article>
        <article><span>Compras atribuídas</span><strong>{number(media.attributedOrders)}</strong><small>Fonte: {mediaSource}</small></article>
      </div>
    </section>
  );
}
