import type { IntelligenceAnalysisRecord, IntelligenceMetric } from "./intelligenceTypes";
import type { Period } from "./PeriodContext";

export type ReportKind = "weekly" | "monthly";
export type IntelligenceReport = { kind: ReportKind; companyName: string; analysis: IntelligenceAnalysisRecord };

/** Calendar intervals only. Metrics/comparisons remain owned by the backend. */
export function reportPeriod(kind: ReportKind, reference: string): Period {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(reference)) throw new Error("Selecione uma data válida.");
  const day = new Date(reference + "T12:00:00Z");
  if (!Number.isFinite(day.getTime()) || day.toISOString().slice(0, 10) !== reference) throw new Error("Selecione uma data válida.");
  const start = new Date(day), end = new Date(day);
  if (kind === "weekly") {
    start.setUTCDate(day.getUTCDate() - (day.getUTCDay() + 6) % 7);
    end.setTime(start.getTime()); end.setUTCDate(start.getUTCDate() + 6);
  } else {
    start.setUTCDate(1); end.setUTCMonth(day.getUTCMonth() + 1, 0);
  }
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

export function validReport(record: IntelligenceAnalysisRecord | null, clientId: string, period: Period): record is IntelligenceAnalysisRecord {
  return Boolean(record?.client_id === clientId && record.status === "completed"
    && record.period_start === period.start && record.period_end === period.end && record.analysis?.executive.overall?.trim());
}

export function comparableReportMetric(metric: IntelligenceMetric): boolean {
  return metric.status === "confirmed" && metric.value != null && metric.previous_value != null && metric.variation_percent != null;
}

export function reportDate(value: string): string {
  const date = new Date(value.length === 10 ? value + "T12:00:00Z" : value);
  return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", dateStyle: "short" }).format(date) : "Não informado";
}

export function sourceLabel(source: string): string {
  if (source.startsWith("meta_campaign_")) return "Meta Ads · campanha";
  const labels: Record<string, string> = {
    paid_media: "Mídia paga", ga4: "Google Analytics", shopify: "Loja virtual",
    "shopify+paid_media": "Loja virtual e mídia paga", meta_ads: "Meta Ads",
    google_ads: "Google Ads", instagram: "Instagram", fbits: "FBITS",
  };
  return labels[source] || source.replaceAll("_", " ");
}

export function formatMetric(metric: IntelligenceMetric) {
  if (metric.value == null) {
    const statusLabel: Partial<Record<IntelligenceMetric["status"], string>> = {
      unavailable: "Indisponível",
      disconnected: "Não conectado",
      partial: "Parcial",
      error: "Erro na consulta",
    };
    return statusLabel[metric.status] || "Sem dados";
  }
  let formatted: string;
  if (metric.format === "currency") {
    formatted = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(metric.value);
  } else if (metric.format === "percent") {
    formatted = `${metric.value.toLocaleString("pt-BR")}%`;
  } else if (metric.format === "decimal") {
    formatted = `${metric.value.toLocaleString("pt-BR")}x`;
  } else {
    formatted = Math.round(metric.value).toLocaleString("pt-BR");
  }
  return metric.status === "partial" ? `${formatted} · parcial` : formatted;
}


/** Clone React-rendered text into a standalone print document. Never inject HTML. */
export function printIntelligenceReport(element: HTMLElement, title: string, stylesheet: string): void {
  const popup = window.open("about:blank", "_blank");
  if (!popup) throw new Error("Permita a abertura da janela de impressão para salvar o PDF.");
  popup.opener = null;
  try {
    const doc = popup.document;
    const heading = doc.createElement("title"); heading.textContent = title;
    const style = doc.createElement("style"); style.textContent = stylesheet;
    doc.documentElement.lang = "pt-BR";
    doc.head.replaceChildren(heading, style);
    doc.body.replaceChildren(doc.importNode(element, true));
    popup.addEventListener("afterprint", () => popup.close(), { once: true });
    popup.focus(); popup.print();
  } catch (error) {
    popup.close(); throw error;
  }
}
