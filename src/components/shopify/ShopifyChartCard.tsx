import { useId } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatShopifyShortDate } from "../../app/shopifyUi";

type ChartRow = {
  date: string;
  [key: string]: number | string;
};

type Props = {
  title: string;
  description?: string;
  data: ChartRow[];
  dataKey: string;
  color: string;
  valueFormatter?: (value: number) => string;
};

export default function ShopifyChartCard({
  title,
  description,
  data,
  dataKey,
  color,
  valueFormatter,
}: Props) {
  const gradientId = useId().replace(/:/g, "");
  const hasData = data.some((row) => Number(row[dataKey] || 0) !== 0);
  const totalValue = data.reduce((total, row) => total + Number(row[dataKey] || 0), 0);
  const formatValue = valueFormatter || ((value: number) => new Intl.NumberFormat("pt-BR").format(value));

  return (
    <article className="shopifyChartCard">
      <div className="shopifyChartCardHead">
        <div>
          <div className="shopifyMiniLabel">{title}</div>
          {description ? <p className="shopifyChartDescription">{description}</p> : null}
        </div>
        <div className="shopifyChartValue" aria-label={`${title} total no período`}>
          {formatValue(totalValue)}
        </div>
      </div>

      {!hasData ? (
        <div className="shopifyChartViewport chartEmptyState">
          <div className="smallMuted">Sem dados de {title.toLowerCase()} neste período.</div>
          <div className="smallMuted">O gráfico aparece assim que a Shopify sincronizar o período.</div>
        </div>
      ) : (
      <div className="shopifyChartViewport">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 6, right: 8, left: 8, bottom: 0 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.24} />
                <stop offset="100%" stopColor={color} stopOpacity={0.03} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="rgba(26,23,24,.08)" strokeDasharray="4 4" />
            <XAxis
              axisLine={false}
              dataKey="date"
              minTickGap={28}
              tick={{ fill: "rgba(26,23,24,.54)", fontSize: 11 }}
              tickFormatter={(value) => formatShopifyShortDate(String(value))}
              tickLine={false}
            />
            <YAxis axisLine={false} hide tickLine={false} />
            <Tooltip
              contentStyle={{
                borderRadius: 14,
                border: "1px solid rgba(26,23,24,.12)",
                boxShadow: "0 18px 40px rgba(26,23,24,.12)",
              }}
              formatter={(value) => formatValue(Number(value))}
              labelFormatter={(value) => `Data: ${formatShopifyShortDate(String(value))}`}
            />
            <Area
              activeDot={{ r: 4, strokeWidth: 0, fill: color }}
              dataKey={dataKey}
              name={title}
              fill={`url(#${gradientId})`}
              stroke={color}
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2.4}
              type="monotone"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      )}
    </article>
  );
}
