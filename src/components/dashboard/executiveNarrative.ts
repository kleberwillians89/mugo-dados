import type { ExecutiveMetric } from "./ExecutiveOverview";

export type Tone = "positive" | "neutral" | "attention";

export function changeOf(current: number, previous: number): { absolute: number; percent: number | null } {
  const absolute = current - previous;
  return {
    absolute,
    percent: previous === 0 ? null : (absolute / Math.abs(previous)) * 100,
  };
}

export function toneOf(metric: ExecutiveMetric): Tone {
  if (metric.value == null || metric.previous == null) return "neutral";
  const direction = metric.value - metric.previous;
  if (direction === 0) return "neutral";
  const positive = metric.inverse ? direction < 0 : direction > 0;
  return positive ? "positive" : "attention";
}

export function signedValue(value: number, digits = 0): string {
  const formatted = Math.abs(value).toLocaleString("pt-BR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${formatted}`;
}

export type ExecutiveNarrative = {
  advance: { metric: ExecutiveMetric; absolute: number; percent: number | null } | null;
  risk: { metric: ExecutiveMetric; absolute: number; percent: number | null } | null;
  opportunity: string;
  nextAction: string;
};

/**
 * Única fonte da narrativa executiva (avanço/risco/oportunidade/próxima
 * ação) — usada pelo hero (frase de abertura) e pelo painel "O que merece
 * atenção", para que as duas superfícies nunca contem histórias diferentes
 * a partir do mesmo dado.
 */
export function computeExecutiveNarrative(metrics: ExecutiveMetric[]): ExecutiveNarrative {
  const comparable = metrics.filter(
    (metric): metric is ExecutiveMetric & { value: number; previous: number } =>
      metric.value != null && metric.previous != null
  );
  const ranked = comparable
    .map((metric) => ({ metric, ...changeOf(metric.value, metric.previous) }))
    .filter((item) => item.percent != null)
    .sort((left, right) => Math.abs(right.percent || 0) - Math.abs(left.percent || 0));
  const advance = ranked.find((item) => toneOf(item.metric) === "positive") || null;
  const risk = ranked.find((item) => toneOf(item.metric) === "attention") || null;

  const reach = metrics.find((metric) => metric.key === "reach")?.value ?? null;
  const interactions = metrics.find((metric) => metric.key === "interactions")?.value ?? null;
  const visits = metrics.find((metric) => metric.key === "profile_views")?.value ?? null;
  const clicks = metrics.find((metric) => metric.key === "website_clicks")?.value ?? null;

  const opportunity =
    visits != null && clicks != null
      ? `${visits.toLocaleString("pt-BR")} visitas ao perfil geraram ${clicks.toLocaleString("pt-BR")} cliques no link — o ponto observável mais próximo da intenção comercial.`
      : reach != null && interactions != null
        ? `${reach.toLocaleString("pt-BR")} contas alcançadas e ${interactions.toLocaleString("pt-BR")} interações formam a base disponível para avaliar conteúdo.`
        : "Conecte e sincronize as fontes para identificar uma oportunidade sustentada por evidência.";

  const nextAction = risk
    ? `Investigar primeiro ${risk.metric.label.toLowerCase()}, que variou ${signedValue(risk.percent || 0, 1)}% contra o período anterior.`
    : visits != null && clicks != null
      ? "Revisar as publicações que mais geraram visitas e cliques antes de decidir o próximo investimento."
      : "Completar a cobertura das fontes antes de tomar decisões de otimização.";

  return { advance, risk, opportunity, nextAction };
}
