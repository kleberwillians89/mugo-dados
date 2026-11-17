import { http, clientClientPath } from "./api";
import type { BrandPillar, BrandProfile, StudioChannel, StudioFormat } from "./studio";
import type { BusinessContextFields } from "./api";

/** Importar configurações do planejamento: prévia (não grava) e aplicação só do que foi aprovado. */
export type ImportKind = "text" | "list" | "int" | "channels" | "formats" | "frequency" | "pillars";
export type ImportStatus = "found" | "ambiguous" | "missing";
export type ImportPillar = Omit<BrandPillar, "weight"> & { weight: number | null };
export type ImportValue = string | string[] | number | Partial<Record<StudioChannel, number>> | ImportPillar[] | StudioChannel[] | StudioFormat[] | null;
export type ImportGroup = "identidade" | "negocio" | "operacao" | "diretrizes";

export type ImportField = {
  key: string; label: string; group: ImportGroup; kind: ImportKind; targets: string[];
  /** Regra operacional (pilares, frequência, formatos, plataformas): nunca vem pré-marcada. */
  operational: boolean;
  status: ImportStatus; value: ImportValue; current: ImportValue; changed: boolean;
  source: { excerpt: string; verified: boolean; location: string | null } | null;
  notes: string[]; max_length: number | null;
};
export type ImportPreview = {
  ok: true;
  document: { id: string; name: string; chars_total: number; read_chars: number; partial: boolean };
  fields: ImportField[];
  counts: Record<ImportStatus, number>;
  missing: string[];
};
export type ApprovedField = { value: ImportValue; mode: "replace" | "append" };
export type ImportApplied = { ok: true; applied: string[]; profile?: BrandProfile; business_context?: BusinessContextFields };

const base = (path: string) => clientClientPath(`/studio/knowledge/import${path}`);

export function previewBrandImport(documentId: string) {
  return http<ImportPreview>(base("/preview"), { method: "POST", body: JSON.stringify({ document_id: documentId }), timeoutMs: 180_000 });
}

export function applyBrandImport(documentId: string | null, fields: Record<string, ApprovedField>) {
  return http<ImportApplied>(base("/apply"), { method: "POST", body: JSON.stringify({ document_id: documentId, fields, confirm: true }) });
}
