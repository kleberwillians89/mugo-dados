import { clientClientPath, http } from "./api";

/** Biblioteca da marca: arquivos e links por categoria + arte dos posts aprovados (lida do Calendário). */
export type LibraryCategory = "produto" | "logo" | "referencia" | "foto" | "video" | "documento" | "outro";
export type LibraryItem = {
  id: string; kind: "arquivo" | "link" | "post"; category: LibraryCategory | "aprovado"; title: string; url: string;
  mime_type?: string | null; size_bytes?: number | null; note?: string | null; side: "mugo" | "cliente";
  created_by_name?: string | null; created_at?: string | null; can_delete?: boolean;
  item_id?: string; status?: string; permalink?: string | null; format?: string | null;
};
export const LIBRARY_CATEGORIES: Record<LibraryCategory, string> = {
  produto: "Produto", logo: "Logo", referencia: "Referência", foto: "Foto", video: "Vídeo bruto", documento: "Documento", outro: "Outro",
};
/** Mesma lista do servidor (studio_library.TYPES). */
export const LIBRARY_ACCEPT = [
  "image/jpeg", "image/png", "image/webp", "image/gif", "image/svg+xml", "video/mp4", "video/quicktime", "video/webm",
  "application/pdf", "application/zip", "text/plain", "text/csv", "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.ms-powerpoint",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation", "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
];
export const LIBRARY_MAX_BYTES = 500 * 1024 * 1024;

const base = (path = "") => clientClientPath(`/studio/library${path}`);

export function listLibrary() {
  return http<{ items: LibraryItem[]; approved: LibraryItem[]; categories: Record<LibraryCategory, string>; team: boolean }>(base());
}
export function addLibraryLink(input: { url: string; title?: string; category: LibraryCategory; note?: string }) {
  return http<{ item: LibraryItem }>(base(), { method: "POST", body: JSON.stringify({ kind: "link", ...input }) });
}
export function deleteLibraryItem(id: string) { return http<{ ok: true }>(base(`/${encodeURIComponent(id)}`), { method: "DELETE" }); }

/** Envia direto para o Storage (link assinado) com progresso e registra na Biblioteca. */
export async function uploadLibraryFile(file: File, category: LibraryCategory, onProgress?: (pct: number) => void, title?: string) {
  const type = (file.type || "").toLowerCase();
  if (!LIBRARY_ACCEPT.includes(type)) throw new Error("Tipo de arquivo não aceito. Envie imagem, vídeo, PDF ou documento do Office.");
  if (file.size > LIBRARY_MAX_BYTES) throw new Error("Arquivo acima de 500 MB.");
  const target = await http<{ upload_url: string; public_url: string }>(base("/upload-url"), { method: "POST", body: JSON.stringify({ content_type: type }) });
  await new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", target.upload_url);
    xhr.setRequestHeader("Content-Type", type);
    xhr.setRequestHeader("x-upsert", "false");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100)); };
    xhr.onload = () => (xhr.status < 400 ? resolve() : reject(new Error("O envio do arquivo falhou. Tente de novo.")));
    xhr.onerror = () => reject(new Error("O envio do arquivo falhou. Confira a conexão."));
    xhr.send(file);
  });
  return http<{ item: LibraryItem }>(base(), { method: "POST", body: JSON.stringify({
    kind: "arquivo", category, url: target.public_url, title: title || file.name, mime_type: type, size_bytes: file.size,
  }) });
}

export function previewKind(item: Pick<LibraryItem, "url" | "mime_type" | "kind">): "image" | "video" | "pdf" | "link" | "file" {
  const t = (item.mime_type || "").toLowerCase();
  const u = item.url.toLowerCase().split("?")[0];
  if (t.startsWith("image/") || /\.(jpe?g|png|webp|gif|svg)$/.test(u)) return "image";
  if (t.startsWith("video/") || /\.(mp4|mov|webm)$/.test(u)) return "video";
  if (t === "application/pdf" || u.endsWith(".pdf")) return "pdf";
  if (item.kind === "post") return "image"; // arte do Calendário sem extensão no endereço
  return item.kind === "link" ? "link" : "file";
}

export function formatBytes(n?: number | null): string {
  if (!n) return "";
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  return `${(n / (1024 * 1024)).toFixed(n < 10 * 1024 * 1024 ? 1 : 0).replace(".", ",")} MB`;
}
