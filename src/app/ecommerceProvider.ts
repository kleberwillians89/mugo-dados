import type { ClientIntegrationConnection } from "./types";

export type EcommerceProvider = "shopify" | "fbits";

export const ECOMMERCE_PROVIDERS: readonly EcommerceProvider[] = ["shopify", "fbits"];

export type EcommerceProviderResolution =
  | { state: "none"; provider: null; candidates: EcommerceProvider[]; connections: ClientIntegrationConnection[] }
  | { state: "resolved"; provider: EcommerceProvider; candidates: EcommerceProvider[]; connections: ClientIntegrationConnection[] }
  | { state: "ambiguous"; provider: null; candidates: EcommerceProvider[]; connections: ClientIntegrationConnection[] };

function providerOf(entry: ClientIntegrationConnection): EcommerceProvider | null {
  const provider = String(entry?.provider || "").trim().toLowerCase();
  return (ECOMMERCE_PROVIDERS as readonly string[]).includes(provider) ? (provider as EcommerceProvider) : null;
}

/**
 * Conexão de e-commerce ativa = linha do contrato canônico do tenant com
 * provider shopify/fbits e status diferente de "disconnected". Erros de
 * sincronização/autorização continuam indicando qual plataforma a empresa
 * usa; a página do provider é quem mostra o erro. Existência de pedidos não
 * entra nesta decisão.
 */
export function isActiveEcommerceConnection(entry: ClientIntegrationConnection): boolean {
  return providerOf(entry) !== null && String(entry?.status || "").trim().toLowerCase() !== "disconnected";
}

/**
 * Resolve o provider de e-commerce da empresa ativa a partir das conexões do
 * próprio tenant. Com Shopify e FBITS ativos ao mesmo tempo não há regra
 * canônica de preferência: retorna "ambiguous" até existir escolha explícita.
 */
export function resolveActiveEcommerceProvider(
  connections: ClientIntegrationConnection[] | null | undefined,
  chosen?: EcommerceProvider | null,
): EcommerceProviderResolution {
  const active = (connections || []).filter(isActiveEcommerceConnection);
  const candidates = ECOMMERCE_PROVIDERS.filter((provider) => active.some((entry) => providerOf(entry) === provider));
  const forProvider = (provider: EcommerceProvider) => active.filter((entry) => providerOf(entry) === provider);
  if (candidates.length === 0) return { state: "none", provider: null, candidates, connections: [] };
  if (candidates.length === 1) {
    return { state: "resolved", provider: candidates[0], candidates, connections: forProvider(candidates[0]) };
  }
  if (chosen && candidates.includes(chosen)) {
    return { state: "resolved", provider: chosen, candidates, connections: forProvider(chosen) };
  }
  return { state: "ambiguous", provider: null, candidates, connections: active };
}

/** Conectado mas ainda sem nenhuma sincronização registrada. */
export function isEcommerceSyncPending(connections: ClientIntegrationConnection[]): boolean {
  return connections.length > 0 && connections.every((entry) => !entry.last_sync_at && !entry.last_error);
}
