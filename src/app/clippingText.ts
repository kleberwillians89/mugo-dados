import type { ClippingView } from "./contentOps";

/** A primeira frase do Clipping, em português de gente. */
export function clippingHeadline(company: string, week: ClippingView["week"] | undefined) {
  if (!week) return "";
  const c = week.current;
  if (!c.marca) return `Nenhuma notícia sobre a ${company} nos últimos 7 dias.${c.concorrente ? ` Os concorrentes apareceram em ${c.concorrente}.` : ""}`;
  const parts = [`${c.positivo} positiva${c.positivo === 1 ? "" : "s"}`, `${c.negativo} negativa${c.negativo === 1 ? "" : "s"}`];
  const trend = week.marca_variacao > 0 ? `, ${week.marca_variacao} a mais que na semana anterior` : week.marca_variacao < 0 ? `, ${Math.abs(week.marca_variacao)} a menos que na semana anterior` : "";
  return `Nos últimos 7 dias, a ${company} apareceu em ${c.marca} notícia${c.marca === 1 ? "" : "s"} (${parts.join(" e ")})${trend}.`;
}

