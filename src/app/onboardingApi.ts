/**
 * Integrações e onboarding (conectar Meta, Google, Shopify; escolher contas; sincronizar).
 * Separado de api.ts para não ir junto em toda tela: só a tela de Integrações/Onboarding carrega este arquivo.
 */
import { ApiError, clientClientPath, http, isUsableGoogleConnection,
  type GenericConnection, type ManualMetaAssetsPayload, type MetaOrganicActivation } from "./api";
import { getActiveClientId } from "./activeClient";
import type {
  MetaDiscoverAssetsResponse,
  MetaOauthStartResponse,
  RefreshAllResponse,
} from "./types";

type JsonRecord = Record<string, unknown>;
function positiveInt(value: unknown, fallback: number): number {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return fallback;
  return Math.max(1, Math.floor(n));
}

export async function startClientMetaOAuth(): Promise<MetaOauthStartResponse> {
  return http<MetaOauthStartResponse>(
    `/api/oauth/meta/start?client_id=${encodeURIComponent(getActiveClientId())}`
  );
}

export async function startGoogleOAuth(
  product: "ga4" | "google_ads"
): Promise<{ ok: boolean; integration_product: string; authorization_url: string }> {
  const routeProduct = product === "google_ads" ? "ads" : "ga4";
  return http<{ ok: boolean; integration_product: string; authorization_url: string }>(
    `/api/oauth/google/${routeProduct}/start`
  );
}

export async function startShopifyOAuth(
  shopDomain: string
): Promise<{ ok: boolean; authorization_url: string; shop_domain: string }> {
  return http<{ ok: boolean; authorization_url: string; shop_domain: string }>(
    `/api/oauth/shopify/start?shop=${encodeURIComponent(shopDomain)}`
  );
}

export async function selectShopifyConnection(
  connectionId: string
): Promise<JsonRecord> {
  return http(`/api/oauth/shopify/${encodeURIComponent(connectionId)}/select`, {
    method: "POST",
  });
}

export async function syncShopifyConnection(
  connectionId: string,
  days = 30
): Promise<JsonRecord> {
  return http(
    `/api/oauth/shopify/${encodeURIComponent(connectionId)}/sync?days=${positiveInt(days, 30)}`,
    { method: "POST" }
  );
}

export type GoogleGa4Property = {
  account?: string;
  account_name?: string;
  property?: string;
  property_name?: string;
};

export type GoogleGa4Stream = {
  name?: string;
  display_name?: string;
  type?: string;
  web_stream_data?: Record<string, unknown>;
};

export type GoogleAdsAccount = {
  customer_id: string;
  resource_name?: string;
  descriptive_name?: string | null;
  currency_code?: string | null;
  time_zone?: string | null;
  is_manager?: boolean;
  is_test_account?: boolean;
  status?: string | null;
  /** "direct" = acesso direto; "manager" = acessada via conta administradora (MCC). */
  access?: "direct" | "manager";
  login_customer_id?: string | null;
  manager_customer_id?: string | null;
  manager_name?: string | null;
  level?: number;
  /** Código Google ao ler os detalhes DESTA conta (ex.: CUSTOMER_NOT_ENABLED). */
  details_error?: string | null;
  /** Código Google ao listar as contas vinculadas (customer_client) desta MCC. */
  hierarchy_error?: string | null;
  /** Código Google do fallback customer_client_link desta MCC. */
  links_error?: string | null;
};

/** Somente exibição: 1234567890 -> 123-456-7890. */
export function formatGoogleAdsCustomerId(customerId: string | null | undefined): string {
  return String(customerId || "").replace(/(\d{3})(\d{3})(\d{4})/, "$1-$2-$3");
}

/** "Amalie — 123-456-7890" quando há nome; nunca só o ID cru. */
export function formatGoogleAdsAccountLabel(account: GoogleAdsAccount): string {
  const formattedId = account.customer_id.replace(/(\d{3})(\d{3})(\d{4})/, "$1-$2-$3");
  return account.descriptive_name
    ? `${account.descriptive_name} — ${formattedId}`
    : `Conta ${formattedId}`;
}

export async function listGoogleGa4Properties(
  connectionId: string
): Promise<{ ok: boolean; properties: GoogleGa4Property[]; property_count?: number; message?: string | null }> {
  return http(`/api/oauth/google/${encodeURIComponent(connectionId)}/ga4/properties`);
}

export async function selectGoogleGa4Property(
  connectionId: string,
  propertyId: string,
  details?: { accountId?: string; propertyName?: string; streamId?: string }
): Promise<JsonRecord> {
  return http(`/api/oauth/google/${encodeURIComponent(connectionId)}/ga4/select`, {
    method: "POST",
    body: JSON.stringify({
      property_id: propertyId,
      account_id: details?.accountId,
      property_name: details?.propertyName,
      stream_id: details?.streamId,
    }),
  });
}

export async function listGoogleGa4Streams(
  connectionId: string,
  propertyId: string
): Promise<{ ok: boolean; streams: GoogleGa4Stream[] }> {
  return http(
    `/api/oauth/google/${encodeURIComponent(connectionId)}/ga4/streams?property_id=${encodeURIComponent(propertyId)}`
  );
}

export async function listGoogleAdsAccounts(
  connection: GenericConnection,
  activeClientId: string
): Promise<{ ok: boolean; configured?: boolean; reason?: string; accounts?: GoogleAdsAccount[] }> {
  if (!isUsableGoogleConnection(connection, "google_ads", activeClientId)) {
    throw new ApiError("A conexão Google Ads não está ativa. Conecte novamente.", {
      status: 409, code: "GOOGLE_CONNECTION_DISCONNECTED",
    });
  }
  return http(`/api/oauth/google/${encodeURIComponent(connection.id)}/ads/accounts`);
}

export async function selectGoogleAdsAccount(
  connectionId: string,
  customerId: string
): Promise<JsonRecord> {
  // Só o customer_id: o backend resolve login-customer-id, nome e tipo pela
  // hierarquia descoberta na listagem desta conexão.
  return http(`/api/oauth/google/${encodeURIComponent(connectionId)}/ads/select`, {
    method: "POST",
    body: JSON.stringify({ customer_id: customerId }),
  });
}

export async function syncGoogleConnection(connectionId: string): Promise<JsonRecord> {
  return http(`/api/oauth/google/${encodeURIComponent(connectionId)}/sync`, {
    method: "POST",
  });
}

export async function disconnectGenericConnection(
  connection: GenericConnection
): Promise<JsonRecord> {
  const providerPath = connection.provider === "shopify" ? "shopify" : "google";
  return http(`/api/oauth/${providerPath}/${encodeURIComponent(connection.id)}`, {
    method: "DELETE",
  });
}

export async function discoverClientMetaAssets(
  handoff: string
): Promise<MetaDiscoverAssetsResponse> {
  return http<MetaDiscoverAssetsResponse>(
    `/api/oauth/meta/discover-assets?client_id=${encodeURIComponent(getActiveClientId())}&handoff=${encodeURIComponent(handoff)}`
  );
}

export async function configureExistingMetaOrganic(
  connectionId: string
): Promise<MetaDiscoverAssetsResponse> {
  return http<MetaDiscoverAssetsResponse>(
    `/api/oauth/meta/${encodeURIComponent(connectionId)}/configure-organic`,
    { method: "POST" }
  );
}

/** Relista as contas Meta Ads com a autorização salva (direto + Businesses). */
export async function discoverExistingMetaAdAccounts(
  connectionId: string
): Promise<MetaDiscoverAssetsResponse> {
  return http<MetaDiscoverAssetsResponse>(
    `/api/oauth/meta/${encodeURIComponent(connectionId)}/discover-ad-accounts`,
    { method: "POST" }
  );
}

export type ManualMetaAssetsValidation = {
  ok: boolean;
  page?: { id?: string; name?: string } | null;
  instagram?: { id?: string; username?: string; name?: string } | null;
  ad_account?: { id?: string; name?: string; account_status?: number } | null;
};

export async function validateManualMetaAssets(
  connectionId: string,
  payload: ManualMetaAssetsPayload
): Promise<ManualMetaAssetsValidation> {
  return http(`/api/oauth/meta/${encodeURIComponent(connectionId)}/manual-assets/validate`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function saveManualMetaAssets(
  connectionId: string,
  payload: ManualMetaAssetsPayload
): Promise<JsonRecord> {
  return http(`/api/oauth/meta/${encodeURIComponent(connectionId)}/manual-assets`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function activateMetaOrganic(
  authorizationConnectionId: string,
  payload: { page_id: string; instagram_id: string }
): Promise<MetaOrganicActivation> {
  return http(`/api/oauth/meta/${encodeURIComponent(authorizationConnectionId)}/organic/activate`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function linkClientAssets(
  payload: {
    handoff: string;
    business_ids: string[];
    page_ids: string[];
    instagram_ig_user_ids: string[];
    ad_account_ids: string[];
  }
): Promise<JsonRecord> {
  return http<JsonRecord>(clientClientPath("/connections/link-assets"), {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export type MetaAdsSelectableAccount = {
  connection_id: string;
  ad_account_id: string;
  ad_account_name?: string;
  status?: string;
  scopes?: string[];
};

export async function listClientMetaAdsAccounts(): Promise<{ ok: boolean; accounts: MetaAdsSelectableAccount[] }> {
  return http(clientClientPath("/meta-ads/accounts"));
}

export async function selectClientMetaAdsAccount(adAccountId: string): Promise<JsonRecord> {
  return http(clientClientPath("/meta-ads/select"), {
    method: "POST",
    body: JSON.stringify({ ad_account_id: adAccountId }),
  });
}

export async function syncClientMetaAdsAccount(connectionId: string): Promise<JsonRecord> {
  return http(clientClientPath("/meta-ads/sync"), {
    method: "POST",
    // Sem since/until: o backend aplica o período canônico
    // (resolve_period, 30 dias por padrão).
    body: JSON.stringify({ connection_id: connectionId }),
  });
}

export async function disconnectClientConnection(connectionId: string): Promise<JsonRecord> {
  return http<JsonRecord>(clientClientPath(`/connections/${encodeURIComponent(connectionId)}`), {
    method: "DELETE",
  });
}

export async function refreshAll(
  limit = 40,
  options?: { connectionId?: string | null; start?: string; end?: string }
): Promise<RefreshAllResponse> {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  const connectionId = String(options?.connectionId || "").trim();
  const start = String(options?.start || "").trim();
  const end = String(options?.end || "").trim();
  if (connectionId) params.set("connection_id", connectionId);
  if (start && end) {
    params.set("start", start);
    params.set("end", end);
  }
  return http<RefreshAllResponse>(`/api/ig/sync?${params.toString()}`, { method: "POST" });
}

