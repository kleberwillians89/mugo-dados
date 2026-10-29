import { http, clientClientPath } from "./api";

/**
 * Biblioteca do Studio. O arquivo vai direto do navegador ao Storage (URL
 * assinada emitida pelo backend) e nunca passa pelo Render:
 * 1) pede a URL de upload → 2) envia com progresso → 3) backend confere e libera.
 */
export type AssetKind = "imagem" | "video" | "pdf";
export const ASSET_KINDS: Record<AssetKind, string> = { imagem: "Imagem", video: "Vídeo", pdf: "PDF" };

export type StudioAsset = {
  id: string; kind: AssetKind; mime_type: string; url: string | null; thumb_url: string | null;
  width: number | null; height: number | null; duration_seconds: number | null;
  size_bytes?: number; name?: string; folder?: string | null; tags?: string[];
  created_at?: string; updated_at?: string; used_in?: number;
};

export type AssetLibrary = { assets: StudioAsset[]; folders: string[]; tags: string[]; limits: Record<AssetKind, number>; url_expires_in: number };

const MB = 1024 * 1024;
export const SIZE_LIMITS: Record<AssetKind, number> = { imagem: 15 * MB, video: 200 * MB, pdf: 30 * MB };
const BY_EXTENSION: Record<string, string> = {
  jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp",
  mp4: "video/mp4", m4v: "video/mp4", mov: "video/quicktime", pdf: "application/pdf",
};
const KIND_BY_MIME: Record<string, AssetKind> = {
  "image/jpeg": "imagem", "image/png": "imagem", "image/webp": "imagem",
  "video/mp4": "video", "video/quicktime": "video", "application/pdf": "pdf",
};
export const ACCEPT = Object.keys(KIND_BY_MIME).join(",") + ",.mov";

/** Tipo aceito pelo bucket; alguns navegadores mandam .mov sem tipo. */
export function mimeOf(file: Pick<File, "name" | "type">): string | null {
  const declared = (file.type || "").toLowerCase();
  if (KIND_BY_MIME[declared]) return declared;
  const ext = file.name.toLowerCase().split(".").pop() || "";
  return BY_EXTENSION[ext] || null;
}

export function checkFile(file: Pick<File, "name" | "type" | "size">): { mime: string; kind: AssetKind } | { error: string } {
  const mime = mimeOf(file);
  if (!mime) return { error: "Tipo não aceito. Use JPG, PNG, WEBP, MP4, MOV ou PDF." };
  const kind = KIND_BY_MIME[mime];
  if (!file.size) return { error: "Arquivo vazio." };
  if (file.size > SIZE_LIMITS[kind]) return { error: `${ASSET_KINDS[kind]} acima de ${formatBytes(SIZE_LIMITS[kind])}.` };
  return { mime, kind };
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < MB) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / MB).toLocaleString("pt-BR", { maximumFractionDigits: bytes < 10 * MB ? 1 : 0 })} MB`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "";
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

const base = (path: string) => clientClientPath(`/studio${path}`);

export function listAssets(filters: { folder?: string; tag?: string; kind?: AssetKind; q?: string } = {}): Promise<AssetLibrary> {
  const params = new URLSearchParams(Object.entries(filters).filter(([, v]) => v) as [string, string][]);
  const query = params.toString();
  return http(base(`/assets${query ? `?${query}` : ""}`));
}
export function updateAsset(id: string, patch: { name?: string; folder?: string | null; tags?: string[] }) {
  return http<{ asset: StudioAsset }>(base(`/assets/${encodeURIComponent(id)}`), { method: "PATCH", body: JSON.stringify(patch) });
}
export function deleteAsset(id: string) {
  return http(base(`/assets/${encodeURIComponent(id)}`), { method: "DELETE" });
}
export function setItemAssets(itemId: string, assetIds: string[]) {
  return http<{ assets: StudioAsset[] }>(base(`/calendar/items/${encodeURIComponent(itemId)}/assets`), { method: "PUT", body: JSON.stringify({ asset_ids: assetIds }) });
}

type SignedUpload = { path: string; token: string; signed_url: string };
type UploadTicket = { asset: StudioAsset; upload: SignedUpload; thumb_upload: SignedUpload | null; max_bytes: number };

/** PUT direto no Storage com progresso (o fetch não informa progresso de envio). */
export function putToSignedUrl(url: string, body: Blob, contentType: string, onProgress?: (fraction: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", contentType);
    xhr.setRequestHeader("x-upsert", "false");
    const anon = String(import.meta.env.VITE_SUPABASE_ANON_KEY || "").trim();
    if (anon) xhr.setRequestHeader("apikey", anon);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(xhr.status === 413 ? "Arquivo acima do limite do armazenamento." : "O envio do arquivo falhou. Tente novamente.")));
    xhr.onerror = () => reject(new Error("A conexão caiu durante o envio. Tente novamente."));
    xhr.onabort = () => reject(new Error("Envio cancelado."));
    xhr.send(body);
  });
}

export type MediaInfo = { thumb: Blob | null; width?: number; height?: number; duration?: number };
const THUMB_EDGE = 480;

function drawThumb(source: CanvasImageSource, width: number, height: number): Promise<Blob | null> {
  const scale = Math.min(1, THUMB_EDGE / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  const ctx = canvas.getContext("2d");
  if (!ctx) return Promise.resolve(null);
  ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => canvas.toBlob((blob) => resolve(blob), "image/jpeg", 0.82));
}

/** Miniatura e dimensões geradas no navegador; se falhar, o upload segue sem miniatura. */
export async function readMediaInfo(file: File, kind: AssetKind): Promise<MediaInfo> {
  try {
    if (kind === "imagem") {
      const bitmap = await createImageBitmap(file);
      const info = { width: bitmap.width, height: bitmap.height, thumb: await drawThumb(bitmap, bitmap.width, bitmap.height) };
      bitmap.close();
      return info;
    }
    if (kind === "video") {
      const src = URL.createObjectURL(file);
      try {
        const video = document.createElement("video");
        video.muted = true; video.playsInline = true; video.preload = "metadata"; video.src = src;
        await new Promise<void>((resolve, reject) => { video.onloadedmetadata = () => resolve(); video.onerror = () => reject(new Error("video")); });
        const duration = Number.isFinite(video.duration) ? video.duration : undefined;
        video.currentTime = Math.min(1, (duration || 2) / 2);
        await new Promise<void>((resolve, reject) => { video.onseeked = () => resolve(); video.onerror = () => reject(new Error("video")); });
        return { width: video.videoWidth || undefined, height: video.videoHeight || undefined, duration,
          thumb: video.videoWidth ? await drawThumb(video, video.videoWidth, video.videoHeight) : null };
      } finally { URL.revokeObjectURL(src); }
    }
  } catch { /* formato que o navegador não decodifica (ex.: HEVC): sem miniatura */ }
  return { thumb: null };
}

export async function uploadAsset(file: File, options: { folder?: string | null; tags?: string[] }, onProgress?: (fraction: number) => void): Promise<StudioAsset> {
  const checked = checkFile(file);
  if ("error" in checked) throw new Error(checked.error);
  const info = await readMediaInfo(file, checked.kind);
  const ticket = await http<UploadTicket>(base("/assets/upload-url"), { method: "POST", body: JSON.stringify({
    file_name: file.name, mime_type: checked.mime, size_bytes: file.size, folder: options.folder || undefined,
    tags: options.tags || [], with_thumb: Boolean(info.thumb),
  }) });
  await putToSignedUrl(ticket.upload.signed_url, file, checked.mime, (f) => onProgress?.(f * 0.97));
  if (info.thumb && ticket.thumb_upload) {
    await putToSignedUrl(ticket.thumb_upload.signed_url, info.thumb, "image/jpeg").catch(() => undefined);
  }
  const confirmed = await http<{ asset: StudioAsset }>(base(`/assets/${encodeURIComponent(ticket.asset.id)}/confirm`), { method: "POST", body: JSON.stringify({
    width: info.width ? Math.round(info.width) : undefined, height: info.height ? Math.round(info.height) : undefined,
    duration_seconds: info.duration != null ? Math.round(info.duration * 100) / 100 : undefined,
  }) });
  onProgress?.(1);
  return confirmed.asset;
}
