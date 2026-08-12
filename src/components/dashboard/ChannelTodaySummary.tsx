type DailyValue = {
  revenue: number | null;
  orders: number | null;
};

type Props = {
  date: string;
  value: DailyValue | null;
};

function currency(value: number): string {
  return value.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    maximumFractionDigits: 2,
  });
}

function civilDate(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("pt-BR", { day: "numeric", month: "long" }).format(
    new Date(Date.UTC(year, month - 1, day, 12))
  );
}

export default function ChannelTodaySummary({ date, value }: Props) {
  const revenue = value?.revenue ?? null;
  const orders = value?.orders ?? null;
  const available = revenue != null && orders != null;
  const ticket = available && orders > 0 ? revenue / orders : null;
  return (
    <section className="channelToday" aria-label="Resultado Shopify de hoje">
      <header className="channelTodayHead">
        <div><span className="executiveEyebrow">Hoje</span><strong>{civilDate(date)}</strong></div>
        <span>Os dados de hoje ainda podem sofrer alterações.</span>
      </header>
      <div className="channelTodayGrid">
        <div><span>Valor vendido hoje</span><strong>{available ? currency(revenue) : "Sem dados atualizados"}</strong></div>
        <div><span>Pedidos hoje</span><strong>{available ? orders.toLocaleString("pt-BR") : "Sem dados atualizados"}</strong></div>
        <div><span>Ticket médio hoje</span><strong>{ticket != null ? currency(ticket) : available ? "—" : "Sem dados atualizados"}</strong></div>
      </div>
      <small>Fonte: Shopify</small>
    </section>
  );
}
