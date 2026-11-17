import { STUDIO_CHANNELS, STUDIO_FORMATS, type StudioChannel } from "../../app/studio";
import type { ApprovedField, ImportField, ImportPillar, ImportValue } from "../../app/brandImport";

export const GROUP_LABELS = { identidade: "Identidade", negocio: "Negócio e objetivos", operacao: "Operação editorial", diretrizes: "Diretrizes" } as const;
export const STATUS_LABELS = { found: "Encontrado", ambiguous: "Revisar", missing: "Não encontrado" } as const;

const channel = (c: string) => STUDIO_CHANNELS[c as StudioChannel] || c;
const format = (f: string) => STUDIO_FORMATS[f as keyof typeof STUDIO_FORMATS] || f;

/** Valor legível para "Atual" e para o resumo da confirmação. */
export function describeValue(field: Pick<ImportField, "kind">, value: ImportValue): string {
  if (value === null || value === undefined || value === "") return "—";
  switch (field.kind) {
    case "text": return String(value);
    case "int": return `${value} por semana`;
    case "list": return (value as string[]).join(", ") || "—";
    case "channels": return (value as string[]).map(channel).join(", ") || "—";
    case "formats": return (value as string[]).map(format).join(", ") || "—";
    case "frequency": return Object.entries(value as Record<string, number>).map(([c, n]) => `${channel(c)}: ${n}/semana`).join(" · ") || "—";
    case "pillars": return (value as ImportPillar[]).map((p) => `${p.name} (${p.weight ?? "?"}%)`).join(", ") || "—";
    default: return String(value);
  }
}

export function pillarTotal(value: ImportValue): number | null {
  const pillars = (value as ImportPillar[] | null) || [];
  if (!pillars.length || pillars.some((p) => p.weight === null || p.weight === undefined || Number.isNaN(Number(p.weight)))) return null;
  return pillars.reduce((sum, p) => sum + Number(p.weight), 0);
}

/** Por que este campo marcado ainda não pode ser aplicado (null = pode). Mesmas regras do backend.
 * ``platforms``: as Plataformas que valerão depois de aplicar (as aprovadas agora ou as atuais). */
export function fieldProblem(field: ImportField, value: ImportValue, platforms: string[]): string | null {
  if (value === null || value === undefined || (typeof value === "string" && !value.trim()) || (Array.isArray(value) && !value.length)
    || (field.kind === "frequency" && !Object.keys(value as object).length)) return "Valor vazio: desmarque para manter o atual.";
  if (field.kind === "text" && field.max_length && String(value).length > field.max_length) return `Até ${field.max_length} caracteres.`;
  if (field.kind === "int" && !(Number(value) >= 1 && Number(value) <= 14)) return "Use de 1 a 14 posts por semana.";
  if (field.kind === "frequency" && Object.values(value as Record<string, number>).some((n) => !(Number(n) >= 1 && Number(n) <= 14))) return "Cada canal: de 1 a 14 posts por semana.";
  if (field.kind === "pillars") {
    const pillars = value as ImportPillar[];
    if (pillars.some((p) => !p.name.trim())) return "Todo pilar precisa de nome.";
    const total = pillarTotal(value);
    if (total === null) return "Defina o peso de todos os pilares.";
    if (total !== 100) return `Os pesos somam ${total}%. Ajuste para 100%.`;
  }
  if (field.kind === "frequency") {
    const outside = Object.keys(value as object).filter((c) => !platforms.includes(c));
    if (outside.length) return `Inclua ${outside.map(channel).join(", ")} nas Plataformas (marque e ajuste o campo Plataformas).`;
  }
  return null;
}

/** Campos a pré-selecionar no "Selecionar os encontrados": descritivos, encontrados e diferentes do atual. */
export function suggestedKeys(fields: ImportField[]): string[] {
  return fields.filter((f) => f.status === "found" && !f.operational && f.changed).map((f) => f.key);
}

export function buildApproved(fields: ImportField[], selected: Set<string>, drafts: Record<string, ImportValue>,
  modes: Record<string, ApprovedField["mode"]>): Record<string, ApprovedField> {
  const out: Record<string, ApprovedField> = {};
  for (const f of fields) if (selected.has(f.key)) out[f.key] = { value: drafts[f.key] ?? f.value, mode: modes[f.key] || "replace" };
  return out;
}

export const listToText = (value: ImportValue) => ((value as string[] | null) || []).join(", ");
export const textToList = (text: string) => text.split(/[,;\n]/).map((s) => s.trim()).filter(Boolean);
