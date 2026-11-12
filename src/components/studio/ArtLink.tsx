import { Palette } from "lucide-react";
/** Link da arte (Canva, Google Drive ou outro https) com prévia quando o serviço permite. */

import { artKind, canvaEmbed, driveId, type ArtKind } from "../../app/artLinks";

const LABEL: Record<ArtKind, string> = { canva: "Ver arte no Canva", drive: "Ver arte no Drive", outro: "Ver arte" };

export default function ArtLink({ url, preview = true, count = 1 }: { url?: string | null; preview?: boolean; count?: number }) {
  if (!url) return null;
  const kind = artKind(url);
  const drive = kind === "drive" ? driveId(url) : null;
  const canva = kind === "canva" ? canvaEmbed(url) : null;
  return <div className="artLink">
    <a className="ds-button" href={url} target="_blank" rel="noreferrer noopener"><Palette className="uiGlyph" size={14} aria-hidden="true" /> {LABEL[kind]}{count > 1 ? ` (${count} slides)` : ""} ↗</a>
    {preview && drive ? <img className="artPreview" loading="lazy" alt="Prévia da arte" src={`https://drive.google.com/thumbnail?id=${drive}&sz=w800`}
      onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} /> : null}
    {preview && canva ? <iframe className="artPreview is-canva" loading="lazy" title="Prévia da arte no Canva" src={canva} allowFullScreen /> : null}
    {preview && (drive || canva) ? <small>A prévia só aparece se o link estiver como "qualquer pessoa com o link pode ver".</small> : null}
  </div>;
}
