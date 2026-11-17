import { ApiError } from "./api";
import { LIBRARY_ACCEPT, listLibrary, uploadLibraryFile, type LibraryItem } from "./library";
import { teachFromFile, type KnowledgeKind, type TeachResult } from "./studio";

/**
 * Enviar material para o Conhecimento da marca guardando também o ARQUIVO ORIGINAL na Biblioteca da marca
 * (categoria Documento). O texto ensina a IA; o original fica para ver e baixar — e a Biblioteca também entra no
 * pacote da IA. O original é complemento: se a Biblioteca falhar, o aprendizado continua valendo.
 */
export const ORIGINAL_NOTE_PREFIX = "Conhecimento da marca · doc:";

/** O PDF não tem texto: a tela oferece a leitura das páginas pela IA. */
export function needsOcr(error: unknown): boolean {
  return error instanceof ApiError && error.code === "DOC_NEEDS_OCR";
}

const MIME: Record<string, string> = {
  pdf: "application/pdf", docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", csv: "text/csv", txt: "text/plain",
};

function withType(file: File): File {
  if (file.type && LIBRARY_ACCEPT.includes(file.type.toLowerCase())) return file;
  const type = MIME[(file.name.split(".").pop() || "").toLowerCase()];
  return type ? new File([file], file.name, { type }) : file;
}

export type TeachWithOriginal = TeachResult & { original: "guardado" | "nao_guardado" | "nao_suportado" };

export async function teachAndKeepOriginal(file: File, kind: KnowledgeKind, options: { ocr?: boolean } = {}): Promise<TeachWithOriginal> {
  const result = await teachFromFile(file, kind, options);
  const typed = withType(file);
  if (!LIBRARY_ACCEPT.includes((typed.type || "").toLowerCase())) return { ...result, original: "nao_suportado" };
  try {
    await uploadLibraryFile(typed, "documento", undefined, file.name, `${ORIGINAL_NOTE_PREFIX}${result.document.id}`);
    return { ...result, original: "guardado" };
  } catch {
    return { ...result, original: "nao_guardado" };
  }
}

/** Documento do Conhecimento → link do original na Biblioteca (quando foi guardado). Nunca falha. */
export async function originalsByDocument(): Promise<Record<string, string>> {
  try {
    const { items } = await listLibrary();
    return originalsFrom(items);
  } catch {
    return {};
  }
}

export function originalsFrom(items: LibraryItem[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const item of items) {
    const note = item.note || "";
    if (note.startsWith(ORIGINAL_NOTE_PREFIX)) out[note.slice(ORIGINAL_NOTE_PREFIX.length).trim()] = item.url;
  }
  return out;
}
