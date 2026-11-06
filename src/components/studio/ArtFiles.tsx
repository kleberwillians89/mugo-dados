import { ChevronLeft, ChevronRight, Film, Link2, X } from "lucide-react";
import { artImage, artKind, artList } from "../../app/artLinks";

const isVideo = (url: string) => /\.(mp4|mov)(\?|$)/i.test(url);

/** Mover um item da lista (ordem = slides do carrossel). */
export function moveArt(list: string[], index: number, delta: number): string[] {
  const to = index + delta;
  if (to < 0 || to >= list.length) return list;
  const next = [...list];
  [next[index], next[to]] = [next[to], next[index]];
  return next;
}

/**
 * Artes do post em miniatura, na ordem dos slides: tirar uma imagem errada ou mudar a ordem sem mexer em link.
 * Só muda o rascunho; vale quando a pessoa salva a pauta.
 */
export default function ArtFiles({ value, onChange, disabled }: { value?: string | null; onChange: (value: string) => void; disabled?: boolean }) {
  const list = artList(value);
  if (!list.length) return null;
  const update = (next: string[]) => onChange(next.join("\n"));
  return <ol className="artFiles" aria-label="Artes do post, na ordem dos slides">
    {list.map((url, i) => {
      const img = artImage(url);
      const kind = artKind(url);
      return <li key={`${url}-${i}`} className="artFile">
        <span className="artFileThumb">
          {img ? <img src={img} alt="" loading="lazy" /> : isVideo(url) ? <Film size={22} aria-hidden="true" /> : <Link2 size={20} aria-hidden="true" />}
          <i>{i + 1}</i>
        </span>
        <small>{img ? (kind === "drive" ? "Drive" : "Imagem") : isVideo(url) ? "Vídeo" : kind === "canva" ? "Canva" : "Link"}</small>
        <span className="artFileActions">
          <button type="button" aria-label={`Mover arte ${i + 1} para a esquerda`} disabled={disabled || i === 0} onClick={() => update(moveArt(list, i, -1))}><ChevronLeft size={14} /></button>
          <button type="button" aria-label={`Mover arte ${i + 1} para a direita`} disabled={disabled || i === list.length - 1} onClick={() => update(moveArt(list, i, 1))}><ChevronRight size={14} /></button>
          <button type="button" className="is-remove" aria-label={`Tirar arte ${i + 1}`} disabled={disabled} onClick={() => update(list.filter((_, j) => j !== i))}><X size={14} /></button>
        </span>
      </li>;
    })}
  </ol>;
}
