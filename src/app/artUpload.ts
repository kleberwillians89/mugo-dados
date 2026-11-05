import { http, clientClientPath } from "./api";

type Target = { upload_url: string; public_url: string; content_type: string };

/** A Meta só publica imagem em JPEG: PNG/WEBP/HEIC viram JPEG aqui no navegador antes de subir. */
export async function toJpeg(file: File): Promise<Blob> {
  if (file.type === "image/jpeg") return file;
  const bitmap = await createImageBitmap(file);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width; canvas.height = bitmap.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Não foi possível converter a imagem.");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height); // transparência vira branco
  ctx.drawImage(bitmap, 0, 0);
  return await new Promise<Blob>((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Falha ao converter a imagem."))), "image/jpeg", 0.92));
}

/** Envia um arquivo direto ao Storage (link assinado gerado pelo backend) e devolve o link público. */
/** itemId vazio/null = pauta ainda não criada: a arte sobe antes e o link entra na pauta ao salvar. */
export async function uploadArt(itemId: string | null, file: File): Promise<string> {
  const isVideo = file.type === "video/mp4" || file.type === "video/quicktime";
  if (!isVideo && !file.type.startsWith("image/")) throw new Error("Envie imagem (JPG/PNG) ou vídeo MP4/MOV.");
  const body = isVideo ? file : await toJpeg(file);
  const contentType = isVideo ? file.type : "image/jpeg";
  const path = itemId ? `/studio/calendar/items/${encodeURIComponent(itemId)}/art/upload` : "/studio/calendar/art/upload";
  const target = await http<Target>(clientClientPath(path),
    { method: "POST", body: JSON.stringify({ content_type: contentType }) });
  const response = await fetch(target.upload_url, { method: "PUT", body, headers: { "Content-Type": contentType, "x-upsert": "false" } });
  if (!response.ok) throw new Error(`O envio do arquivo falhou (${response.status}).`);
  return target.public_url;
}
