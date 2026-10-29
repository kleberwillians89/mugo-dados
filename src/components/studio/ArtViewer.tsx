import { useRef, useState } from "react";
import type { StudioAsset } from "../../app/studioAssets";

/** Arte real do post: imagem, vídeo (Reels) ou carrossel deslizável. */
export default function ArtViewer({ assets, label }: { assets: StudioAsset[]; label?: string }) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const [active, setActive] = useState(0);
  const slides = assets.filter((a) => a.url && a.kind !== "pdf");
  if (!slides.length) return null;

  function go(index: number) {
    const track = trackRef.current;
    const target = Math.max(0, Math.min(slides.length - 1, index));
    track?.scrollTo?.({ left: target * track.clientWidth, behavior: "smooth" });
    setActive(target);
  }

  return <div className="artViewer" aria-roledescription={slides.length > 1 ? "carrossel" : undefined} aria-label={label}>
    <div className="artTrack" ref={trackRef}
      onScroll={(e) => { const el = e.currentTarget; if (el.clientWidth) setActive(Math.round(el.scrollLeft / el.clientWidth)); }}>
      {slides.map((asset, index) => <div key={asset.id} className="artSlide" aria-label={slides.length > 1 ? `${index + 1} de ${slides.length}` : undefined}>
        {asset.kind === "video"
          ? <video src={asset.url || undefined} poster={asset.thumb_url || undefined} controls playsInline preload="metadata" />
          : <img src={asset.url || undefined} alt={slides.length > 1 ? `Slide ${index + 1}` : "Arte do post"} loading="lazy" draggable={false} />}
      </div>)}
    </div>
    {slides.length > 1 ? <>
      {active > 0 ? <button type="button" className="artNav is-prev" aria-label="Slide anterior" onClick={() => go(active - 1)}>‹</button> : null}
      {active < slides.length - 1 ? <button type="button" className="artNav is-next" aria-label="Próximo slide" onClick={() => go(active + 1)}>›</button> : null}
      <span className="artCount">{active + 1}/{slides.length}</span>
      <span className="igCarouselDots">{slides.map((a, i) => <i key={a.id} className={i === active ? "on" : ""} />)}</span>
    </> : null}
  </div>;
}
