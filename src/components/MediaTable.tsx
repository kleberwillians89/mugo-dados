// src/components/MediaTable.tsx
import type { IgMediaItem } from "../app/types";
import { memo, useMemo, useState } from "react";
import { ExternalLink, Play } from "lucide-react";
import { PlatformLogo } from "./BrandLogo";

function badge(mediaType?: string, productType?: string) {
  const pt = (productType || "").toUpperCase();
  if (pt === "REELS") return <span className="badge badgeReels">REEL</span>;
  if (pt === "STORY") return <span className="badge badgeStory">STORY</span>;
  const mt = (mediaType || "").toUpperCase();
  if (mt === "CAROUSEL_ALBUM") return <span className="badge badgeFeed">CAROUSEL</span>;
  return <span className="badge badgeFeed">POST</span>;
}

function labelMediaType(mediaType?: string, productType?: string) {
  const pt = (productType || "").toUpperCase();
  if (pt === "REELS") return "Reels";
  if (pt === "STORY") return "Story";

  const mt = (mediaType || "").toUpperCase();
  if (mt === "CAROUSEL_ALBUM") return "Carrossel";
  if (mt === "IMAGE") return "Imagem";
  if (mt === "VIDEO") return "Vídeo";
  return mt || "—";
}

function num(v?: number) {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function previewFromPermalink(permalink?: string | null): string {
  const p = String(permalink || "").trim();
  if (!p) return "";
  // Fallback público funciona melhor para posts (/p/). Em /reel/ tende a retornar 500.
  try {
    const parsed = new URL(p);
    const path = parsed.pathname.toLowerCase();
    if (!path.startsWith("/p/")) return "";
  } catch {
    return "";
  }
  return `${p.replace(/\/+$/, "")}/media/?size=l`;
}

function isLikelyBlockedIgCdn(url?: string | null): boolean {
  const value = String(url || "").trim();
  if (!value) return false;
  try {
    const hostname = new URL(value).hostname.toLowerCase();
    return hostname.includes("cdninstagram.com") || hostname.startsWith("scontent-");
  } catch {
    return false;
  }
}

function MediaThumb(props: { src?: string | null; alt: string; permalink?: string | null; video?: boolean }) {
  const src = String(props.src || "").trim();
  const fallback = previewFromPermalink(props.permalink);
  const blockedByPolicy = isLikelyBlockedIgCdn(src);
  const preferred = blockedByPolicy ? fallback : src || fallback;
  const [currentSrc, setCurrentSrc] = useState(preferred);
  const [triedFallback, setTriedFallback] = useState(false);
  const [failed, setFailed] = useState(false);

  if (failed || !currentSrc) {
    return (
      <div className="mediaThumb mediaThumbFallback">
        <PlatformLogo platform="instagram" size={32} />
        <span>Prévia indisponível</span>
      </div>
    );
  }

  return (
    <span className="mediaThumbVisual">
      <img
        className="mediaThumb"
        src={currentSrc}
        alt={props.alt}
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => {
          if (!triedFallback && fallback && currentSrc !== fallback) {
            setCurrentSrc(fallback);
            setTriedFallback(true);
            return;
          }
          setFailed(true);
        }}
      />
      {props.video ? <span className="mediaPlay" aria-label="Vídeo"><Play size={19} fill="currentColor" /></span> : null}
    </span>
  );
}

// score simples e bom (ajuste pesos depois se quiser)
function impactScore(m: IgMediaItem) {
  const ins: Record<string, unknown> = m.insights || {};
  const reach = num(ins["reach"] as number | undefined);
  const views = num(ins["views"] as number | undefined);
  const interactions = num(ins["total_interactions"] as number | undefined);
  const saved = num(ins["saved"] as number | undefined);
  const shares = num(ins["shares"] as number | undefined);
  const comments = num(ins["comments"] as number | undefined);
  const likes = num(ins["likes"] as number | undefined);

  const isReels = String(m.media_product_type || "").toUpperCase() === "REELS";

  const score =
    reach * 1 +
    (isReels ? views * 0.7 : 0) +
    interactions * 3 +
    saved * 4 +
    shares * 4 +
    comments * 2 +
    likes * 0.5;

  return Math.round(score);
}

function arrayOrEmpty<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function MediaTable({ media }: { media: IgMediaItem[] }) {
  const rows = useMemo(
    () =>
      [...arrayOrEmpty<IgMediaItem>(media)].sort((a, b) => {
        const sa = impactScore(a);
        const sb = impactScore(b);
        if (sb !== sa) return sb - sa;
        return (b.timestamp || "").localeCompare(a.timestamp || "");
      }),
    [media]
  );

  return (
    <>
      <div className="organicMediaShelf" aria-label="Últimos reels e posts orgânicos">
        {rows.slice(0, 8).map((m) => {
          const ins: Record<string, unknown> = m.insights || {};
          const typeLabel = labelMediaType(m.media_type, m.media_product_type);
          const caption = String(m.caption || "").replace(/\s+/g, " ").trim();
          const date = m.timestamp ? new Date(m.timestamp).toLocaleDateString("pt-BR") : "Sem data";
          const isVideo = typeLabel === "Reels" || typeLabel === "Vídeo";
          return (
            <article className="organicMediaCard" key={`card-${m.id}`}>
              <div className="organicMediaPreview">
                <MediaThumb
                  src={m.thumb_url || m.thumbnail_url || m.media_url}
                  permalink={m.permalink}
                  alt={typeLabel}
                  video={isVideo}
                />
              </div>
              <div className="organicMediaCardBody">
                <div className="organicMediaCardHead">
                  {badge(m.media_type, m.media_product_type)}
                  <span>{date}</span>
                </div>
                <div className="organicMediaCaption">
                  {caption || "Conteúdo orgânico do cliente ativo"}
                </div>
                <div className="organicMediaStats">
                  <span>Alcance <strong>{num(ins["reach"] as number | undefined)}</strong></span>
                  <span>Interações <strong>{num(ins["total_interactions"] as number | undefined)}</strong></span>
                  <span>Comentários <strong>{num(ins["comments"] as number | undefined)}</strong></span>
                </div>
                {m.permalink ? (
                  <a className="organicMediaLink" href={m.permalink} target="_blank" rel="noreferrer">
                    Ver no Instagram <ExternalLink size={14} aria-hidden="true" />
                  </a>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
      <div className="tableWrap">
      <div className="tableScroller">
        <table className="mediaTable">
          <thead>
            <tr>
              <th>Mídia</th>
              <th>Tipo</th>
              <th>Data</th>
              <th>Legenda</th>
              <th>Reach</th>
              <th>Curtidas</th>
              <th>Comentários</th>
              <th>Salvamentos</th>
            </tr>
          </thead>

          <tbody>
            {rows.map((m) => {
              const ins: Record<string, unknown> = m.insights || {};

              const date = (m.timestamp || "").slice(0, 10);
              const typeLabel = labelMediaType(m.media_type, m.media_product_type);
              const caption = m.caption || "—";

              return (
                <tr key={m.id}>
                  <td>
                    <div className="mediaThumbWrap">
                      <MediaThumb
                        src={m.thumb_url || m.thumbnail_url || m.media_url}
                        permalink={m.permalink}
                        alt={typeLabel}
                        video={typeLabel === "Reels" || typeLabel === "Vídeo"}
                      />
                    </div>
                  </td>
                  <td>{badge(m.media_type, m.media_product_type)}</td>

                  <td className="cellMuted">{date || "—"}</td>

                  <td className="cellClamp" title={caption}>{caption}</td>
                  <td>{num(ins["reach"] as number | undefined)}</td>
                  <td>{num(ins["likes"] as number | undefined)}</td>
                  <td>{num(ins["comments"] as number | undefined)}</td>
                  <td>{num(ins["saved"] as number | undefined)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      </div>
    </>
  );
}

export default memo(MediaTable);
