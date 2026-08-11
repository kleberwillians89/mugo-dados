export type ClientBrand = {
  displayName: string;
  logo: string;
  fallback: string;
};

const CLIENT_BRANDS: Record<string, ClientBrand> = {
  amalie: { displayName: "Amalie", logo: "/clients/amalie.png", fallback: "A" },
  roove: { displayName: "Roove", logo: "/clients/roove.png", fallback: "R" },
  ruahparfums: { displayName: "Ruah Parfums", logo: "/clients/ruahparfums.png", fallback: "RP" },
  origami: { displayName: "Origami", logo: "/clients/origami.png", fallback: "O" },
  cafifa: { displayName: "Cafifa", logo: "/clients/cafifa.png", fallback: "C" },
  santocircuito: { displayName: "Santo Circuito", logo: "/clients/santocircuito.png", fallback: "SC" },
  curavino: { displayName: "Curavino", logo: "/clients/curavino.png", fallback: "C" },
};

const CLIENT_ALIASES: Record<string, string> = {
  "ruah-parfums": "ruahparfums",
  "santo-circuito": "santocircuito",
};

export function getClientBrand(clientId: string, displayName?: string): ClientBrand {
  const normalized = String(clientId || "").trim().toLowerCase();
  const key = CLIENT_ALIASES[normalized] || normalized;
  const known = CLIENT_BRANDS[key];
  if (known) return known;
  const name = String(displayName || clientId || "Cliente").trim();
  return { displayName: name, logo: "", fallback: name.slice(0, 2).toUpperCase() || "CL" };
}

export const PLATFORM_LOGOS = {
  meta: "/platforms/meta.png",
  instagram: "/platforms/instagram.png",
  facebook: "/platforms/facebook.png",
  tiktok: "/platforms/tiktok.png",
  pinterest: "/platforms/pinterest.png",
  googleads: "/platforms/googleads.png",
  googlemerchant: "/platforms/googlemerchant.png",
  ecommerce: "/platforms/ecommerce.png",
} as const;

export type PlatformBrand = keyof typeof PLATFORM_LOGOS;

export const INTEGRATION_PLATFORM_BRANDS = {
  meta: "meta",
  ga4: "googleads",
  google_ads: "googleads",
  shopify: "ecommerce",
  fbits: "ecommerce",
  merchant_center: "googlemerchant",
  tiktok: "tiktok",
  pinterest: "pinterest",
} as const satisfies Record<string, PlatformBrand>;

export type IntegrationBrandId = keyof typeof INTEGRATION_PLATFORM_BRANDS;

export function getIntegrationPlatformBrand(id: string): PlatformBrand | null {
  return INTEGRATION_PLATFORM_BRANDS[id as IntegrationBrandId] || null;
}
