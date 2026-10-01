/** Área útil da marca dentro do asset quadrado, em frações (0–1). */
export type LogoCrop = { x: number; y: number; w: number; h: number };

export type ClientBrand = {
  displayName: string;
  /** Asset quadrado em public/clients/ (avatar e cabeçalho), usado sem alteração. */
  logo: string;
  /** Área útil da marca dentro do asset, usada nos cabeçalhos (escala uniforme, sem distorção). */
  logoCrop?: LogoCrop;
  /** O nome da empresa é legível na própria marca: no cabeçalho ele não se repete visualmente. */
  nameInLogo?: boolean;
  /** Imagem de marca (ilustração com fundo próprio), não wordmark: exibida inteira, sem recorte. */
  logoIsImage?: boolean;
  /** Asset horizontal já recortado para cabeçalhos; quando existir, tem prioridade. */
  wordmark?: string;
  fallback: string;
};

// Assets oficiais (512 × 512) de Mugô, Curavino, Roove, Origami, Ruah e Latina:
// logoCrop = caixa dos pixels visíveis (alfa > 24), medida nos próprios arquivos.
// Amalie, Cafifa e Santo Circuito seguem com os assets anteriores (320 × 320,
// recorte medido com ~1,5% de folga).
// Ruah: o nome escrito no emblema fica ilegível no tamanho do cabeçalho, então
// o nome aparece em texto ao lado da marca.
const CLIENT_BRANDS: Record<string, ClientBrand> = {
  mugo: { displayName: "Mugô", logo: "/clients/mugo.png", logoCrop: { x: .039, y: .246, w: .934, h: .436 }, nameInLogo: true, fallback: "M" },
  curavino: { displayName: "Curavino", logo: "/clients/curavino.png", logoCrop: { x: 0, y: .424, w: 1, h: .152 }, nameInLogo: true, fallback: "C" },
  roove: { displayName: "Roove", logo: "/clients/roove.png", logoCrop: { x: .014, y: .406, w: .978, h: .19 }, nameInLogo: true, fallback: "R" },
  origami: { displayName: "Origami", logo: "/clients/origami.png", logoCrop: { x: .033, y: .359, w: .897, h: .284 }, nameInLogo: true, fallback: "O" },
  ruahparfums: { displayName: "Ruah Parfums", logo: "/clients/ruahparfums.png", logoCrop: { x: .176, y: .066, w: .648, h: .807 }, fallback: "RP" },
  latina: { displayName: "Latina", logo: "/clients/latina.png", logoIsImage: true, fallback: "L" },
  amalie: { displayName: "Amalie", logo: "/clients/amalie.png", logoCrop: { x: .275, y: .255, w: .45, h: .47 }, fallback: "A" },
  cafifa: { displayName: "Cafifa", logo: "/clients/cafifa.png", logoCrop: { x: .245, y: .285, w: .47, h: .41 }, nameInLogo: true, fallback: "C" },
  santocircuito: { displayName: "Santo Circuito", logo: "/clients/santocircuito.png", logoCrop: { x: .235, y: .335, w: .53, h: .3 }, nameInLogo: true, fallback: "SC" },
};

// Mapeamento frontend temporário: id (ou nome normalizado) do tenant → marca registrada acima.
const CLIENT_ALIASES: Record<string, string> = {
  "ruah-parfums": "ruahparfums",
  ruah: "ruahparfums",
  "santo-circuito": "santocircuito",
  vinhos: "curavino",
  "mugo-agencia": "mugo",
  mugoagencia: "mugo",
};

/** "Mugô Agência" → "mugoagencia": casa o nome exibido do tenant com o registro. */
function brandKeyFromName(value: string): string {
  return value.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

export function getClientBrand(clientId: string, displayName?: string): ClientBrand {
  const normalized = String(clientId || "").trim().toLowerCase();
  const byName = brandKeyFromName(String(displayName || ""));
  const key = [CLIENT_ALIASES[normalized] || normalized, CLIENT_ALIASES[byName] || byName]
    .find((candidate) => Boolean(candidate && CLIENT_BRANDS[candidate]));
  if (key) return CLIENT_BRANDS[key];
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
