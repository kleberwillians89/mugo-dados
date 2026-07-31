export type IntegrationAvailability =
  | "available"
  | "configuration_unavailable"
  | "platform_update_pending";

export type IntegrationDefinition = {
  id: "meta" | "google" | "shopify" | "merchant_center" | "tiktok" | "pinterest";
  name: string;
  shortName: string;
  category: "marketing" | "analytics" | "commerce";
  availability: IntegrationAvailability;
  resources: string[];
  providerIds: string[];
  actionLabel?: string;
};

export const INTEGRATION_REGISTRY: readonly IntegrationDefinition[] = [
  {
    id: "meta", name: "Meta e Instagram", shortName: "Meta", category: "marketing",
    availability: "available", resources: ["Instagram profissional", "Meta Ads", "Páginas"],
    providerIds: ["meta", "instagram"], actionLabel: "Conectar com Meta",
  },
  {
    id: "google", name: "Google Analytics e Ads", shortName: "Google", category: "analytics",
    availability: "available", resources: ["Google Analytics 4", "Google Ads"],
    providerIds: ["ga4", "google_ads"], actionLabel: "Conectar com Google",
  },
  {
    id: "shopify", name: "Shopify", shortName: "Shopify", category: "commerce",
    availability: "available", resources: ["Pedidos", "Clientes", "Produtos"],
    providerIds: ["shopify"], actionLabel: "Conectar loja",
  },
  {
    id: "merchant_center", name: "Merchant Center", shortName: "Merchant", category: "commerce",
    availability: "configuration_unavailable", resources: ["Catálogo e produtos"],
    providerIds: ["merchant_center"],
  },
  {
    id: "tiktok", name: "TikTok", shortName: "TikTok", category: "marketing",
    availability: "platform_update_pending", resources: ["Conteúdo e mídia"],
    providerIds: ["tiktok"],
  },
  {
    id: "pinterest", name: "Pinterest", shortName: "Pinterest", category: "marketing",
    availability: "platform_update_pending", resources: ["Conteúdo e mídia"],
    providerIds: ["pinterest"],
  },
] as const;

export function unavailableIntegrationLabel(availability: IntegrationAvailability): string {
  if (availability === "platform_update_pending") return "Aguardando atualização da plataforma";
  if (availability === "configuration_unavailable") return "Configuração indisponível";
  return "Não conectado";
}
