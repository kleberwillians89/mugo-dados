import whiteWordmark from "../assets/mugo-logo.png";

export const MUGO_LOGO_ASSETS = {
  wordmark: "/brand/mugo.png",
  wordmarkInverse: whiteWordmark,
  symbol: "/brand/mugo-symbol.png",
  /** Logo 3D (quadro de frente do vídeo), fundo transparente. */
  mark3d: "/brand/mugo-3d-mark.png",
} as const;

/** Logo 3D girando (vídeo leve, sem som, em loop). Pôster = mesmo quadro do logo parado. */
export const MUGO_LOGO_VIDEO = { mp4: "/brand/mugo-3d.mp4", poster: "/brand/mugo-3d-poster.jpg" } as const;

/** Nome do produto como aparece na marca. */
export const PRODUCT_WORDMARK = "MUGOVERSO";

type MugoLogoVariant = keyof typeof MUGO_LOGO_ASSETS | "responsive";

type Props = {
  variant?: MugoLogoVariant;
  className?: string;
  alt?: string;
};

export default function MugoLogo({ variant = "wordmark", className = "", alt = "Mugô" }: Props) {
  if (variant === "responsive") {
    return (
      <span className={`mugoLogo mugoLogoResponsive ${className}`.trim()}>
        <img src={MUGO_LOGO_ASSETS.symbol} alt={alt} />
      </span>
    );
  }

  return (
    <span className={`mugoLogo mugoLogo-${variant} ${className}`.trim()}>
      <img src={MUGO_LOGO_ASSETS[variant]} alt={alt} />
    </span>
  );
}
