import type { Ga4CampaignRow } from "../../app/types";
import { formatCurrency } from "../../app/dataFormat";

export function formatGa4Roas(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}x`;
}

export function formatGa4Investment(row: Pick<Ga4CampaignRow, "investment">): string {
  return typeof row.investment === "number" && Number.isFinite(row.investment) ? formatCurrency(row.investment) : "—";
}
