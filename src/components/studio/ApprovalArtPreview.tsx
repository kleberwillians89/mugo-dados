import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { Expand, X } from "lucide-react";
import { isArtVideo } from "../../app/artLinks";
import ArtCarousel from "./ArtCarousel";
import { approvalRatio } from "./artCarousel.helpers";

/**
 * Prévia de aprovação: a arte SEMPRE inteira (contain), numa moldura com a proporção da própria peça —
 * Stories/Reels 9:16; feed/carrossel/vídeo pela arte (4:5 a 1,91:1). Desktop = post aberto no navegador
 * (arte à esquerda, legenda à direita); Mobile = celular, tudo empilhado e rolando.
 * "Ver arte completa" abre o slide atual ampliado, sem alterar o arquivo.
 * Quem usa passa `key` com as artes, para a moldura recomeçar ao trocar de peça.
 */
export default function ApprovalArtPreview({ slides, format, mode, account, caption, meta, fallback }: {
  slides: string[]; format: string | null | undefined; mode: "desktop" | "mobile";
  account: string; caption: ReactNode; meta?: ReactNode; fallback: ReactNode;
}) {
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [index, setIndex] = useState(0);
  const [full, setFull] = useState(false);
  const ratio = approvalRatio(format, size?.w, size?.h);
  const vertical = ratio < 0.7;
  const style = { "--art-ratio": String(ratio) } as CSSProperties;

  const media = <div className={`approvalMedia${vertical ? " is-vertical" : ""}`} style={style}>
    {slides.length ? <ArtCarousel images={slides} onSize={(w, h) => setSize({ w, h })} onIndex={setIndex} /> : <div className="approvalMediaFallback">{fallback}</div>}
    {slides.length ? <button type="button" className="approvalFullButton" onClick={() => setFull(true)}><Expand size={14} aria-hidden="true" /> Ver arte completa</button> : null}
  </div>;
  const head = <div className="approvalPostHead"><span className="approvalAvatar" aria-hidden="true">{account.slice(0, 2).toUpperCase()}</span><b>{account}</b></div>;

  return <>
    {mode === "desktop"
      ? <div className="approvalBrowser" aria-label="Prévia no navegador">
          <div className="approvalBrowserBar"><span /><span /><span /><i>instagram.com/{account.toLowerCase().replace(/[^a-z0-9._]/g, "")}</i></div>
          <div className={`approvalBrowserPost${vertical ? " is-vertical" : ""}`}>
            <div className="approvalBrowserMedia">{media}</div>
            <aside className="approvalBrowserSide">{head}<div className="approvalCaption">{caption}</div>{meta ? <small className="approvalMeta">{meta}</small> : null}</aside>
          </div>
        </div>
      : <div className="approvalPhone" aria-label="Prévia no celular">
          <div className="approvalPhoneScreen">
            <div className="approvalPhoneStatus"><b>9:41</b><span aria-hidden="true">●●● ▮</span></div>
            {vertical ? null : head}
            {media}
            {vertical ? <div className="approvalPhoneOverlayHead">{head}</div> : null}
            <div className="approvalCaption">{caption}</div>
            {meta ? <small className="approvalMeta">{meta}</small> : null}
          </div>
        </div>}
    {full && slides.length ? <ArtLightbox src={slides[Math.min(index, slides.length - 1)]} index={index} total={slides.length} onClose={() => setFull(false)} /> : null}
  </>;
}

function ArtLightbox({ src, index, total, onClose }: { src: string; index: number; total: number; onClose: () => void }) {
  const [zoom, setZoom] = useState(false);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return <div className="approvalLightbox" role="dialog" aria-modal="true" aria-label={`Arte completa, slide ${index + 1} de ${total}`} onClick={onClose}>
    <button type="button" className="approvalLightboxClose" aria-label="Fechar" onClick={onClose}><X size={20} aria-hidden="true" /></button>
    <div className={`approvalLightboxBody${zoom ? " is-zoom" : ""}`} onClick={(event) => event.stopPropagation()}>
      {isArtVideo(src) ? <video src={src} controls autoPlay playsInline />
        : <img src={src} alt={`Arte completa, slide ${index + 1} de ${total}`} title={zoom ? "Clique para caber na tela" : "Clique para ver no tamanho original"}
            onClick={() => setZoom((v) => !v)} />}
    </div>
    {total > 1 ? <small className="approvalLightboxCount">{index + 1}/{total}</small> : null}
  </div>;
}
