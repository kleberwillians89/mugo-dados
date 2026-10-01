import type { ReactNode } from "react";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

// Espelham os tokens de design-system.css (atributos SVG não resolvem var()).
// Sem animação: o dado aparece pronto para leitura (e respeita movimento reduzido).
const ACCENT = "#004f6e";
const CONTEXT_FILL = "rgba(21, 24, 27, .08)";
const GRID = "rgba(21, 24, 27, .06)";
const AXIS_TEXT = "#687178";

type Row = Record<string, unknown>;

type Props<T extends Row> = {
  data: T[];
  xKey: string;
  /** Série protagonista: área + linha na cor de destaque. */
  primaryKey: string;
  /** Série de contexto: barras neutras em eixo próprio, oculto. */
  secondaryKey?: string;
  formatX: (value: string) => string;
  formatY: (value: number) => string;
  renderTooltip: (row: T) => ReactNode;
  /** Resumo textual do gráfico para leitores de tela. */
  ariaLabel: string;
  testId?: string;
};

export default function TrendChart<T extends Row>({
  data,
  xKey,
  primaryKey,
  secondaryKey,
  formatX,
  formatY,
  renderTooltip,
  ariaLabel,
  testId,
}: Props<T>) {
  return (
    <div className="ds-chart" role="img" aria-label={ariaLabel} data-testid={testId}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis
            dataKey={xKey}
            tickFormatter={(value) => formatX(String(value))}
            tick={{ fontSize: 11, fill: AXIS_TEXT }}
            axisLine={false}
            tickLine={false}
            tickMargin={10}
            minTickGap={28}
          />
          <YAxis
            yAxisId="primary"
            tickFormatter={(value) => formatY(Number(value))}
            tick={{ fontSize: 11, fill: AXIS_TEXT }}
            axisLine={false}
            tickLine={false}
            tickCount={4}
            width={76}
          />
          {secondaryKey ? (
            // Contexto fica no terço inferior: não disputa atenção com a série principal.
            <YAxis
              yAxisId="secondary"
              orientation="right"
              allowDecimals={false}
              domain={[0, (dataMax: number) => Math.max(1, Math.ceil(dataMax * 2.8))]}
              hide
            />
          ) : null}
          <Tooltip
            cursor={{ fill: "rgba(21, 24, 27, .035)" }}
            content={({ active, payload }) => {
              const row = payload?.[0]?.payload as T | undefined;
              return active && row ? <div className="ds-tooltip">{renderTooltip(row)}</div> : null;
            }}
          />
          {secondaryKey ? (
            <Bar yAxisId="secondary" dataKey={secondaryKey} fill={CONTEXT_FILL} radius={[3, 3, 0, 0]} maxBarSize={28} isAnimationActive={false} />
          ) : null}
          <Area
            yAxisId="primary"
            dataKey={primaryKey}
            type="monotone"
            stroke={ACCENT}
            strokeWidth={2.5}
            fill={ACCENT}
            fillOpacity={0.05}
            dot={false}
            activeDot={{ r: 4, fill: ACCENT, stroke: "#fff", strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
