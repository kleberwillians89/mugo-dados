export const CHART_COLORS = {
  organic: "#2D6CDF",
  organicSoft: "rgba(45,108,223,0.16)",
  organicMuted: "rgba(45,108,223,0.64)",
  ads: "#7C3AED",
  adsSoft: "rgba(124,58,237,0.14)",
  grid: "rgba(12,65,96,0.10)",
  axis: "rgba(31,41,55,0.70)",
  tooltipBg: "rgba(12,18,30,0.94)",
  tooltipBorder: "rgba(148,163,184,0.32)",
  tooltipText: "#F8FAFC",
};

export const CHART_LINE_WIDTH = 2.6;
export const CHART_POINT_RADIUS = 0;
export const CHART_POINT_HOVER_RADIUS = 4;

export function formatCompactNumber(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "0";
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(abs >= 10_000_000_000 ? 0 : 1)} bi`;
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)} mi`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(abs >= 10_000 ? 0 : 1)} mil`;
  return n.toLocaleString("pt-BR");
}

export function formatFullNumber(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "0";
  return n.toLocaleString("pt-BR");
}

export function formatDatePtBr(isoDate: string): string {
  const parsed = new Date(`${String(isoDate || "").trim()}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return String(isoDate || "");
  return parsed.toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}
