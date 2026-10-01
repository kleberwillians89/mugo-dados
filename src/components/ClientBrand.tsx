import { useState, type CSSProperties, type ReactNode } from "react";
import { getClientBrand, type LogoCrop } from "../app/brandRegistry";

type Props = {
  clientId: string;
  clientName?: string | null;
  /** Asset horizontal explícito; sem ele, a marca vem do registro (public/clients/). */
  logoAsset?: string | null;
  /** Linha de contexto sob a marca, ex.: "Ecommerce · FBITS". */
  context?: ReactNode;
  titleAs?: "h1" | "h2" | "p" | "span";
  /**
   * "page": identidade no topo da página. "compact": seletor de empresa e
   * barra móvel — mesma lógica de proporção, área menor.
   */
  size?: "page" | "compact";
  /** Só elementos de frase (span): pode ficar dentro de <button>. */
  inline?: boolean;
  className?: string;
  /** Classe extra no elemento do nome (ex.: seletor de empresa). */
  nameClassName?: string;
};

type MarkScale = { area: number; maxHeight: number; maxWidth: number; imageSize: number };

// Peso visual equivalente entre marcas: a caixa tem área constante, limitada
// em altura (marcas verticais) e em largura (wordmarks muito horizontais).
const MARK_SCALE: Record<NonNullable<Props["size"]>, MarkScale> = {
  page: { area: 3800, maxHeight: 56, maxWidth: 200, imageSize: 52 },
  compact: { area: 3000, maxHeight: 40, maxWidth: 176, imageSize: 36 },
};

function markBox(ratio: number, scale: MarkScale): { width: number; height: number } {
  let height = Math.min(Math.sqrt(scale.area / ratio), scale.maxHeight);
  let width = height * ratio;
  if (width > scale.maxWidth) {
    width = scale.maxWidth;
    height = width / ratio;
  }
  return { width: Math.round(width), height: Math.round(height) };
}

/**
 * Mostra só a área útil de um asset quadrado com margem transparente.
 * Escala uniforme: a proporção da marca nunca muda.
 */
function croppedMarkStyles(crop: LogoCrop, scale: MarkScale): { box: CSSProperties; image: CSSProperties } {
  const box = markBox(crop.w / crop.h, scale);
  const size = box.width / crop.w;
  return {
    box,
    image: {
      width: Math.round(size),
      height: Math.round(size),
      marginLeft: -Math.round(crop.x * size),
      marginTop: -Math.round(crop.y * size),
    },
  };
}

/**
 * Identidade da empresa analisada (nunca a marca do produto). Quando a marca
 * já escreve o nome de forma legível, o nome fica só para leitores de tela;
 * emblemas e imagens de marca levam o nome ao lado. Sem asset (ou se a
 * imagem falhar) fica o nome — nunca um logo genérico.
 */
export default function ClientBrand({
  clientId,
  clientName,
  logoAsset,
  context,
  titleAs: Title = "h1",
  size = "page",
  inline = false,
  className = "",
  nameClassName = "",
}: Props) {
  const brand = getClientBrand(clientId, clientName || undefined);
  const name = String(clientName || "").trim() || brand.displayName;
  const wordmark = String(logoAsset || brand.wordmark || "").trim();
  const source = wordmark || brand.logo;
  const scale = MARK_SCALE[size];
  const [failedSource, setFailedSource] = useState<string | null>(null);
  const showMark = Boolean(source) && failedSource !== source;
  const crop = !wordmark && !brand.logoIsImage && brand.logoCrop ? croppedMarkStyles(brand.logoCrop, scale) : null;
  const layout = wordmark ? " is-wordmark" : crop ? " is-cropped" : brand.logoIsImage ? " is-image" : " is-square";
  const imageBox = brand.logoIsImage && !wordmark ? { width: scale.imageSize, height: scale.imageSize } : undefined;
  const nameInMark = showMark && (Boolean(wordmark) || Boolean(brand.nameInLogo));
  const variant = !showMark ? " is-textOnly" : nameInMark ? " is-markOnly" : " is-markWithName";
  const Wrapper = inline ? "span" : "div";
  const Context = inline ? "span" : "p";

  return (
    <Wrapper className={`ds-clientBrand is-${size}${variant}${className ? ` ${className}` : ""}`}>
      {showMark ? (
        // Decorativo: o nome (visível ou para leitor de tela) identifica a empresa.
        <span className={`ds-clientBrandMark${layout}`} style={crop?.box ?? imageBox} aria-hidden="true">
          <img src={source} alt="" style={crop?.image} onError={() => setFailedSource(source)} />
        </span>
      ) : null}
      <Wrapper className="ds-clientBrandText">
        <Title className={`ds-clientBrandName${nameInMark ? " ds-srOnly" : ""}${nameClassName ? ` ${nameClassName}` : ""}`}>{name}</Title>
        {context ? <Context className="ds-clientBrandContext">{context}</Context> : null}
      </Wrapper>
    </Wrapper>
  );
}
