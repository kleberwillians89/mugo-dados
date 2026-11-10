import { useRef, useState } from "react";
import { isArtVideo } from "../../app/artLinks";
import { feedRatio } from "./artCarousel.helpers";

/** Carrossel como no Instagram: um slide por vez, setas, bolinhas e deslize no celular. */

export default function ArtCarousel({ images, onBroken, onRatio }: { images: string[]; onBroken?: () => void; onRatio?: (ratio: number) => void }) {
  const track = useRef<HTMLDivElement | null>(null);
  const [index, setIndex] = useState(0);
  const go = (i: number) => {
    const el = track.current;
    if (!el) return;
    const next = Math.max(0, Math.min(images.length - 1, i));
    el.scrollTo({ left: next * el.clientWidth, behavior: "smooth" });
    setIndex(next);
  };
  return <div className="artCarousel">
    <div className="artTrack" ref={track} onScroll={(e) => {
      const el = e.currentTarget;
      if (el.clientWidth) setIndex(Math.round(el.scrollLeft / el.clientWidth));
    }}>
      {images.map((src, i) => isArtVideo(src)
        ? <video key={src + i} src={src} controls muted playsInline loop preload="metadata" aria-label={`Vídeo, slide ${i + 1} de ${images.length}`}
            onError={i === 0 ? onBroken : undefined}
            onLoadedMetadata={i === 0 && onRatio ? (e) => onRatio(feedRatio(e.currentTarget.videoWidth, e.currentTarget.videoHeight)) : undefined} />
        : <img key={src + i} src={src} alt={`Slide ${i + 1} de ${images.length}`} loading={i < 2 ? "eager" : "lazy"}
            onError={i === 0 ? onBroken : undefined} draggable={false}
            onLoad={i === 0 && onRatio ? (e) => onRatio(feedRatio(e.currentTarget.naturalWidth, e.currentTarget.naturalHeight)) : undefined} />)}
    </div>
    {images.length > 1 ? <>
      {index > 0 ? <button type="button" className="artNav is-prev" aria-label="Slide anterior" onClick={() => go(index - 1)}>‹</button> : null}
      {index < images.length - 1 ? <button type="button" className="artNav is-next" aria-label="Próximo slide" onClick={() => go(index + 1)}>›</button> : null}
      <span className="artCount">{index + 1}/{images.length}</span>
      <span className="artDots" aria-hidden="true">{images.map((_, i) => <i key={i} className={i === index ? "on" : ""} />)}</span>
    </> : null}
  </div>;
}
