import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { MonthAgg } from "../app/types";
import {
  CHART_COLORS,
  CHART_LINE_WIDTH,
  formatCompactNumber,
  formatFullNumber,
} from "./dashboard/chartTheme";

const AXIS_STYLE = { fill: CHART_COLORS.axis, fontSize: 12, fontWeight: 700 };
const TOOLTIP_STYLE = {
  backgroundColor: CHART_COLORS.tooltipBg,
  border: `1px solid ${CHART_COLORS.tooltipBorder}`,
  borderRadius: "12px",
  color: CHART_COLORS.tooltipText,
};
const TOOLTIP_LABEL_STYLE = { color: CHART_COLORS.tooltipText, fontWeight: 700 };
const TOOLTIP_ITEM_STYLE = { color: CHART_COLORS.tooltipText, fontWeight: 600 };

function fmtMonth(m: string) {
  const [y, mo] = m.split("-");
  return `${mo}/${y.slice(2)}`;
}

function fmtInt(value: unknown): string {
  return formatFullNumber(value);
}

function useChartSize() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ w: 0, h: 260 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const apply = () => {
      const w = Math.max(280, Math.floor(el.clientWidth || 0));
      const h = Math.max(220, Math.floor(el.clientHeight || 0) || 260);
      setSize({ w, h });
    };

    apply();
    const ro = new ResizeObserver(() => apply());
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return { ref, ...size };
}

export function MonthMixChart(props: {
  data: MonthAgg[];
}) {
  const rows = useMemo(
    () =>
      props.data.map((d) => ({
        month: fmtMonth(d.month),
        posts_total: d.posts + d.reels,
        reach_total: d.reach,
      })),
    [props.data]
  );
  const { ref, w, h } = useChartSize();

  return (
    <div className="chartHost" ref={ref}>
      {w > 0 ? (
        <BarChart width={w} height={h} data={rows}>
          <CartesianGrid strokeDasharray="4 4" stroke={CHART_COLORS.grid} />
          <XAxis dataKey="month" tick={AXIS_STYLE} tickMargin={8} />
          <YAxis yAxisId="left" tick={AXIS_STYLE} tickFormatter={(v) => formatCompactNumber(v)} />
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={AXIS_STYLE}
            tickFormatter={(v) => formatCompactNumber(v)}
          />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            labelStyle={TOOLTIP_LABEL_STYLE}
            itemStyle={TOOLTIP_ITEM_STYLE}
            formatter={(value, name) => {
              const label =
                name === "posts_total"
                  ? "Posts publicados"
                  : name === "reach_total"
                    ? "Alcance mensal"
                    : String(name);
              return [fmtInt(value), label];
            }}
            labelFormatter={(label) => `Mês: ${label}`}
          />
          <Legend
            formatter={(value) => {
              if (value === "posts_total") return "Posts publicados";
              if (value === "reach_total") return "Alcance mensal";
              return value;
            }}
          />
          <Bar
            yAxisId="left"
            dataKey="posts_total"
            name="posts_total"
            fill={CHART_COLORS.organicSoft}
            radius={[8, 8, 0, 0]}
          />
          <Line
            type="monotone"
            yAxisId="right"
            dataKey="reach_total"
            name="reach_total"
            stroke={CHART_COLORS.organic}
            strokeWidth={CHART_LINE_WIDTH}
            dot={{ r: 2 }}
          />
        </BarChart>
      ) : null}
    </div>
  );
}

export function MonthCompareLines(props: {
  aLabel: string;
  bLabel: string;
  a?: MonthAgg;
  b?: MonthAgg;
}) {
  const a = props.a;
  const b = props.b;
  const rows = useMemo(
    () => [
      { key: "posts", label: "Posts (feed)", a: a?.posts ?? 0, b: b?.posts ?? 0 },
      { key: "reels", label: "Reels", a: a?.reels ?? 0, b: b?.reels ?? 0 },
      { key: "reach", label: "Reach (conteúdo)", a: a?.reach ?? 0, b: b?.reach ?? 0 },
      { key: "views", label: "Views (reels)", a: a?.views ?? 0, b: b?.views ?? 0 },
      { key: "interactions", label: "Interações", a: a?.interactions ?? 0, b: b?.interactions ?? 0 },
      { key: "profile_visits", label: "Visitas ao perfil", a: a?.profile_visits ?? 0, b: b?.profile_visits ?? 0 },
    ],
    [a, b]
  );
  const { ref, w, h } = useChartSize();

  return (
    <div className="chartHost" ref={ref}>
      {w > 0 ? (
        <LineChart width={w} height={h} data={rows}>
          <CartesianGrid strokeDasharray="4 4" stroke={CHART_COLORS.grid} />
          <XAxis dataKey="label" hide />
          <YAxis tick={AXIS_STYLE} tickFormatter={(v) => formatCompactNumber(v)} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            labelStyle={TOOLTIP_LABEL_STYLE}
            itemStyle={TOOLTIP_ITEM_STYLE}
            formatter={(value: unknown) => formatFullNumber(value)}
          />
          <Legend />
          <Line
            type="monotone"
            dataKey="a"
            name={props.aLabel}
            stroke={CHART_COLORS.organic}
            strokeWidth={CHART_LINE_WIDTH}
            dot={{ r: 2 }}
          />
          <Line
            type="monotone"
            dataKey="b"
            name={props.bLabel}
            stroke={CHART_COLORS.ads}
            strokeWidth={CHART_LINE_WIDTH}
            dot={{ r: 2 }}
          />
        </LineChart>
      ) : null}
    </div>
  );
}
