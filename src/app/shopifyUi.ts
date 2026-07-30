const currencyFormatter = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
  maximumFractionDigits: 0,
});

const compactFormatter = new Intl.NumberFormat("pt-BR", {
  notation: "compact",
  maximumFractionDigits: 1,
});

export function formatShopifyCurrency(value: number, currency = "BRL"): string {
  const amount = Number.isFinite(value) ? value : 0;
  if (currency.toUpperCase() === "BRL") {
    return currencyFormatter.format(amount);
  }

  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: currency.toUpperCase(),
    maximumFractionDigits: 0,
  }).format(amount);
}

export function formatShopifyCompactNumber(value: number): string {
  const amount = Number.isFinite(value) ? value : 0;
  if (Math.abs(amount) < 1000) {
    return new Intl.NumberFormat("pt-BR").format(amount);
  }
  return compactFormatter.format(amount);
}

export function formatShopifyShortDate(value?: string | null): string {
  if (!value) return "Sem data";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Sem data";
  return parsed.toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "short",
  });
}

export function formatShopifyLongDate(value?: string | null): string {
  if (!value) return "Sem data";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Sem data";
  return parsed.toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export function formatShopifyDateTime(value?: string | null): string {
  if (!value) return "Sem registro";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Sem registro";
  return parsed.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatShopifyMonthLabel(month: number): string {
  return new Date(2026, month - 1, 1).toLocaleDateString("pt-BR", { month: "long" });
}

export function getShopifyFinancialStatusLabel(status?: string | null): string {
  const normalized = String(status || "").trim().toLowerCase();
  if (!normalized) return "Sem status";
  if (normalized === "paid") return "Pago";
  if (normalized === "partially_paid") return "Parcial";
  if (normalized === "pending") return "Pendente";
  if (normalized === "authorized") return "Autorizado";
  if (normalized === "refunded") return "Reembolsado";
  if (normalized === "voided") return "Cancelado";
  if (normalized === "expired") return "Expirado";
  return normalized.replaceAll("_", " ");
}

export function getShopifyWebhookStatusLabel(status?: string | null): string {
  const normalized = String(status || "").trim().toLowerCase();
  if (!normalized) return "Sem status";
  if (normalized === "processed") return "Processado";
  if (normalized === "processing") return "Processando";
  if (normalized === "received") return "Recebido";
  if (normalized === "error") return "Erro";
  if (normalized === "ignored") return "Ignorado";
  return normalized.replaceAll("_", " ");
}

export function getShopifyCustomerStatusLabel(status?: string | null): string {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "recurring") return "Recorrente";
  if (normalized === "new") return "Novo";
  return "Sem status";
}

export function getShopifyStatusTone(status?: string | null): "positive" | "warning" | "danger" | "neutral" {
  const normalized = String(status || "").trim().toLowerCase();
  if (["paid", "processed", "active", "success"].includes(normalized)) return "positive";
  if (["pending", "processing", "received", "authorized"].includes(normalized)) return "warning";
  if (["recurring"].includes(normalized)) return "positive";
  if (["new"].includes(normalized)) return "warning";
  if (["cancelled", "voided", "refunded", "error", "failed"].includes(normalized)) return "danger";
  return "neutral";
}
