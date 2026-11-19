import { formatCurrency, formatInteger } from "./dataFormat";

/** Frases de resultado em português de gente: a primeira coisa que a tela diz, para qualquer pessoa entender. */
export function salesOriginHeadline(t: { orders: number; revenue: number; origin_coverage_percent?: number | null } | null | undefined) {
  if (!t) return "";
  if (!t.orders) return "Nenhum pedido na loja neste período.";
  const base = `Neste período, a loja recebeu ${formatInteger(t.orders)} pedido${t.orders === 1 ? "" : "s"}, somando ${formatCurrency(t.revenue)}`;
  return t.origin_coverage_percent != null ? `${base}. Sabemos de onde veio ${Math.round(t.origin_coverage_percent)}% deles.` : `${base}.`;
}

export function siteHeadline(s: { sessions: number; purchases?: number | null; purchase_revenue?: number | null } | null | undefined) {
  if (!s) return "";
  if (!s.sessions) return "O site não recebeu visitas registradas pelo Google Analytics neste período.";
  const base = `Neste período, o site recebeu ${formatInteger(s.sessions)} visita${s.sessions === 1 ? "" : "s"}`;
  if (s.purchases) {
    const rate = (s.purchases / s.sessions) * 100;
    return `${base} e ${formatInteger(s.purchases)} compra${s.purchases === 1 ? "" : "s"}${s.purchase_revenue ? ` (${formatCurrency(s.purchase_revenue)})` : ""}: de cada 100 visitas, ${rate.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} compraram.`;
  }
  return `${base}.`;
}
