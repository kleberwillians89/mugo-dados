/** Link da arte (Canva, Google Drive ou outro https): tipo e prévia. */

export type ArtKind = "canva" | "drive" | "outro";

export function artKind(url: string): ArtKind {
  try {
    const host = new URL(url).hostname;
    if (host.endsWith("canva.com") || host.endsWith("canva.link")) return "canva";
    if (host === "drive.google.com" || host === "docs.google.com") return "drive";
  } catch { /* link inválido cai em "outro" */ }
  return "outro";
}

/** Id do arquivo do Drive em /file/d/<id>/… ou ?id=<id>. */
export function driveId(url: string): string | null {
  const m = url.match(/\/d\/([A-Za-z0-9_-]{10,})/) || url.match(/[?&]id=([A-Za-z0-9_-]{10,})/);
  return m ? m[1] : null;
}

/** Canva: /design/<id>/<token>/view vira /view?embed (só abre se o link estiver público). */
export function canvaEmbed(url: string): string | null {
  const m = url.match(/canva\.com\/design\/([A-Za-z0-9_-]+)(?:\/([A-Za-z0-9_-]+))?/);
  return m ? `https://www.canva.com/design/${m[1]}${m[2] && m[2] !== "view" && m[2] !== "edit" ? `/${m[2]}` : ""}/view?embed` : null;
}

/** Imagem que dá para mostrar direto na prévia do post: miniatura do Drive ou link de imagem. Canva fica no botão. */
export function artImage(url?: string | null): string | null {
  if (!url || !url.startsWith("https://")) return null;
  if (artKind(url) === "drive") {
    const id = driveId(url);
    return id ? `https://drive.google.com/thumbnail?id=${id}&sz=w1200` : null;
  }
  return /\.(jpe?g|png|webp|gif)(\?|$)/i.test(url) ? url : null;
}

/** "Link da arte" aceita um link por linha (um por slide do carrossel, na ordem). */
export function artList(value?: string | null): string[] {
  return (value || "").split(/\s+/).map((s) => s.trim()).filter((s) => s.startsWith("https://")).slice(0, 12);
}

/** Imagens que dá para mostrar na prévia, na ordem dos slides. */
export function artImages(value?: string | null): string[] {
  return artList(value).map(artImage).filter((u): u is string => Boolean(u));
}
