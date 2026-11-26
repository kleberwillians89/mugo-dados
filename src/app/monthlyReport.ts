import { clientClientPath, http, publicHttp } from "./api";
import type { ReportData } from "./socialReport";

/** Relatório mensal completo: mídia paga, WhatsApp, vendas e resumo (cresce em cima do Relatório social). */
export type BusinessAd = { anuncio: string | null; campanha: string | null; investimento: number; conversoes: number; receita: number;
  roas: number | null; ctr_pct: number | null };
export type MonthlyBusiness = {
  month?: string; built_at?: string;
  midia?: { investimento?: number; impressoes?: number; cliques?: number; conversoes?: number; receita?: number; roas?: number | null;
    custo_por_conversao?: number | null; anuncios?: number; comparado_por?: string; melhores?: BusinessAd[]; piores?: BusinessAd[] };
  whatsapp?: { conversas?: number; viraram_venda?: number; taxa_pct?: number | null; pedidos?: number; receita?: number;
    parte_da_loja_pct?: number | null; origens?: { origem: string; conversas: number; vendas: number; receita: number }[] };
  vendas?: { pedidos?: number; faturamento?: number; ticket_medio?: number; pedidos_mes_anterior?: number; faturamento_mes_anterior?: number;
    variacao_faturamento_pct?: number | null };
};
export type MonthlyReport = {
  exists: boolean; status: "rascunho" | "liberado" | null; hidden?: boolean;
  data?: MonthlyBusiness; summary?: string | null; released_at?: string | null; updated_at?: string | null; share_token?: string | null;
};
const base = (path: string) => clientClientPath(`/studio/monthly-report${path}`);
const m = (month: string) => `/${encodeURIComponent(month)}`;

export const getMonthlyReport = (month: string) => http<MonthlyReport>(base(m(month)));
export const closeMonthlyReport = (month: string) => http<MonthlyReport>(base(`${m(month)}/close`), { method: "POST", timeoutMs: 180_000 });
export const saveMonthlySummary = (month: string, summary: string) =>
  http<MonthlyReport>(base(`${m(month)}/summary`), { method: "PUT", body: JSON.stringify({ summary }) });
export const releaseMonthlyReport = (month: string, release: boolean) =>
  http<MonthlyReport>(base(`${m(month)}/${release ? "release" : "unrelease"}`), { method: "POST" });
export const shareMonthlyReport = (month: string) => http<{ share_token: string }>(base(`${m(month)}/share`), { method: "POST" });
export const shareUrl = (token: string) => `${window.location.origin}/relatorio/${token}`;

export type PublicReport = {
  month: string; brand: string; business: MonthlyBusiness; summary: string | null;
  social: { built: boolean; data?: ReportData; insights?: string[]; images?: Record<string, string> };
};
export const getPublicReport = (token: string) => publicHttp<PublicReport>(`/api/public/reports/${encodeURIComponent(token)}`);

export function reportTokenFromPath(pathname: string): string | null {
  const match = String(pathname || "").match(/^\/relatorio\/([A-Za-z0-9_-]{24,80})\/?$/);
  return match ? match[1] : null;
}
export const hasBusiness = (b?: MonthlyBusiness) => Boolean(b && ((b.midia && b.midia.investimento) || (b.whatsapp && b.whatsapp.conversas) || (b.vendas && b.vendas.pedidos)));
