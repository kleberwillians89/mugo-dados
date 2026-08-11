import whiteWordmark from "../assets/mugo-logo.png";

export const MUGO_LOGO_ASSETS = {
  wordmark: "/brand/mugo.png",
  wordmarkInverse: whiteWordmark,
  symbol: "/brand/mugo-symbol.png",
} as const;

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
