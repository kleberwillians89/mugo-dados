import { useState, type ImgHTMLAttributes } from "react";
import { getClientBrand, PLATFORM_LOGOS, type PlatformBrand } from "../app/brandRegistry";

type BaseLogoProps = {
  src: string;
  alt: string;
  fallback: string;
  className?: string;
  size?: number;
  loading?: ImgHTMLAttributes<HTMLImageElement>["loading"];
};

export function BrandLogo({ src, alt, fallback, className = "", size = 36, loading = "eager" }: BaseLogoProps) {
  const [failed, setFailed] = useState(false);
  const style = { width: size, height: size };
  if (!src || failed) {
    return <span className={`brandLogo brandLogoFallback ${className}`.trim()} style={style} aria-label={alt}>{fallback}</span>;
  }
  return (
    <img
      className={`brandLogo ${className}`.trim()}
      src={src}
      alt={alt}
      width={size}
      height={size}
      loading={loading}
      onError={() => setFailed(true)}
    />
  );
}

export function ClientLogo({ clientId, displayName, size = 36, className = "" }: {
  clientId: string; displayName?: string; size?: number; className?: string;
}) {
  const brand = getClientBrand(clientId, displayName);
  return <BrandLogo src={brand.logo} alt={`Logo ${brand.displayName}`} fallback={brand.fallback} size={size} className={className} />;
}

export function PlatformLogo({ platform, size = 32, className = "" }: {
  platform: PlatformBrand; size?: number; className?: string;
}) {
  return <BrandLogo src={PLATFORM_LOGOS[platform]} alt={`Logo ${platform}`} fallback={platform.slice(0, 2).toUpperCase()} size={size} loading="lazy" className={className} />;
}
