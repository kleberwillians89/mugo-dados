import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  disconnectClientConnection,
  activateMetaOrganic,
  configureExistingMetaOrganic,
  ApiError,
  disconnectGenericConnection,
  discoverClientMetaAssets,
  linkClientAssets,
  listClientConnections,
  listClientMetaAdsAccounts,
  listGenericConnections,
  getApiVersion,
  isUsableGoogleConnection,
  isUsableMetaConnection,
  selectUsableGoogleConnection,
  selectUsableMetaConnection,
  formatGoogleAdsAccountLabel,
  formatGoogleAdsCustomerId,
  listGoogleAdsAccounts,
  listGoogleGa4Properties,
  listGoogleGa4Streams,
  selectGoogleAdsAccount,
  selectGoogleGa4Property,
  selectClientMetaAdsAccount,
  selectShopifyConnection,
  syncGoogleConnection,
  syncClientMetaAdsAccount,
  syncShopifyConnection,
  validateManualMetaAssets,
  saveManualMetaAssets,
  type GenericConnection,
  type GoogleAdsAccount,
  type GoogleGa4Property,
  type GoogleGa4Stream,
  type MetaAdsSelectableAccount,
  type ManualMetaAssetsValidation,
  startClientMetaOAuth,
  startGoogleOAuth,
  startShopifyOAuth,
} from "../app/api";
import { resolveOperationalMetaConnectionId, selectUniqueConnection } from "../app/connectionManager";
import useClientIntegrations from "../hooks/useClientIntegrations";
import {
  getActiveConnectionId,
  getSelectedConnectionId,
  setActiveConnectionId,
  setSelectedConnectionId,
} from "../app/connectionState";
import type {
  ClientIntegrationConnection,
  MetaConnection,
  MetaDiscoverAssetsResponse,
  MetaDiscoveredAdAccount,
  MetaDiscoveredBusinessManager,
  MetaDiscoveredInstagramAsset,
  MetaDiscoveredPageAsset,
} from "../app/types";
import {
  getActiveClientConfigurationWarning,
  getActiveClient,
  getActiveClientId,
  getActiveClientName,
  MUGO_APP_NAME,
} from "../app/activeClient";
import { describeSyncError, isSyncAlreadyRunningError, runExclusiveSync } from "../app/syncOrchestrator";
import { navigateToExternalAuthorization } from "../app/externalNavigation";
import AssetCombobox from "../components/AssetCombobox";
import FbitsIntegrationPanel from "../components/FbitsIntegrationPanel";
import MugoLogo from "../components/MugoLogo";
import "../components/mugo-logo.css";
import StatusBadge, { type StatusTone } from "../components/StatusBadge";
import { PlatformLogo } from "../components/BrandLogo";
import { getIntegrationPlatformBrand } from "../app/brandRegistry";
import {
  INTEGRATION_REGISTRY,
  unavailableIntegrationLabel,
} from "../app/integrationRegistry";
import { commitsMismatch, FRONTEND_COMMIT_SHA, INTEGRATION_BUILD_FEATURES, shortCommit } from "../buildVersion";
import "../styles/onboarding.css";

type Props = {
  isAuthenticated?: boolean;
  initialError?: string | null;
  onCompleted?: () => Promise<void> | void;
  onLogout?: () => Promise<void> | void;
};

const EMPTY_INTEGRATION_DIAGNOSTIC = {
  code: "", requestId: "", initialSyncOk: null as boolean | null,
  organicConnectionId: "", adsBlockedReason: "", propertyCount: 0,
  streamCount: 0, propertyId: "", streamId: "", ga4LastSync: "",
};

function fmtDate(value?: string | null): string {
  if (!value) return "-";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "-";
  return dt.toLocaleString("pt-BR");
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return `${error.message}${error.code ? ` Código: ${error.code}.` : ""}${error.requestId ? ` Request ID: ${error.requestId}.` : ""}`;
  }
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return fallback;
}

function statusLabel(status: string): string {
  const normalized = String(status || "").toLowerCase();
  if (["active", "connected", "updated"].includes(normalized)) return "Conectado";
  if (["connecting", "importing", "syncing"].includes(normalized)) return "Sincronizando";
  if (["needs_reauth", "reauth_required", "token_expired", "stale"].includes(normalized)) return "Requer atenção";
  if (["error", "sync_error"].includes(normalized)) return "Erro";
  if (normalized === "disconnected") return "Não conectado";
  if (normalized === "selection_required") return "Seleção de conta pendente";
  return normalized ? "Não conectado" : "Não conectado";
}

function connectionTone(status: string): "red" | "yellow" | "green" {
  const normalized = String(status || "").toLowerCase();
  if (["active", "connected", "updated"].includes(normalized)) return "green";
  if (["selection_required", "connecting", "importing", "syncing", "awaiting_authorization", "authorizing"].includes(normalized)) return "yellow";
  return "red";
}

/**
 * Único ponto que decide o estado visual final de um card a partir do
 * contrato canônico (GET /api/clients/{client_id}/integrations). Os
 * endpoints legados (/api/connections, /api/clients/{id}/connections)
 * continuam sendo usados para executar ações, mas nunca mais determinam
 * este texto/tom.
 */
function canonicalStatusLabel(
  entry: ClientIntegrationConnection | undefined,
  isRefreshing: boolean
): string {
  if (!entry) return "Desconectado";
  if (isRefreshing) return "Atualizando…";
  if (entry.status === "disconnected") return "Desconectado";
  if (entry.status === "token_expired") return "Token expirado";
  if (entry.status === "permission_error") return "Permissão insuficiente";
  if (entry.status === "needs_configuration") return "Configuração necessária";
  if (entry.sync_status === "sync_error") return "Erro de sincronização";
  if (entry.sync_status === "sync_success") return "Sincronizado";
  // Commerce: conexão válida ainda sem nenhuma importação concluída é
  // "conectado", nunca "não conectado" — só a primeira carga está pendente.
  if ((entry.provider === "shopify" || entry.provider === "fbits") && !entry.last_sync_at && !entry.last_error) {
    return "Conectado · sincronização pendente";
  }
  return "Conectado";
}

function canonicalStatusTone(entry: ClientIntegrationConnection | undefined): "red" | "yellow" | "green" {
  if (!entry) return "red";
  if (entry.status === "disconnected") return "red";
  if (entry.status === "token_expired" || entry.status === "permission_error") return "red";
  if (entry.status === "needs_configuration") return "yellow";
  if (entry.sync_status === "sync_error") return "yellow";
  return "green";
}

/** Tom do StatusBadge (5 níveis) — distinto do tom de 3 níveis acima, que
 * só controla a borda do card. "Sincronizando" precisa de tom próprio
 * (info/azul, com pulso), diferente de "erro" e de "configuração
 * necessária", que hoje colapsam no mesmo amarelo do card. */
function canonicalStatusBadgeTone(
  entry: ClientIntegrationConnection | undefined,
  isRefreshing: boolean
): StatusTone {
  if (!entry) return "neutral";
  if (isRefreshing) return "info";
  if (entry.status === "disconnected") return "neutral";
  if (entry.status === "token_expired" || entry.status === "permission_error") return "error";
  if (entry.status === "needs_configuration") return "warning";
  if (entry.sync_status === "sync_error") return "error";
  if (entry.sync_status === "sync_success") return "success";
  return "success";
}

const GOOGLE_ADS_STATUS_LABEL: Record<string, string> = {
  CANCELED: "Cancelada", SUSPENDED: "Suspensa", CLOSED: "Encerrada",
};

function googleAdsAccountSubtitle(account: GoogleAdsAccount): string {
  if (account.is_manager) return "Conta administradora";
  if (account.access === "manager" && account.manager_customer_id) {
    const manager = `${account.manager_name ? `${account.manager_name} · ` : ""}${formatGoogleAdsCustomerId(account.manager_customer_id)}`;
    return `Via conta administradora ${manager}`;
  }
  return "Conta de anúncios";
}

function googleAdsAccountStatus(account: GoogleAdsAccount): { label: string; tone: StatusTone } | undefined {
  const status = String(account.status || "").toUpperCase();
  if (!status || status === "ENABLED") return undefined;
  return { label: GOOGLE_ADS_STATUS_LABEL[status] || status, tone: "warning" };
}

function canonicalAccountLabel(entry: ClientIntegrationConnection | undefined): string | null {
  if (!entry) return null;
  if (entry.provider === "google_ads") {
    // Conta de mídia selecionada (nome + ID), nunca o e-mail da autorização.
    const customerId = entry.assets?.customer_id ? formatGoogleAdsCustomerId(entry.assets.customer_id) : null;
    const name = entry.account?.name || null;
    return name && customerId ? `${name} · ${customerId}` : name || customerId;
  }
  const account = entry.account || {};
  const name = account.name || account.domain || null;
  if (name) return name;
  const assets = entry.assets || {};
  return assets.ad_account_name || assets.property_name || assets.instagram_account_name || null;
}

/**
 * Erro técnico bruto (código HTTP, mensagem de API) nunca aparece direto
 * para o cliente — vira uma frase humana com o próximo passo, mantendo o
 * detalhe técnico disponível separadamente para quem precisar dele.
 */
function humanizeIntegrationError(rawError: string, providerName: string): string {
  const normalized = rawError.toLowerCase();
  if (normalized.includes("permission") || normalized.includes("permissão") || normalized.includes("403")) {
    return `A autorização da ${providerName} perdeu uma permissão necessária. Reconecte para continuar atualizando.`;
  }
  if (normalized.includes("token") || normalized.includes("401") || normalized.includes("expired")) {
    return `A conexão com a ${providerName} expirou. Reconecte para retomar as atualizações.`;
  }
  return `Não conseguimos atualizar a ${providerName} agora. Os últimos dados salvos continuam disponíveis.`;
}

function isOrganicConnection(connection: MetaConnection): boolean {
  return (
    String(connection.platform || "").toLowerCase() === "instagram" ||
    String(connection.connection_type || "").toLowerCase() === "organic"
  );
}

function isPaidConnection(connection: MetaConnection): boolean {
  return (
    String(connection.platform || "").toLowerCase() === "meta_ads" ||
    String(connection.connection_type || "").toLowerCase() === "paid"
  );
}

function connectionLabel(connection: MetaConnection): string {
  const username = String(connection.username || "").trim();
  if (username) return username.startsWith("@") ? username : `@${username}`;

  const adAccountName = String(connection.ad_account_name || "").trim();
  if (adAccountName) return adAccountName;

  const igUserId = String(connection.ig_user_id || "").trim();
  if (igUserId) return `Instagram ${igUserId.slice(-6)}`;

  const adAccountId = String(connection.ad_account_id || "").trim();
  if (adAccountId) return `Conta Ads ${adAccountId.replace(/^act_/, "").slice(-6)}`;

  return "Conexao do cliente ativo";
}

const pickDefaultOrganicConnectionId = (connections: MetaConnection[], preferredConnectionId: string | null) =>
  resolveOperationalMetaConnectionId(connections, "organic", preferredConnectionId);

export default function Onboarding({
  isAuthenticated = false,
  initialError = null,
  onCompleted,
  onLogout,
}: Props) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [oauthLoading, setOauthLoading] = useState(false);
  const [shopifyDomain, setShopifyDomain] = useState("");
  const activeRole = String(getActiveClient()?.role || "viewer").toLowerCase();
  // Gerencia integrações: equipe Mugô (qualquer tenant) e o administrador da
  // própria empresa (client_admin/owner). viewer permanece somente-leitura.
  const canManageConnections =
    activeRole === "platform_admin" ||
    activeRole === "agency_admin" ||
    activeRole === "client_admin" ||
    activeRole === "owner" ||
    activeRole === "admin";
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [connections, setConnections] = useState<MetaConnection[]>([]);
  const [genericConnections, setGenericConnections] = useState<GenericConnection[]>([]);
  // Contrato canônico consolidado (Fase 3) — aditivo: enriquece os cards
  // abaixo com status de sync mesclado de integration_connections +
  // meta_connections, sem substituir os fetches existentes desta tela.
  const canonicalIntegrations = useClientIntegrations({ enabled: isAuthenticated });
  const canonicalIntegrationsRefetch = canonicalIntegrations.refetch;
  // Ref em vez de dependência direta: loadConnections só precisa da versão
  // mais recente do refetch canônico, sem precisar mudar de identidade
  // (e sem recascatear o efeito de mount que depende de loadConnections)
  // toda vez que o hook canônico re-renderiza.
  const canonicalIntegrationsRefetchRef = useRef(canonicalIntegrationsRefetch);
  useEffect(() => {
    canonicalIntegrationsRefetchRef.current = canonicalIntegrationsRefetch;
  }, [canonicalIntegrationsRefetch]);
  const [activeConnectionId, setActiveConnection] = useState<string | null>(null);
  // Cada card decide seu próprio estado padrão (expandido quando exige ação,
  // recolhido quando já está conectado e sincronizado); o usuário pode
  // sobrepor manualmente esse padrão por provider através de "Gerenciar".
  const [expandedOverrides, setExpandedOverrides] = useState<Record<string, boolean>>({});
  const [pendingAssets, setPendingAssets] = useState<MetaDiscoverAssetsResponse | null>(null);
  const [selectedIg, setSelectedIg] = useState<Record<string, boolean>>({});
  const [selectedPages, setSelectedPages] = useState<Record<string, boolean>>({});
  const [selectedAds, setSelectedAds] = useState<Record<string, boolean>>({});
  const [googlePickerId, setGooglePickerId] = useState<string | null>(null);
  const [selectedMetaAuthorizationId, setSelectedMetaAuthorizationId] = useState(
    () => getSelectedConnectionId(getActiveClientId(), "meta") || ""
  );
  const [selectedGoogleAuthorizationIds, setSelectedGoogleAuthorizationIds] = useState<Record<"ga4" | "google_ads", string>>({
    ga4: getSelectedConnectionId(getActiveClientId(), "ga4") || "",
    google_ads: getSelectedConnectionId(getActiveClientId(), "google_ads") || "",
  });
  const [googlePickerProduct, setGooglePickerProduct] = useState<"ga4" | "ads" | null>(null);
  const [googleProperties, setGoogleProperties] = useState<GoogleGa4Property[]>([]);
  const [googleStreams, setGoogleStreams] = useState<GoogleGa4Stream[]>([]);
  const [googleAdsAccounts, setGoogleAdsAccounts] = useState<GoogleAdsAccount[]>([]);
  const [selectedGoogleProperty, setSelectedGoogleProperty] = useState("");
  const [selectedGoogleStream, setSelectedGoogleStream] = useState("");
  const [selectedGoogleAds, setSelectedGoogleAds] = useState("");
  const [googleAdsNotice, setGoogleAdsNotice] = useState("");
  // Erro da listagem fica no próprio seletor: erro da API nunca vira
  // "Nenhuma conta encontrada".
  const [googleAdsListError, setGoogleAdsListError] = useState<string | null>(null);
  const [metaAdsPickerOpen, setMetaAdsPickerOpen] = useState(false);
  const [metaAdsAccounts, setMetaAdsAccounts] = useState<MetaAdsSelectableAccount[]>([]);
  const [selectedMetaAdsAccount, setSelectedMetaAdsAccount] = useState("");
  const [oauthRetry, setOauthRetry] = useState<"meta_discover" | null>(null);
  const [manualMetaConnectionId, setManualMetaConnectionId] = useState<string | null>(null);
  const [manualPageId, setManualPageId] = useState("");
  const [manualInstagramId, setManualInstagramId] = useState("");
  const [manualAdAccountId, setManualAdAccountId] = useState("");
  const [manualMetaValidation, setManualMetaValidation] = useState<ManualMetaAssetsValidation | null>(null);
  const [googleReconnectProduct, setGoogleReconnectProduct] = useState<"ga4" | "google_ads" | null>(null);
  const [backendCommitSha, setBackendCommitSha] = useState("unknown");
  const [lastIntegrationDiagnostic, setLastIntegrationDiagnostic] = useState(EMPTY_INTEGRATION_DIAGNOSTIC);
  const [syncRuntime, setSyncRuntime] = useState<Array<Record<string, unknown>>>([]);
  const manualMetaFormRef = useRef<HTMLElement | null>(null);
  const processedOauthReturnRef = useRef<string | null>(null);
  // Evita setState após desmontagem quando uma carga em andamento resolve
  // depois que o componente já saiu da tela (troca de rota, logout etc.).
  const isMountedRef = useRef(true);
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const configWarning = getActiveClientConfigurationWarning();

  const prepareMetaAssets = useCallback((data: MetaDiscoverAssetsResponse) => {
    // Resposta atrasada de outra empresa (troca durante a descoberta) nunca
    // é exibida no tenant atual.
    const dataClientId = String(data?.client_id || "").trim();
    if (dataClientId && dataClientId !== getActiveClientId()) return;
    setPendingAssets(data);
    setSelectedIg({});
    setSelectedPages({});
    setSelectedAds({});
  }, []);

  // Deduplica cargas concorrentes para o MESMO client_id (reutiliza a
  // Promise em andamento). Uma troca real de empresa não fica presa a essa
  // dedupe: como a chave é o client_id, uma carga para um client_id novo
  // segue em paralelo normalmente.
  const inFlightLoadRef = useRef<{ clientId: string; promise: Promise<{ meta: MetaConnection[]; generic: GenericConnection[] }> } | null>(null);

  const loadConnections = useCallback(async () => {
    const cid = getActiveClientId();
    const inFlight = inFlightLoadRef.current;
    if (inFlight && inFlight.clientId === cid) {
      return inFlight.promise;
    }

    const promise = (async () => {
      const [response, genericResponse] = await Promise.all([
        listClientConnections(),
        listGenericConnections(),
      ]);
      if (!isMountedRef.current) {
        return { meta: response.connections || [], generic: genericResponse.connections || [] };
      }
      const nextConnections = response.connections || [];
      setConnections(nextConnections);
      setGenericConnections(genericResponse.connections || []);

      const nextActiveConnectionId = pickDefaultOrganicConnectionId(
        nextConnections,
        getActiveConnectionId()
      );
      setActiveConnection(nextActiveConnectionId);
      setActiveConnectionId(nextActiveConnectionId);

      // Toda ação que recarrega conexões (conectar, reconectar, selecionar
      // conta, sincronizar) também refaz a leitura canônica — sem exigir
      // reload manual da página.
      void canonicalIntegrationsRefetchRef.current();

      return { meta: nextConnections, generic: genericResponse.connections || [] };
    })();

    inFlightLoadRef.current = { clientId: cid, promise };
    try {
      return await promise;
    } finally {
      if (inFlightLoadRef.current?.promise === promise) {
        inFlightLoadRef.current = null;
      }
    }
  }, []);

  function clearOauthParamsFromUrl() {
    try {
      const url = new URL(window.location.href);
      const params = url.searchParams;
      params.delete("meta_oauth");
      params.delete("google_oauth");
      params.delete("shopify_oauth");
      params.delete("connection_id");
      params.delete("handoff");
      params.delete("error");
      params.delete("code");
      params.delete("integration_product");
      params.delete("google_product");
      params.delete("view");
      params.delete("onboarding");
      params.delete("client_id");
      const next = `${url.pathname}${params.toString() ? `?${params.toString()}` : ""}`;
      window.history.replaceState({}, document.title, next);
    } catch {
      // no-op
    }
  }

  const handleOauthRedirectParams = useCallback(async () => {
    const params = new URLSearchParams(window.location.search);
    const provider = params.has("meta_oauth")
      ? "Meta"
      : params.has("google_oauth")
        ? "Google"
        : params.has("shopify_oauth")
          ? "Shopify"
          : "";
    const oauthStatus = String(
      params.get("meta_oauth") || params.get("google_oauth") || params.get("shopify_oauth") || ""
    ).trim();
    const clientFromCallback = String(params.get("client_id") || "").trim();
    const handoff = String(params.get("handoff") || "").trim();
    const callbackConnectionId = String(params.get("connection_id") || "").trim();
    const oauthError = String(params.get("error") || "").trim();
    const oauthErrorCode = String(params.get("code") || "").trim();

    if (!oauthStatus) return;
    let preserveMetaRetry = false;

    try {
      if (clientFromCallback && clientFromCallback !== getActiveClientId()) {
        throw new Error("O retorno da conexão não corresponde à empresa ativa.");
      }

      if (oauthStatus === "error") {
        if (provider === "Shopify" && oauthErrorCode === "SHOPIFY_INSUFFICIENT_SCOPE") {
          throw new Error("A Shopify não concedeu acesso ao histórico completo de pedidos. A conexão atual não foi alterada.");
        }
        throw new Error(oauthError || "Falha no OAuth da integracao.");
      }

      if (oauthStatus === "success" && handoff) {
        preserveMetaRetry = true;
        const data = await discoverClientMetaAssets(handoff);
        prepareMetaAssets(data);
        const loaded = await loadConnections();
        const callbackAuthorization = selectUsableMetaConnection(
          loaded.generic, getActiveClientId(), callbackConnectionId
        );
        if (!callbackAuthorization) throw new Error("A autorização Meta retornada não está ativa para a empresa selecionada.");
        setSelectedMetaAuthorizationId(callbackConnectionId);
        setSelectedConnectionId(getActiveClientId(), "meta", callbackConnectionId);
        setOauthRetry(null);
        preserveMetaRetry = false;
        setInfo("Autorizacao concluida. Revise os ativos do cliente ativo e finalize o vinculo.");
      } else if (oauthStatus === "success") {
         const loaded = await loadConnections();
         const connectionId = String(params.get("connection_id") || "").trim();
         if (provider === "Google" && connectionId) {
           const product = params.get("integration_product") === "google_ads" ? "google_ads" : "ga4";
           const callbackConnection = selectUsableGoogleConnection(
             loaded.generic, product, getActiveClientId(), connectionId
           );
           if (!callbackConnection) {
             throw new Error(`A conexão ${product === "google_ads" ? "Google Ads" : "GA4"} retornada não está ativa. Conecte novamente.`);
           }
          if (product === "ga4") {
            setSelectedGoogleAuthorizationIds((current) => ({ ...current, ga4: connectionId }));
            setSelectedConnectionId(getActiveClientId(), "ga4", connectionId);
            const ga4 = await listGoogleGa4Properties(connectionId);
            const properties = ga4.properties || [];
            setGooglePickerId(connectionId);
            setGooglePickerProduct("ga4");
            setGoogleProperties(properties);
            if (properties.length === 1) {
              const propertyId = String(properties[0].property || "");
              const streamResponse = await listGoogleGa4Streams(connectionId, propertyId);
              const streams = streamResponse.streams || [];
              setSelectedGoogleProperty(propertyId);
              setGoogleStreams(streams);
              if (streams.length === 1) {
                setSelectedGoogleStream(String(streams[0].name || "").split("/").pop() || "");
              }
              setInfo("Google Analytics autorizado. Confirme a propriedade e o stream para concluir.");
            } else {
              setInfo("Google Analytics autorizado. Selecione a propriedade GA4 para concluir.");
            }
          } else {
            setSelectedGoogleAuthorizationIds((current) => ({ ...current, google_ads: connectionId }));
            setSelectedConnectionId(getActiveClientId(), "google_ads", connectionId);
            const ads = await listGoogleAdsAccounts(callbackConnection, getActiveClientId());
            setGooglePickerId(connectionId);
            setGooglePickerProduct("ads");
            setGoogleAdsAccounts(ads.accounts || []);
            setGoogleAdsNotice(ads.reason || "");
            setInfo("Google Ads autorizado. Selecione a conta para concluir.");
          }
        } else if (provider === "Shopify" && connectionId) {
          // O callback OAuth já dispara o backfill inicial em background
          // (server/routes/shopify_oauth.py) assim que a conexão é salva.
          // Disparar outro POST /sync aqui é redundante e só colide com o
          // lock do backfill em andamento (409 SYNC_ALREADY_RUNNING) — só
          // relemos o estado persistido (conexão + seleção local).
          setSelectedConnectionId(getActiveClientId(), "shopify", connectionId);
          await loadConnections();
          setInfo("Shopify conectada. Importando pedidos, clientes e produtos em segundo plano.");
        } else {
          setInfo(`${provider || "Integração"} conectada com sucesso.`);
        }
      }
    } catch (error: unknown) {
      // Uma sincronização já em andamento (ex.: o backfill iniciado pelo
      // próprio callback OAuth) nunca é uma falha — é o estado esperado.
      // Nunca vira erro vermelho nem afeta o retry de Meta.
      if (isSyncAlreadyRunningError(error)) {
        setInfo("Importando dados em segundo plano…");
      } else {
        setErr(errorMessage(error, "Falha ao processar o retorno do OAuth."));
        if (preserveMetaRetry) setOauthRetry("meta_discover");
      }
    } finally {
      if (!preserveMetaRetry) clearOauthParamsFromUrl();
    }
  }, [loadConnections, prepareMetaAssets]);

  const activeClientIdForSelection = getActiveClientId();
  // Troca de empresa sem remontar a tela: descarta todo estado transitório
  // (ativos descobertos, seleções, handoff, pickers, diagnósticos) que
  // pertence à empresa anterior. Não toca em conexões persistidas. Declarado
  // antes do efeito de carga para limpar antes de carregar a nova empresa.
  const previousClientIdRef = useRef(activeClientIdForSelection);
  useEffect(() => {
    if (previousClientIdRef.current === activeClientIdForSelection) return;
    previousClientIdRef.current = activeClientIdForSelection;
    setPendingAssets(null);
    setSelectedIg({});
    setSelectedPages({});
    setSelectedAds({});
    setOauthRetry(null);
    setActiveConnection(null);
    setManualMetaConnectionId(null);
    setManualPageId("");
    setManualInstagramId("");
    setManualAdAccountId("");
    setManualMetaValidation(null);
    setMetaAdsPickerOpen(false);
    setMetaAdsAccounts([]);
    setSelectedMetaAdsAccount("");
    setGooglePickerId(null);
    setGooglePickerProduct(null);
    setGoogleProperties([]);
    setGoogleStreams([]);
    setGoogleAdsAccounts([]);
    setSelectedGoogleProperty("");
    setSelectedGoogleStream("");
    setSelectedGoogleAds("");
    setGoogleAdsNotice("");
    setGoogleAdsListError(null);
    setGoogleReconnectProduct(null);
    setLastIntegrationDiagnostic(EMPTY_INTEGRATION_DIAGNOSTIC);
    setSyncRuntime([]);
    setErr(null);
    setInfo(null);
  }, [activeClientIdForSelection]);

  useEffect(() => {
    if (!isAuthenticated) return;

    let alive = true;
    setLoading(true);

    (async () => {
      try {
        const search = new URLSearchParams(window.location.search);
        const hasOauthReturn = search.has("meta_oauth") || search.has("google_oauth") || search.has("shopify_oauth");
        if (hasOauthReturn) {
          const oauthReturnKey = window.location.search;
          if (processedOauthReturnRef.current === oauthReturnKey) return;
          processedOauthReturnRef.current = oauthReturnKey;
          await handleOauthRedirectParams();
        }
        else await loadConnections();
      } catch (error: unknown) {
        if (!alive) return;
        setErr(errorMessage(error, "Erro ao carregar as integracoes do cliente ativo."));
      } finally {
        if (alive) {
          setLoading(false);
        }
      }
    })();

    return () => {
      alive = false;
    };
    // activeClientIdForSelection é o único gatilho de "mudança real de
    // empresa": troca de cliente sem reload de página (ex.: admin da
    // agência trocando de empresa) precisa recarregar as conexões da nova
    // empresa. handleOauthRedirectParams/loadConnections têm identidade
    // estável (deps primitivas/refs) e não recascateiam este efeito por
    // conta própria — só aparecem aqui para o efeito sempre usar a versão
    // mais recente deles.
  }, [activeClientIdForSelection, handleOauthRedirectParams, isAuthenticated, loadConnections]);

  useEffect(() => {
    setSelectedMetaAuthorizationId(getSelectedConnectionId(activeClientIdForSelection, "meta") || "");
    setSelectedGoogleAuthorizationIds({
      ga4: getSelectedConnectionId(activeClientIdForSelection, "ga4") || "",
      google_ads: getSelectedConnectionId(activeClientIdForSelection, "google_ads") || "",
    });
    setManualMetaConnectionId(null);
    setGooglePickerId(null);
    setGooglePickerProduct(null);
  }, [activeClientIdForSelection]);

  useEffect(() => {
    if (!isAuthenticated) return;
    void getApiVersion()
      .then((version) => setBackendCommitSha(String(version.commit_sha || "unknown")))
      .catch(() => setBackendCommitSha("unavailable"));
  }, [isAuthenticated]);

  useEffect(() => {
    if (!googlePickerId || googlePickerProduct !== "ads") return;
    const selected = selectUsableGoogleConnection(
      genericConnections, "google_ads", getActiveClientId(), googlePickerId
    );
    if (selected) return;
    setGooglePickerId(null);
    setGooglePickerProduct(null);
    setSelectedGoogleAds("");
    setGoogleAdsAccounts([]);
    setGoogleAdsListError(null);
  }, [genericConnections, googlePickerId, googlePickerProduct]);

  useEffect(() => {
    if (loading) return;
    const selectedId = selectedGoogleAuthorizationIds.google_ads;
    if (!selectedId) return;
    const selected = selectUsableGoogleConnection(
      genericConnections, "google_ads", getActiveClientId(), selectedId
    );
    if (selected) return;
    console.warn("Google Ads request blocked", {
      connection_id: selectedId, reason: "persisted_connection_unavailable",
      activeClientId: getActiveClientId(),
    });
    setLastIntegrationDiagnostic((current) => ({ ...current, adsBlockedReason: "persisted_connection_unavailable" }));
    setSelectedConnectionId(getActiveClientId(), "google_ads", null);
    setSelectedGoogleAuthorizationIds((current) => ({ ...current, google_ads: "" }));
    setGooglePickerId(null);
    setGooglePickerProduct(null);
  }, [genericConnections, loading, selectedGoogleAuthorizationIds.google_ads]);

  useEffect(() => {
    if (!manualMetaConnectionId) return;
    window.requestAnimationFrame(() => {
      manualMetaFormRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      manualMetaFormRef.current?.querySelector<HTMLInputElement>("input")?.focus();
    });
  }, [manualMetaConnectionId]);

  useEffect(() => {
    if (!initialError) return;
    setErr(initialError);
  }, [initialError]);

  const selectedGoogleAdsAccount = googlePickerProduct === "ads"
    ? googleAdsAccounts.find((item) => item.customer_id === selectedGoogleAds) || null
    : null;
  const googleAdsReady = Boolean(selectedGoogleAdsAccount && !selectedGoogleAdsAccount.is_manager);

  const organicConnections = useMemo(
    () => connections.filter(isOrganicConnection),
    [connections]
  );
  const paidConnections = useMemo(
    () => connections.filter(isPaidConnection),
    [connections]
  );

  const activeOrganicConnection =
    selectUniqueConnection(organicConnections, (connection) => connection.id === activeConnectionId) ||
    null;

  const dashboardReady = Boolean(activeOrganicConnection);
  const metaGenericConnection = selectUsableMetaConnection(
    genericConnections, getActiveClientId(), selectedMetaAuthorizationId
  );
  const selectedPaidConnection = selectUniqueConnection(paidConnections, (connection) =>
    String(connection.ad_account_id || "") === String(metaGenericConnection?.metadata?.selected_ad_account_id || "")
  );
  const metaAdsOperational = Boolean(selectedPaidConnection?.ad_account_id);
  const metaSelectionPending = String(metaGenericConnection?.status || "").toLowerCase() === "selection_required";
  const connectionSummary = useMemo(() => {
    const states = genericConnections.map((item) => connectionTone(item.status));
    const hasGenericMeta = genericConnections.some((item) => item.provider === "meta");
    if (!hasGenericMeta && (dashboardReady || paidConnections.length)) states.push("green");
    return {
      connected: states.filter((state) => state === "green").length,
      pending: states.filter((state) => state === "yellow").length + (!hasGenericMeta && pendingAssets ? 1 : 0),
      errors: states.filter((state) => state === "red").length,
    };
  }, [dashboardReady, genericConnections, paidConnections.length, pendingAssets]);

  async function onStartOAuth() {
    if (!canManageConnections) {
      setErr("Seu perfil permite apenas visualizar as conexões.");
      return;
    }
    setErr(null);
    setInfo(null);
    setOauthLoading(true);

    try {
      const response = await startClientMetaOAuth();
      const authorizationUrl = String(response.authorization_url || "").trim();
      if (!authorizationUrl) {
        throw new Error("A integracao nao retornou URL de autorizacao.");
      }
      window.location.assign(authorizationUrl);
    } catch (error: unknown) {
      setErr(errorMessage(error, "Erro ao iniciar a integracao do cliente ativo."));
      setOauthLoading(false);
    }
  }

  async function onResumeMetaSelection(connection: GenericConnection) {
    const handoff = String(connection.metadata?.oauth_handoff || "").trim();
    setSaving(true);
    setErr(null);
    try {
      const data = handoff
        ? await discoverClientMetaAssets(handoff)
        : await configureExistingMetaOrganic(connection.id);
      prepareMetaAssets(data);
      if (!handoff) setSelectedAds({});
      setInfo(data.message || "Ativos Meta carregados. Revise a seleção e salve para concluir.");
    } catch (error: unknown) {
      setErr(errorMessage(error, "Não foi possível carregar os ativos Meta autorizados."));
    } finally {
      setSaving(false);
    }
  }

  async function onOpenMetaAdsPicker() {
    setSaving(true);
    setErr(null);
    try {
      const response = await listClientMetaAdsAccounts();
      const accounts = response.accounts || [];
      setMetaAdsAccounts(accounts);
      setSelectedMetaAdsAccount(String(selectedPaidConnection?.ad_account_id || ""));
      setMetaAdsPickerOpen(true);
      if (!accounts.length) setErr("A autorização Meta não retornou nenhuma conta de anúncios acessível com ads_read.");
    } catch (error: unknown) {
      setErr(errorMessage(error, "Não foi possível listar as contas Meta Ads acessíveis."));
    } finally {
      setSaving(false);
    }
  }

  async function onValidateManualMetaAssets() {
    const connection = selectUsableMetaConnection(
      genericConnections, getActiveClientId(), manualMetaConnectionId
    );
    if (!connection) {
      setErr(`A conexão Meta selecionada não está ativa para ${getActiveClientName()}. Selecione ou reconecte a Meta.`);
      return;
    }
    setSaving(true);
    setErr(null);
    setManualMetaValidation(null);
    try {
      console.info("[meta-manual]", {
        stage: "validate", activeClientId: getActiveClientId(), selectedMetaAuthorizationId,
        manualMetaConnectionId, provider: connection.provider, status: connection.status,
        connectionClientId: connection.client_id, tokenAvailable: connection.token_available,
        pageId: manualPageId.trim() || null, instagramId: manualInstagramId.trim() || null,
        endpoint: `/api/oauth/meta/${connection.id}/manual-assets/validate`,
      });
      const result = await validateManualMetaAssets(connection.id, {
        page_id: manualPageId.trim() || undefined,
        instagram_id: manualInstagramId.trim() || undefined,
        ad_account_id: manualAdAccountId.trim() || undefined,
      });
      setManualMetaValidation(result);
      setInfo("Ativos validados com a autorização Meta atual. Revise os nomes antes de salvar.");
    } catch (error: unknown) {
      if (error instanceof ApiError) setLastIntegrationDiagnostic((current) => ({ ...current, code: error.code, requestId: error.requestId }));
      setErr(error instanceof ApiError && error.status === 404
        ? "A configuração manual Meta não está disponível nesta versão do servidor. Atualize o deploy do backend e tente novamente."
        : errorMessage(error, "Não foi possível validar os IDs Meta. Verifique os IDs, permissões e o vínculo entre Página e Instagram."));
    } finally {
      setSaving(false);
    }
  }

  async function onSaveManualMetaAssets() {
    const validatedPageId = String(manualMetaValidation?.page?.id || (manualPageId || "")).trim();
    const validatedInstagramId = String(manualMetaValidation?.instagram?.id || (manualInstagramId || "")).trim();
    const activeClientId = getActiveClientId();
    if (!selectedMetaAuthorizationId) {
      return;
    }
    const connection = selectUsableMetaConnection(
      genericConnections, activeClientId, selectedMetaAuthorizationId
    );
    if (!connection) {
      setErr(`A conexão Meta selecionada não está ativa para ${getActiveClientName()}. Selecione ou reconecte a Meta.`);
      return;
    }
    const metadata = connection?.metadata || {};
    const replacing =
      (manualPageId.trim() && metadata.selected_page_id && manualPageId.trim() !== String(metadata.selected_page_id)) ||
      (manualInstagramId.trim() && metadata.selected_instagram_id && manualInstagramId.trim() !== String(metadata.selected_instagram_id)) ||
      (manualAdAccountId.trim() && metadata.selected_ad_account_id && manualAdAccountId.replace(/^act_/, "") !== String(metadata.selected_ad_account_id).replace(/^act_/, ""));
    const adAccountChanged = Boolean(
      manualAdAccountId.trim()
      && manualAdAccountId.replace(/^act_/, "") !== String(metadata.selected_ad_account_id || "").replace(/^act_/, "")
    );
    if (replacing && !window.confirm("Substituir o ativo Meta atualmente selecionado para esta empresa?")) {
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      console.info("[meta-manual]", {
        stage: "save", activeClientId: getActiveClientId(), selectedMetaAuthorizationId,
        manualMetaConnectionId, provider: connection.provider, status: connection.status,
        connectionClientId: connection.client_id, tokenAvailable: connection.token_available,
        pageId: manualPageId.trim() || null, instagramId: manualInstagramId.trim() || null,
        endpoint: `/api/oauth/meta/${connection.id}/manual-assets`,
      });
      if (adAccountChanged) {
        await saveManualMetaAssets(connection.id, { ad_account_id: manualAdAccountId.trim() });
      }
      if (!validatedPageId || !validatedInstagramId) {
        if (adAccountChanged) {
          await loadConnections();
          setManualMetaConnectionId(null);
          setManualMetaValidation(null);
          setInfo("Ativo Meta Ads salvo sem alterar a configuração orgânica.");
          return;
        }
        setErr("META_ORGANIC_ASSETS_REQUIRED: selecione uma Página e o Instagram profissional vinculado.");
        return;
      }
      const result = await activateMetaOrganic(selectedMetaAuthorizationId, {
        page_id: validatedPageId, instagram_id: validatedInstagramId,
      });
      if (result.ok && result.initial_sync?.ok === true && result.organic_connection_id) {
        setActiveConnection(result.organic_connection_id);
        setActiveConnectionId(result.organic_connection_id);
      }
      await loadConnections();
      const initialSync = result.initial_sync && typeof result.initial_sync === "object"
        ? result.initial_sync as Record<string, unknown>
        : null;
      const organicConnectionId = String(result.organic_connection_id || "");
      const initialSyncOk = Boolean(result.ok && initialSync?.ok === true && organicConnectionId);
      setLastIntegrationDiagnostic((current) => ({
        ...current, initialSyncOk, organicConnectionId,
        code: String(result.code || ""), requestId: String(result.request_id || ""),
      }));
      console.info("[meta-manual]", { stage: "complete", initialSyncOk, organicConnectionId });
      if (!initialSyncOk) {
        setErr(`Ativos Meta salvos, mas a sincronização inicial falhou.${String(initialSync?.code || result.code || "") ? ` Código: ${String(initialSync?.code || result.code)}.` : ""}${result.request_id ? ` Request ID: ${result.request_id}.` : ""}`);
        return;
      }
      setManualMetaConnectionId(null);
      setManualMetaValidation(null);
      setInfo("Instagram orgânico configurado, salvo e sincronização inicial iniciada.");
    } catch (error: unknown) {
      if (error instanceof ApiError) setLastIntegrationDiagnostic((current) => ({ ...current, code: error.code, requestId: error.requestId }));
      setErr(error instanceof ApiError && error.status === 404
        ? "A configuração manual Meta não está disponível nesta versão do servidor. Atualize o deploy do backend e tente novamente."
        : errorMessage(error, "Não foi possível salvar os ativos Meta. Verifique permissões e incompatibilidade entre os ativos."));
    } finally {
      setSaving(false);
    }
  }

  async function onSaveMetaAdsAccount() {
    if (!selectedMetaAdsAccount) return setErr("Selecione uma conta de anúncios.");
    setSaving(true);
    setErr(null);
    try {
      await selectClientMetaAdsAccount(selectedMetaAdsAccount);
      await loadConnections();
      setMetaAdsPickerOpen(false);
      setInfo(`Conta Meta Ads ${selectedMetaAdsAccount} selecionada para ${getActiveClientName()}.`);
    } catch (error: unknown) {
      setErr(errorMessage(error, "Não foi possível persistir a conta Meta Ads."));
    } finally {
      setSaving(false);
    }
  }

  async function onSyncMetaAdsNow() {
    if (!selectedPaidConnection?.id) return setErr("Selecione uma conta Meta Ads antes de sincronizar.");
    setSaving(true);
    setErr(null);
    const startedAt = new Date().toISOString();
    setSyncRuntime([{ tenant: getActiveClientId(), provider: "meta_ads", connection_id: selectedPaidConnection.id, endpoint: "/api/clients/{client_id}/meta-ads/sync", status: "running", code: "-", request_id: "-", started_at: startedAt, finished_at: "-", rows_written: 0 }]);
    try {
      // Dedup por (client_id, provider, connection_id): clique duplo no
      // mesmo botão reaproveita a mesma chamada em voo em vez de disparar
      // um segundo POST de sync.
      const result = await runExclusiveSync(
        { clientId: getActiveClientId(), provider: "meta_ads", connectionId: selectedPaidConnection.id },
        () => syncClientMetaAdsAccount(selectedPaidConnection.id)
      );
      setSyncRuntime([{ tenant: getActiveClientId(), provider: "meta_ads", connection_id: selectedPaidConnection.id, endpoint: "/api/clients/{client_id}/meta-ads/sync", status: "fulfilled", code: String(result.code || "OK"), request_id: String(result.request_id || ""), started_at: startedAt, finished_at: new Date().toISOString(), rows_written: Number(result.rows_written || 0) }]);
      await loadConnections();
      const outcome = String(result.sync_outcome || result.job_status || "");
      setInfo(outcome === "success" ? "Meta Ads sincronizado e persistido." : `Sincronização Meta Ads: ${outcome || "resultado indisponível"}.`);
    } catch (error: unknown) {
      setSyncRuntime([{ tenant: getActiveClientId(), provider: "meta_ads", connection_id: selectedPaidConnection.id, endpoint: "/api/clients/{client_id}/meta-ads/sync", status: "rejected", code: error instanceof ApiError ? error.code : "SYNC_FAILED", request_id: error instanceof ApiError ? error.requestId : "", started_at: startedAt, finished_at: new Date().toISOString(), rows_written: 0 }]);
      setErr(describeSyncError(error, "A sincronização Meta Ads falhou."));
    } finally {
      setSaving(false);
    }
  }

  async function onStartGoogleOAuth(product: "ga4" | "google_ads") {
    if (!canManageConnections) return;
    setOauthLoading(true);
    setErr(null);
    try {
      const response = await startGoogleOAuth(product);
      window.location.assign(response.authorization_url);
    } catch (error: unknown) {
      setErr(errorMessage(error, "Não foi possível iniciar a autorização Google."));
      setOauthLoading(false);
    }
  }

  async function onStartShopifyOAuth(domainOverride?: string) {
    if (!canManageConnections) return;
    setOauthLoading(true);
    setErr(null);
    try {
      const response = await startShopifyOAuth(domainOverride || shopifyDomain);
      navigateToExternalAuthorization(response.authorization_url);
    } catch (error: unknown) {
      setErr(errorMessage(error, "Informe um domínio válido nomedaloja.myshopify.com."));
      setOauthLoading(false);
    }
  }

  async function onSelectShopify(connectionId: string) {
    if (!canManageConnections || !connectionId) return;
    setSaving(true);
    setErr(null);
    setInfo(null);
    try {
      await selectShopifyConnection(connectionId);
      setSelectedConnectionId(getActiveClientId(), "shopify", connectionId);
      await loadConnections();
      setInfo("Loja Shopify selecionada para os relatórios da empresa ativa.");
    } catch (error: unknown) {
      setErr(errorMessage(error, "Não foi possível selecionar a loja Shopify."));
    } finally {
      setSaving(false);
    }
  }

  async function onSyncShopify(connectionId: string) {
    if (!canManageConnections || !connectionId) return;
    setSaving(true);
    setErr(null);
    setInfo(null);
    const startedAt = new Date().toISOString();
    setSyncRuntime([{ tenant: getActiveClientId(), provider: "shopify", connection_id: connectionId, endpoint: "/api/oauth/shopify/{connection_id}/sync", status: "running", code: "-", request_id: "-", started_at: startedAt, finished_at: "-", rows_written: 0 }]);
    try {
      const result = await runExclusiveSync(
        { clientId: getActiveClientId(), provider: "shopify", connectionId },
        () => syncShopifyConnection(connectionId)
      );
      setSyncRuntime([{ tenant: getActiveClientId(), provider: "shopify", connection_id: connectionId, endpoint: "/api/oauth/shopify/{connection_id}/sync", status: "fulfilled", code: String(result.code || "OK"), request_id: String(result.request_id || ""), started_at: startedAt, finished_at: new Date().toISOString(), rows_written: Number(result.rows_written || result.orders_saved || 0) }]);
      await loadConnections();
      setInfo("Pedidos, clientes e produtos da Shopify foram atualizados.");
    } catch (error: unknown) {
      setSyncRuntime([{ tenant: getActiveClientId(), provider: "shopify", connection_id: connectionId, endpoint: "/api/oauth/shopify/{connection_id}/sync", status: "rejected", code: error instanceof ApiError ? error.code : "SYNC_FAILED", request_id: error instanceof ApiError ? error.requestId : "", started_at: startedAt, finished_at: new Date().toISOString(), rows_written: 0 }]);
      // Uma sincronização já em andamento (409 SYNC_ALREADY_RUNNING) é um
      // estado válido, nunca uma falha da integração — não vira erro
      // vermelho nem dispara retry automático.
      if (isSyncAlreadyRunningError(error)) {
        setInfo("Importando dados da Shopify em segundo plano…");
      } else {
        setErr(describeSyncError(error, "Não foi possível sincronizar a loja Shopify."));
      }
    } finally {
      setSaving(false);
    }
  }

  async function onRefreshStatus() {
    if (loading) return;
    setLoading(true);
    setErr(null);
    try {
      await loadConnections();
    } catch (error: unknown) {
      setErr(errorMessage(error, "Erro ao atualizar o status das integracoes."));
    } finally {
      setLoading(false);
    }
  }

  async function onLinkSelectedAssets() {
    if (!pendingAssets?.handoff) {
      setErr("Sessao OAuth invalida. Conecte novamente.");
      return;
    }

    const instagramIds = Object.entries(selectedIg)
      .filter(([, checked]) => checked)
      .map(([id]) => id);
    const pageIds = Object.entries(selectedPages)
      .filter(([, checked]) => checked)
      .map(([id]) => id);
    const adAccountIds = Object.entries(selectedAds)
      .filter(([, checked]) => checked)
      .map(([id]) => id);

    setSaving(true);
    setErr(null);
    setInfo(null);

    try {
      if (instagramIds.length && (!selectedMetaAuthorizationId || instagramIds.length !== 1 || pageIds.length !== 1)) {
        setErr("Selecione explicitamente uma autorização, uma Página e um Instagram para concluir o orgânico.");
        return;
      }
      await linkClientAssets({
        handoff: pendingAssets.handoff,
        page_ids: pageIds,
        instagram_ig_user_ids: instagramIds,
        ad_account_ids: adAccountIds,
      });
      if (instagramIds.length === 1 && pageIds.length === 1) {
        const activation = await activateMetaOrganic(selectedMetaAuthorizationId, {
          page_id: pageIds[0], instagram_id: instagramIds[0],
        });
        setLastIntegrationDiagnostic((current) => ({
          ...current,
          initialSyncOk: Boolean(activation?.ok && activation?.initial_sync?.ok === true && activation?.organic_connection_id),
          organicConnectionId: activation?.organic_connection_id || "",
          code: activation?.code || "",
          requestId: activation?.request_id || "",
        }));
        if (!activation.ok || activation.initial_sync?.ok !== true || !activation.organic_connection_id) {
          await loadConnections();
          setErr(`Os ativos foram salvos, mas a sincronização orgânica falhou. Código: ${activation.code}.${activation.request_id ? ` Request ID: ${activation.request_id}.` : ""}`);
          return;
        }
        setActiveConnection(activation.organic_connection_id);
        setActiveConnectionId(activation.organic_connection_id);
      }
      setPendingAssets(null);
      setSelectedIg({});
      setSelectedPages({});
      setSelectedAds({});
      await loadConnections();
      setInfo("Meta conectada. Ativos persistidos e importação inicial concluída.");
    } catch (error: unknown) {
      setErr(errorMessage(error, "Erro ao vincular os ativos do cliente ativo."));
    } finally {
      setSaving(false);
    }
  }

  async function onDisconnect(connection: MetaConnection) {
    if (disconnectingId) return;
    setDisconnectingId(connection.id);
    setErr(null);
    setInfo(null);

    try {
      await disconnectClientConnection(connection.id);
      await loadConnections();
      setInfo(`Conexao "${connectionLabel(connection)}" desconectada.`);
    } catch (error: unknown) {
      setErr(errorMessage(error, "Erro ao desconectar a integracao."));
    } finally {
      setDisconnectingId(null);
    }
  }

  async function onManageGoogle(connection: GenericConnection, product: "ga4" | "ads") {
    setSaving(true);
    setErr(null);
    setInfo(null);
    setGoogleReconnectProduct(null);
    try {
      const provider = product === "ga4" ? "ga4" : "google_ads";
      const explicitlySelectedId = selectedGoogleAuthorizationIds[provider];
      if (connection.id !== explicitlySelectedId || !isUsableGoogleConnection(connection, provider, getActiveClientId())) {
        if (provider === "google_ads") {
          const reason = connection.id !== explicitlySelectedId ? "not_explicitly_selected" : "connection_unusable";
          console.warn("Google Ads request blocked", { connection_id: connection.id, reason, activeClientId: getActiveClientId() });
          setLastIntegrationDiagnostic((current) => ({ ...current, adsBlockedReason: reason }));
        }
        setInfo(`Conecte ${product === "ga4" ? "o Google Analytics" : "o Google Ads"} antes de selecionar ativos.`);
        return;
      }
      if (product === "ga4") {
        setGooglePickerId(connection.id);
        setGooglePickerProduct(product);
        setGoogleProperties([]);
        setGoogleStreams([]);
        setSelectedGoogleProperty(String(connection.metadata?.ga4_property_id || ""));
        setSelectedGoogleStream(String(connection.metadata?.ga4_stream_id || ""));
        const ga4 = await listGoogleGa4Properties(connection.id);
        const properties = ga4.properties || [];
        setGoogleProperties(properties);
        setLastIntegrationDiagnostic((current) => ({
          ...current, propertyCount: properties.length, code: "OK", requestId: "",
        }));
        if (!properties.length) setInfo(ga4.message || "O usuário Google autorizado não possui acesso a nenhuma propriedade GA4.");
      } else {
        setGoogleAdsListError(null);
        const ads = await listGoogleAdsAccounts(connection, getActiveClientId());
        setGooglePickerId(connection.id);
        setGooglePickerProduct(product);
        setGoogleAdsAccounts(ads.accounts || []);
        setGoogleAdsNotice(ads.reason || "");
      }
      if (product !== "ga4") {
        setSelectedGoogleProperty(String(connection.metadata?.ga4_property_id || ""));
        setSelectedGoogleStream(String(connection.metadata?.ga4_stream_id || ""));
      }
      setSelectedGoogleAds(String(connection.metadata?.google_ads_customer_id || ""));
    } catch (error: unknown) {
      if (error instanceof ApiError && error.code.startsWith("GOOGLE_REAUTH_REQUIRED")) {
        setGoogleReconnectProduct(product === "ga4" ? "ga4" : "google_ads");
      }
      if (error instanceof ApiError) setLastIntegrationDiagnostic((current) => ({ ...current, code: error.code, requestId: error.requestId }));
      const fallback = product === "ga4"
        ? "Não foi possível listar as propriedades do Google Analytics."
        : "Não foi possível consultar as contas Google Ads.";
      if (product === "ads" && connection?.id) {
        // Mostra o erro dentro do seletor Ads (com código), em vez de uma
        // lista vazia que pareceria "nenhuma conta".
        setGooglePickerId(connection.id);
        setGooglePickerProduct("ads");
        setGoogleAdsAccounts([]);
        setSelectedGoogleAds("");
        setGoogleAdsNotice("");
        setGoogleAdsListError(
          `${errorMessage(error, fallback)}${error instanceof ApiError && error.code ? ` Código: ${error.code}.` : ""}`
        );
      }
      setErr(error instanceof ApiError && error.code === "GOOGLE_ADMIN_API_DISABLED"
        ? `${error.message} Ative a Google Analytics Admin API no projeto Google Cloud da credencial OAuth. Código: ${error.code}.${error.requestId ? ` Request ID: ${error.requestId}.` : ""}`
        : errorMessage(error, fallback));
    } finally {
      setSaving(false);
    }
  }

  async function onSaveGoogleSelection() {
    if (!googlePickerId) return;
    if (googlePickerProduct === "ga4" && !selectedGoogleProperty) {
      setErr("Selecione uma propriedade GA4.");
      return;
    }
    if (googlePickerProduct === "ga4" && !selectedGoogleStream) {
      setErr("Selecione um stream da propriedade GA4.");
      return;
    }
    if (googlePickerProduct === "ads" && !selectedGoogleAds) {
      setErr("Selecione uma conta Google Ads.");
      return;
    }
    if (googlePickerProduct === "ads" && googleAdsAccounts.find((item) => item.customer_id === selectedGoogleAds)?.is_manager) {
      setErr("Conta administradora (MCC) não possui campanhas próprias. Selecione uma conta de anúncios.");
      return;
    }
    setSaving(true);
    setErr(null);
    let adsSyncError = "";
    try {
      if (googlePickerProduct === "ga4") {
        const property = googleProperties.find((item) => item.property === selectedGoogleProperty);
        await selectGoogleGa4Property(googlePickerId, selectedGoogleProperty, {
          accountId: property?.account,
          propertyName: property?.property_name,
          streamId: selectedGoogleStream,
        });
        await syncGoogleConnection(googlePickerId);
        setLastIntegrationDiagnostic((current) => ({
          ...current, propertyId: selectedGoogleProperty,
          streamId: selectedGoogleStream, ga4LastSync: new Date().toISOString(),
          code: "OK", requestId: "",
        }));
      } else if (selectedGoogleAds) {
        const account = googleAdsAccounts.find((item) => item.customer_id === selectedGoogleAds);
        await selectGoogleAdsAccount(googlePickerId, selectedGoogleAds, account?.login_customer_id || null);
        // Primeira sincronização imediata (como no GA4): sem ela o dashboard
        // só recebe dados no próximo cron. Falha aqui não desfaz a seleção.
        try {
          await syncGoogleConnection(googlePickerId);
        } catch (syncError: unknown) {
          adsSyncError = errorMessage(syncError, "A primeira sincronização Google Ads falhou.");
          if (syncError instanceof ApiError && syncError.code) adsSyncError += ` Código: ${syncError.code}.`;
        }
      }
      await loadConnections();
      setGooglePickerId(null);
      setGooglePickerProduct(null);
      if (adsSyncError) {
        setErr(`Conta Google Ads salva, mas a primeira sincronização falhou: ${adsSyncError}`);
      } else {
        setInfo(googlePickerProduct === "ga4" ? "Propriedade GA4 salva e sincronizada." : "Conta Google Ads conectada e sincronizada.");
      }
    } catch (error: unknown) {
      setErr(errorMessage(error, "Não foi possível salvar a seleção Google."));
    } finally {
      setSaving(false);
    }
  }

  async function onSelectGooglePropertyForStreams(propertyId: string) {
    setSelectedGoogleProperty(propertyId);
    setSelectedGoogleStream("");
    setGoogleStreams([]);
    if (!googlePickerId || !propertyId) return;
    setSaving(true);
    setErr(null);
    try {
      const response = await listGoogleGa4Streams(googlePickerId, propertyId);
      const streams = response.streams || [];
      setGoogleStreams(streams);
      setLastIntegrationDiagnostic((current) => ({
        ...current, propertyId, streamCount: streams.length, code: "OK", requestId: "",
      }));
      if (streams.length === 1) {
        setSelectedGoogleStream(String(streams[0].name || "").split("/").pop() || "");
      }
      if (!streams.length) setErr("A propriedade não possui streams acessíveis.");
    } catch (error: unknown) {
      if (error instanceof ApiError) setLastIntegrationDiagnostic((current) => ({
        ...current, code: error.code, requestId: error.requestId,
      }));
      setErr(errorMessage(error, "Não foi possível listar os streams da propriedade."));
    } finally {
      setSaving(false);
    }
  }

  async function onSyncGoogle(connection: GenericConnection) {
    setSaving(true);
    setErr(null);
    const startedAt = new Date().toISOString();
    setSyncRuntime([{ tenant: getActiveClientId(), provider: "ga4", connection_id: connection.id, endpoint: "/api/oauth/google/{connection_id}/sync", status: "running", code: "-", request_id: "-", started_at: startedAt, finished_at: "-", rows_written: 0 }]);
    try {
      const result = await runExclusiveSync(
        { clientId: getActiveClientId(), provider: "ga4", connectionId: connection.id },
        () => syncGoogleConnection(connection.id)
      );
      setSyncRuntime([{ tenant: getActiveClientId(), provider: "ga4", connection_id: connection.id, endpoint: "/api/oauth/google/{connection_id}/sync", status: "fulfilled", code: String(result.code || "OK"), request_id: String(result.request_id || ""), started_at: startedAt, finished_at: new Date().toISOString(), rows_written: Number(result.rows_written || 0) }]);
      await loadConnections();
      setInfo("Sincronização manual do GA4 concluída.");
    } catch (error: unknown) {
      setSyncRuntime([{ tenant: getActiveClientId(), provider: "ga4", connection_id: connection.id, endpoint: "/api/oauth/google/{connection_id}/sync", status: "rejected", code: error instanceof ApiError ? error.code : "SYNC_FAILED", request_id: error instanceof ApiError ? error.requestId : "", started_at: startedAt, finished_at: new Date().toISOString(), rows_written: 0 }]);
      setErr(describeSyncError(error, "Não foi possível sincronizar o GA4."));
    } finally {
      setSaving(false);
    }
  }

  async function onDisconnectGeneric(connection: GenericConnection) {
    if (disconnectingId) return;
    const confirmation = connection.provider === "shopify"
      ? "Desconectar a Shopify?\n\nA sincronização será interrompida. Os dados históricos e dashboards já importados serão preservados. Novos dados não serão sincronizados até uma nova conexão."
      : "Desconectar esta integração? O histórico importado será preservado.";
    if (!window.confirm(confirmation)) return;
    setDisconnectingId(connection.id);
    setErr(null);
    try {
      await disconnectGenericConnection(connection);
      await loadConnections();
      setInfo("Integração desconectada. Os dados históricos foram preservados.");
    } catch (error: unknown) {
      setErr(errorMessage(error, "Não foi possível desconectar a integração."));
    } finally {
      setDisconnectingId(null);
    }
  }

  function onUseConnection(connection: MetaConnection) {
    setActiveConnection(connection.id);
    setActiveConnectionId(connection.id);
    setInfo(`A conexao "${connectionLabel(connection)}" foi definida como ativa no painel.`);
  }

  async function onContinue() {
    if (!dashboardReady) {
      setErr("Conecte a integracao organica do cliente ativo antes de abrir o dashboard.");
      return;
    }
    await onCompleted?.();
  }

  if (!isAuthenticated) {
    return null;
  }

  return (
    <div className="onboardingPage">
      <header className="onboardingTop">
        <div className="onboardingBrand">
          <MugoLogo variant="responsive" className="onboardingLogo" alt="Mugô" />
          <div>
            <div className="onboardingTitle">{MUGO_APP_NAME}</div>
            <div className="onboardingSub">Central de conexões da empresa ativa.</div>
          </div>
        </div>
        <button className="btn btnGhost" type="button" onClick={() => void onLogout?.()}>
          Sair
        </button>
      </header>

      <main className="onboardingWrap">
        <section className="onboardingHero">
          <div>
            <h1>Conexões de {getActiveClientName()}</h1>
            <p>
              Autorize fontes oficiais e acompanhe o estado de cada importação. O histórico
              permanece preservado quando uma conta é desconectada.
            </p>
          </div>
          <div className="onboardingHeroActions">
            <button className="btn btnGhost" type="button" disabled={loading} onClick={() => void onRefreshStatus()}>
              {loading ? "Atualizando..." : "Atualizar status"}
            </button>
            {metaSelectionPending && metaGenericConnection ? (
              <button className="btn btnGold" type="button" disabled={saving || !canManageConnections} onClick={() => void onResumeMetaSelection(metaGenericConnection)}>
                {saving ? "Carregando ativos..." : "Selecionar ativos"}
              </button>
            ) : !metaGenericConnection || ["disconnected", "expired", "token_expired", "reauth_required"].includes(String(metaGenericConnection.status || "").toLowerCase()) ? (
              <button className="btn btnGold" type="button" disabled={oauthLoading || !canManageConnections} onClick={() => void onStartOAuth()}>
                {oauthLoading ? "Redirecionando..." : "Conectar com Meta"}
              </button>
            ) : null}
            <button className="btn btnPrimary" type="button" disabled={!dashboardReady} onClick={() => void onContinue()}>
              Abrir dashboard
            </button>
          </div>
        </section>

        {configWarning ? <div className="pill pillDanger">{configWarning}</div> : null}
        {commitsMismatch(FRONTEND_COMMIT_SHA, backendCommitSha) ? (
          <div className="pill pillDanger">
            Versões incompatíveis: frontend {shortCommit(FRONTEND_COMMIT_SHA)} · backend {shortCommit(backendCommitSha)}.
          </div>
        ) : null}
        {err ? <div className="pill pillDanger">
          {err}
          {googleReconnectProduct ? (
            <button className="btn btnGhost" type="button" disabled={oauthLoading} onClick={() => void onStartGoogleOAuth(googleReconnectProduct)} style={{ marginLeft: 10 }}>
              Reconectar Google
            </button>
          ) : null}
          {oauthRetry === "meta_discover" ? (
            <button className="btn btnGhost" type="button" disabled={loading} onClick={() => void handleOauthRedirectParams()} style={{ marginLeft: 10 }}>
              Tentar novamente
            </button>
          ) : null}
        </div> : null}
        {info ? <div className="pill pillSoft">{info}</div> : null}

        <section className="integrationSummary" aria-label="Resumo das integrações">
          <article><span>Conectadas</span><strong>{connectionSummary.connected}</strong></article>
          <article><span>Configurações pendentes</span><strong>{connectionSummary.pending}</strong></article>
          <article><span>Com atenção</span><strong>{connectionSummary.errors}</strong></article>
          <article><span>Empresa</span><strong>{getActiveClientName()}</strong></article>
        </section>

        <section className="card cardWide">
          <div className="sectionHeader">
            <div>
              <div className="h1">Ambiente protegido da empresa</div>
              <div className="p">
                Todas as consultas usam o identificador da empresa selecionada e são
                validadas pelo servidor antes de acessar qualquer dado.
              </div>
            </div>
            <div className="pill pillSoft">{getActiveClientName()}</div>
          </div>
        </section>

        <div className="onboardingConnections">
          <div className="onboardingConnBlock">
            <div className="h1">Fonte principal do dashboard</div>
            <div className="p">A conexao organica do cliente ativo libera os KPIs, comentarios, media e stories.</div>
            <div className={`pill ${dashboardReady ? "pillSoft" : "pillDanger"}`} style={{ marginTop: 10 }}>
              {dashboardReady
                ? `Ativa: ${connectionLabel(activeOrganicConnection!)}`
                : "Conexão ainda não configurada"}
            </div>
            <div className="smallMuted" style={{ marginTop: 10 }}>
              Ultimo sync: {fmtDate(activeOrganicConnection?.last_synced_at || activeOrganicConnection?.last_sync_at)}
            </div>
          </div>

          <div className="onboardingConnBlock">
            <div className="h1">Fontes adicionais</div>
            <div className="p">
              O frontend local usa a stack atual de Instagram, Meta Ads e Google Analytics do cliente ativo.
            </div>
            <div className={`pill ${paidConnections.length ? "pillSoft" : "pillDanger"}`} style={{ marginTop: 10 }}>
              {paidConnections.length
                ? `${paidConnections.length} conexao(oes) de Ads encontrada(s)`
                : "Nenhuma conexao de Ads vinculada"}
            </div>
            <div className="smallMuted" style={{ marginTop: 10 }}>
              Total de integracoes cadastradas: {connections.length}
            </div>
          </div>
        </div>

        <section className="card cardWide">
          <div className="sectionHeader">
            <div>
              <div className="h1">Plataformas disponíveis</div>
              <div className="p">Cada produto possui autorização, estado e dados isolados por empresa.</div>
            </div>
            <button
              type="button"
              className="btn btnGhost"
              disabled={canonicalIntegrations.isRefreshing}
              onClick={() => {
                void canonicalIntegrationsRefetch();
              }}
              data-testid="refresh-canonical-integrations"
            >
              {canonicalIntegrations.isRefreshing ? "Verificando..." : "Verificar status"}
            </button>
          </div>
          {canonicalIntegrations.error ? (
            <div className="smallMuted" style={{ marginTop: 8 }} role="status">
              Não foi possível atualizar agora. Exibindo o último estado salvo.
            </div>
          ) : null}
          <div className="onboardingConnections">
            {INTEGRATION_REGISTRY.filter((definition) => definition.availability === "available").map((definition) => {
              const activeClientId = getActiveClientId();
              const matchingConnections =
                definition.id === "ga4"
                  ? genericConnections.filter((item) =>
                      item.capabilities?.ga4_authorized === true &&
                      isUsableGoogleConnection(item, "ga4", activeClientId)
                    )
                  : definition.id === "google_ads"
                    ? genericConnections.filter((item) =>
                        item.capabilities?.ads_authorized === true &&
                        isUsableGoogleConnection(item, "google_ads", activeClientId)
                      )
                    : definition.id === "meta"
                      ? genericConnections.filter((item) => isUsableMetaConnection(item, activeClientId))
                      : genericConnections.filter((item) => definition.providerIds.includes(item.provider));
              const requestedAuthorizationId = definition.id === "meta"
                ? selectedMetaAuthorizationId
                : definition.id === "ga4"
                  ? selectedGoogleAuthorizationIds.ga4
                  : definition.id === "google_ads"
                    ? selectedGoogleAuthorizationIds.google_ads
                    : "";
              const connection = definition.id === "meta"
                ? selectUsableMetaConnection(genericConnections, activeClientId, requestedAuthorizationId) || undefined
                : definition.id === "ga4"
                  ? selectUsableGoogleConnection(genericConnections, "ga4", activeClientId, requestedAuthorizationId) || undefined
                    : definition.id === "google_ads"
                      ? selectUsableGoogleConnection(genericConnections, "google_ads", activeClientId, requestedAuthorizationId) || undefined
                    : definition.id === "shopify"
                      ? matchingConnections.find((item) => item.id === getSelectedConnectionId(activeClientId, "shopify")) || matchingConnections[0]
                      : undefined;
              const canonicalEntry = (canonicalIntegrations.lastValidConnections || []).find(
                (item) => item.provider === definition.id
              );
              const metaConnected =
                definition.id === "meta" && (dashboardReady || paidConnections.length > 0);
              const productStatus = definition.id === "ga4"
                ? connection?.capabilities?.ga4_status
                : definition.id === "google_ads"
                  ? connection?.capabilities?.ads_status
                  : null;
              const status = !connection && matchingConnections.length > 0
                ? "Selecione uma autorização"
                : productStatus === "authorization_required"
                ? "Autorização incompleta"
                : productStatus === "property_required"
                  ? "Propriedade pendente"
                : productStatus === "stream_required"
                  ? "Stream pendente"
                : productStatus === "account_required"
                  ? "Conta pendente"
                  : productStatus === "setup_required"
                    ? "Configuração externa pendente"
                    : productStatus === "connected"
                      ? "Conectado"
                : definition.id === "meta" && !metaAdsOperational
                  ? "Conta de anúncios pendente"
                : connection
                  ? statusLabel(connection.status)
                : metaConnected
                  ? "Conectado"
                  : definition.availability === "available"
                    ? "Não conectado"
                    : unavailableIntegrationLabel(definition.availability);
              // O contrato canônico é a única fonte do estado visual final
              // do card quando já existe uma conexão canônica; os estados de
              // pré-seleção (nenhuma autorização escolhida ainda) continuam
              // vindos do fluxo OAuth existente, que não é alterado aqui.
              const connectionState = String(connection?.status || "").toLowerCase();
              const shopifyNeedsReauth = definition.id === "shopify" && Boolean(connection) &&
                connectionState !== "disconnected" && !connection?.scopes?.includes("read_all_orders");
              const displayStatus = shopifyNeedsReauth
                ? "Atualização de permissão necessária"
                : canonicalEntry
                ? canonicalStatusLabel(canonicalEntry, canonicalIntegrations.isRefreshing)
                : status;
              const actionable = definition.availability === "available";
              // FBITS não usa OAuth: conexão por token no FbitsIntegrationPanel.
              const shouldAuthorize = actionable && definition.id !== "fbits" && (
                (!connection && matchingConnections.length === 0) ||
                (definition.id !== "shopify" && ["disconnected", "expired", "token_expired", "reauth_required"].includes(connectionState))
              );
              const tone = definition.availability === "platform_update_pending"
                ? "yellow"
                : definition.id === "meta" && !metaAdsOperational
                  ? "yellow"
                : connectionTone(productStatus || connection?.status || (metaConnected ? "connected" : ""));
              const displayTone = shopifyNeedsReauth ? "yellow" : canonicalEntry ? canonicalStatusTone(canonicalEntry) : tone;
              const platformBrand = getIntegrationPlatformBrand(definition.id);
              return (
              <div className={`onboardingConnBlock is-${displayTone}`} key={definition.id}>
                <div className="integrationCardHeading">
                  {platformBrand ? <PlatformLogo platform={platformBrand} size={44} className="integrationOfficialLogo" /> : null}
                  <div>
                    <div className="h1">{definition.name}</div>
                    <div className="smallMuted">{definition.resources.join(" · ")}</div>
                  </div>
                </div>
                <div className="integrationStateRow">
                  {definition.availability === "platform_update_pending" ? (
                    <>
                      <span className={`integrationLight is-${displayTone}`} aria-hidden="true" />
                      <strong>Em desenvolvimento</strong>
                    </>
                  ) : canonicalEntry ? (
                    <StatusBadge
                      label={displayStatus}
                      tone={shopifyNeedsReauth ? "warning" : canonicalStatusBadgeTone(canonicalEntry, canonicalIntegrations.isRefreshing) as StatusTone}
                    />
                  ) : (
                    <>
                      <span className={`integrationLight is-${displayTone}`} aria-hidden="true" />
                      <strong>{displayStatus}</strong>
                    </>
                  )}
                </div>
                {definition.id === "meta" ? <div className="smallMuted" style={{ marginTop: 8 }}>
                  Meta Ads: {metaAdsOperational ? "conectado" : "pendente"}<br />
                  Instagram orgânico: {dashboardReady ? "conectado" : "configuração pendente"}
                </div> : null}
                {canonicalEntry && canonicalAccountLabel(canonicalEntry) ? (
                  <div className="smallMuted" style={{ marginTop: 8 }}>Conta: {canonicalAccountLabel(canonicalEntry)}</div>
                ) : null}
                {canonicalEntry?.last_error ? (
                  <div className="integrationErrorNotice" style={{ marginTop: 8 }}>
                    <p>{humanizeIntegrationError(canonicalEntry.last_error, definition.name)}</p>
                    <details>
                      <summary>Detalhes técnicos</summary>
                      <span>{canonicalEntry.last_error}</span>
                    </details>
                  </div>
                ) : null}
                {shopifyNeedsReauth ? (
                  <div className="integrationErrorNotice" style={{ marginTop: 8 }}>
                    <p>Atualize a autorização da Shopify para liberar o histórico completo de pedidos.</p>
                  </div>
                ) : null}
                {(() => {
                  const needsAttention =
                    !canonicalEntry || shopifyNeedsReauth || shouldAuthorize || connectionState === "selection_required" || matchingConnections.length > 1;
                  const isExpanded = expandedOverrides[definition.id] ?? needsAttention;
                  return (
                    <>
                      <button
                        type="button"
                        className="btn btnGhost integrationManageToggle"
                        onClick={() =>
                          setExpandedOverrides((current) => ({ ...current, [definition.id]: !isExpanded }))
                        }
                        aria-expanded={isExpanded}
                      >
                        {isExpanded ? "Ocultar detalhes" : "Gerenciar"}
                      </button>
                      {isExpanded ? (<>
                {definition.id === "meta" || definition.id === "ga4" || definition.id === "google_ads" ? (
                  <div style={{ marginTop: 12 }}>
                    <AssetCombobox
                      label="Autorização"
                      placeholder="Selecione a autorização"
                      value={requestedAuthorizationId}
                      disabled={!canManageConnections || saving}
                      options={matchingConnections.map((item) => ({
                        value: item.id,
                        label: item.account_name || item.external_key || item.id,
                        subtitle: definition.name,
                        meta: item.external_key && item.external_key !== item.account_name ? item.external_key : undefined,
                      }))}
                      emptyMessage="Nenhuma autorização encontrada."
                      onChange={(id) => {
                        if (definition.id === "meta") {
                          setSelectedMetaAuthorizationId(id);
                          setSelectedConnectionId(activeClientId, "meta", id || null);
                          setManualMetaConnectionId(null);
                        } else {
                          const provider = definition.id as "ga4" | "google_ads";
                          setSelectedGoogleAuthorizationIds((current) => ({ ...current, [provider]: id }));
                          setSelectedConnectionId(activeClientId, provider, id || null);
                          setGooglePickerId(null);
                          setGooglePickerProduct(null);
                        }
                      }}
                    />
                  </div>
                ) : null}
                {canonicalEntry ? (
                  <div className="smallMuted" style={{ marginTop: 10 }} data-testid={`integration-account-${definition.id}`}>
                    {canonicalAccountLabel(canonicalEntry) ? <>Conta: {canonicalAccountLabel(canonicalEntry)}<br /></> : null}
                    Última sincronização: {fmtDate(canonicalEntry.last_sync_at)}
                    {canonicalEntry.last_error ? <><br />{canonicalEntry.last_error}</> : null}
                    {canonicalIntegrations.isRefreshing ? <><br />Atualizando…</> : null}
                  </div>
                ) : (definition.id === "meta" ? selectedPaidConnection?.ad_account_name : connection?.account_name) ? (
                  <div className="smallMuted" style={{ marginTop: 10 }}>
                    Conta: {definition.id === "meta" ? selectedPaidConnection?.ad_account_name : connection?.account_name}<br />
                    {definition.id === "meta" && selectedPaidConnection?.ad_account_id ? <>{selectedPaidConnection.ad_account_id}<br /></> : null}
                    Última sincronização: {fmtDate(definition.id === "meta" ? selectedPaidConnection?.last_sync_at || selectedPaidConnection?.last_synced_at : connection?.last_sync_at)}
                  </div>
                ) : null}
                {definition.id === "shopify" ? (
                  <>
                    {matchingConnections.length > 1 ? (
                      <select
                        value={connection?.id || ""}
                        onChange={(event) => void onSelectShopify(event.target.value)}
                        disabled={!canManageConnections || saving}
                        style={{ marginTop: 12, width: "100%" }}
                      >
                        <option value="">Selecione a loja dos relatórios</option>
                        {matchingConnections.map((item) => (
                          <option key={item.id} value={item.id}>
                            {String(item.metadata?.shop_domain || item.external_key || item.account_name || item.id)}
                          </option>
                        ))}
                      </select>
                    ) : null}
                    <input
                      type="text"
                      value={shopifyDomain}
                      onChange={(event) => setShopifyDomain(event.target.value)}
                      placeholder="minhaloja.myshopify.com"
                      disabled={!canManageConnections || oauthLoading}
                      style={{ marginTop: 12, width: "100%" }}
                    />
                  </>
                ) : null}
                {definition.id === "fbits" ? (
                  <FbitsIntegrationPanel
                    entry={canonicalEntry}
                    canManage={canManageConnections}
                    onChanged={async () => { await loadConnections(); }}
                  />
                ) : null}
                {definition.id === "meta" && connectionState === "selection_required" && connection ? (
                  <button
                    className="btn btnGhost"
                    type="button"
                    style={{ marginTop: 12 }}
                    disabled={!canManageConnections || saving}
                    onClick={() => void onResumeMetaSelection(connection)}
                  >
                    {saving ? "Carregando ativos..." : "Selecionar ativos"}
                  </button>
                ) : shouldAuthorize ? (
                  <button
                    className="btn btnGhost"
                    type="button"
                    style={{ marginTop: 12 }}
                    disabled={!canManageConnections || oauthLoading}
                    onClick={
                      definition.id === "meta"
                        ? () => void onStartOAuth()
                        : definition.id === "ga4"
                          ? () => void onStartGoogleOAuth("ga4")
                          : definition.id === "google_ads"
                            ? () => void onStartGoogleOAuth("google_ads")
                          : () => void onStartShopifyOAuth()
                    }
                  >
                    {connectionState === "error" ? "Corrigir conexão" : ["expired", "token_expired", "reauth_required"].includes(connectionState) ? "Reconectar" : definition.actionLabel}
                  </button>
                ) : null}
                {connection ? (
                  <div className="onboardingConnActions" style={{ marginTop: 10 }}>
                    {definition.id === "meta" ? (
                      <>
                        {!dashboardReady ? <button
                          className="btn btnGhost"
                          type="button"
                          disabled={!canManageConnections || saving}
                          onClick={() => connection && void onResumeMetaSelection(connection)}
                        >
                          Configurar Instagram orgânico
                        </button> : null}
                        <button
                          className="btn btnGhost"
                          type="button"
                          disabled={!canManageConnections || saving}
                          onClick={() => {
                            if (!connection) return;
                            setManualMetaConnectionId(connection.id);
                            setManualPageId(String(connection.metadata?.selected_page_id || ""));
                            setManualInstagramId(String(connection.metadata?.selected_instagram_id || ""));
                            setManualAdAccountId(String(connection.metadata?.selected_ad_account_id || ""));
                            setManualMetaValidation(null);
                          }}
                        >
                          Configuração avançada por ID
                        </button>
                        <button className="btn btnGhost" type="button" disabled={!canManageConnections || saving} onClick={() => void onOpenMetaAdsPicker()}>
                          Selecionar conta
                        </button>
                        <button className="btn btnGhost" type="button" disabled={!canManageConnections || saving || !metaAdsOperational} onClick={() => void onSyncMetaAdsNow()}>
                          Sincronizar agora
                        </button>
                      </>
                    ) : null}
                    {definition.id === "ga4" || definition.id === "google_ads" ? (
                      <>
                        <button
                          className="btn btnGhost"
                          type="button"
                          disabled={!canManageConnections || saving || status === "Autorização incompleta" || status === "Não conectado" || status === "Configuração externa pendente"}
                          onClick={() => void onManageGoogle(connection, definition.id === "ga4" ? "ga4" : "ads")}
                        >
                          {definition.id === "ga4" ? "Selecionar propriedade" : "Selecionar conta"}
                        </button>
                        {definition.id === "ga4" ? <button className="btn btnGhost" type="button" disabled={!canManageConnections || saving || status !== "Conectado"} onClick={() => void onSyncGoogle(connection)}>
                          Atualizar dados
                        </button> : null}
                      </>
                    ) : null}
                    {definition.id === "shopify" ? (
                      <>
                        <button
                          className="btn btnPrimary"
                          type="button"
                          disabled={!canManageConnections || oauthLoading}
                          onClick={() => void onStartShopifyOAuth(String(connection.metadata?.shop_domain || connection.external_key || ""))}
                        >
                          {oauthLoading ? "Abrindo Shopify..." : connectionState === "disconnected" ? "Conectar Shopify" : "Atualizar permissões"}
                        </button>
                        {connectionState !== "disconnected" ? <button
                          className="btn btnGhost"
                          type="button"
                          disabled={!canManageConnections || saving}
                          onClick={() => void onSyncShopify(connection.id)}
                        >
                          Atualizar dados
                        </button> : null}
                      </>
                    ) : null}
                    {connectionState !== "disconnected" ? <button className="btn btnGhost" type="button" disabled={!canManageConnections || disconnectingId === connection.id} onClick={() => void onDisconnectGeneric(connection)}>
                      {disconnectingId === connection.id ? "Desconectando..." : "Desconectar"}
                    </button> : definition.id === "shopify" ? <span className="smallMuted">Dados históricos preservados.</span> : null}
                  </div>
                ) : null}
                      </>) : null}
                    </>
                  );
                })()}
              </div>
              );
            })}
          </div>

          {INTEGRATION_REGISTRY.some((definition) => definition.availability !== "available") ? (
            <div className="onboardingComingSoon">
              <span className="smallMuted">Em breve:</span>
              {INTEGRATION_REGISTRY.filter((definition) => definition.availability !== "available").map((definition) => (
                <span className="onboardingComingSoonPill" key={definition.id}>{definition.shortName}</span>
              ))}
            </div>
          ) : null}
        </section>

        {activeRole === "agency_admin" ? (
          <section className="card cardWide" aria-label="Diagnóstico temporário de integrações">
            <div className="h1">Diagnóstico temporário</div>
            <div className="smallMuted" style={{ marginTop: 10 }}>
              Meta — tenant: {getActiveClientId()} · autorização: {selectedMetaAuthorizationId || "não selecionada"} · páginas descobertas: {pendingAssets?.page_count ?? pendingAssets?.pages?.length ?? 0} · página escolhida: {Object.keys(selectedPages).find((id) => selectedPages[id]) || "-"} · Instagram escolhido: {Object.keys(selectedIg).find((id) => selectedIg[id]) || "-"} · último sync: {fmtDate(activeOrganicConnection?.last_synced_at || activeOrganicConnection?.last_sync_at)} · último código: {lastIntegrationDiagnostic.code || "-"} · request_id: {lastIntegrationDiagnostic.requestId || pendingAssets?.request_id || "-"}<br />
              GA4 — autorização: {selectedGoogleAuthorizationIds.ga4 || "não selecionada"} · status: {selectUsableGoogleConnection(genericConnections, "ga4", getActiveClientId(), selectedGoogleAuthorizationIds.ga4)?.status || "não configurada"} · propriedades: {lastIntegrationDiagnostic.propertyCount} · propriedade: {selectedGoogleProperty || lastIntegrationDiagnostic.propertyId || "-"} · streams: {lastIntegrationDiagnostic.streamCount} · stream: {selectedGoogleStream || lastIntegrationDiagnostic.streamId || "-"} · último sync: {lastIntegrationDiagnostic.ga4LastSync || "-"} · último código: {lastIntegrationDiagnostic.code || "-"} · request_id: {lastIntegrationDiagnostic.requestId || "-"}<br />
              Google Ads — autorização: {selectedGoogleAuthorizationIds.google_ads || "não selecionada"} · conexão bloqueada: {lastIntegrationDiagnostic.adsBlockedReason ? "sim" : "não"} · motivo: {lastIntegrationDiagnostic.adsBlockedReason || "-"}
              <br />Atualizar dados — {syncRuntime.length ? syncRuntime.map((item) => `${String(item.provider || "-")}: ${String(item.status || "-")} · ${String(item.endpoint || "-")} · conexão ${String(item.connection_id || "-")} · código ${String(item.code || "-")} · request_id ${String(item.request_id || "-")} · linhas ${String(item.rows_written ?? 0)} · ${String(item.started_at || "-")} → ${String(item.finished_at || "-")}`).join(" | ") : "nenhuma ação disparada"}
            </div>
          </section>
        ) : null}

        {googlePickerId ? (
          <section className="card cardWide onboardingFinalizeCard" aria-live="polite">
            <div className="h1">{googlePickerProduct === "ga4" ? "Selecionar propriedade GA4" : "Selecionar conta Google Ads"}</div>
            <div className="p">A seleção será vinculada somente à empresa ativa.</div>
            {googlePickerProduct === "ga4" ? <div style={{ display: "grid", gap: 14 }}>
              <AssetCombobox
                label="Propriedade GA4"
                placeholder="Selecione uma propriedade"
                value={selectedGoogleProperty}
                onChange={(propertyId) => void onSelectGooglePropertyForStreams(propertyId)}
                emptyMessage="Nenhuma propriedade encontrada."
                options={googleProperties.map((property) => ({
                  value: property.property || "",
                  label: property.property_name || property.property || "",
                  subtitle: property.account_name || "Conta GA4",
                  meta: property.property || undefined,
                }))}
              />
              <AssetCombobox
                label="Stream GA4"
                placeholder="Selecione um stream"
                value={selectedGoogleStream}
                onChange={setSelectedGoogleStream}
                emptyMessage="Nenhum stream encontrado."
                options={googleStreams.map((stream) => {
                  const streamId = String(stream.name || "").split("/").pop() || "";
                  return {
                    value: streamId,
                    label: stream.display_name || streamId,
                    subtitle: stream.type || "STREAM",
                    meta: streamId,
                  };
                })}
              />
            </div> : null}
            {googlePickerProduct === "ads" ? <div style={{ marginTop: 14 }}>
              <AssetCombobox
                label="Conta Google Ads"
                placeholder="Selecione a conta de anúncios"
                value={selectedGoogleAds}
                onChange={setSelectedGoogleAds}
                error={googleAdsListError}
                emptyMessage={googleAdsListError ? "Não foi possível carregar as contas." : "Nenhuma conta encontrada."}
                options={googleAdsAccounts.map((account) => ({
                  value: account.customer_id,
                  label: formatGoogleAdsAccountLabel(account),
                  subtitle: googleAdsAccountSubtitle(account),
                  status: googleAdsAccountStatus(account),
                }))}
              />
              {selectedGoogleAdsAccount ? (
                <div className="smallMuted" style={{ marginTop: 8 }} data-testid="google-ads-selected" role="status">
                  ✓ <strong>{selectedGoogleAdsAccount.descriptive_name || "Conta Google Ads"}</strong><br />
                  ID: {formatGoogleAdsCustomerId(selectedGoogleAdsAccount.customer_id)}
                  {selectedGoogleAdsAccount.access === "manager" && selectedGoogleAdsAccount.manager_customer_id
                    ? <><br />Acesso via conta administradora {formatGoogleAdsCustomerId(selectedGoogleAdsAccount.manager_customer_id)}</>
                    : null}
                  {selectedGoogleAdsAccount.is_manager
                    ? <><br />Conta administradora: não possui campanhas próprias. Selecione uma conta de anúncios.</>
                    : null}
                </div>
              ) : null}
            </div> : null}
            {googlePickerProduct === "ads" && googleAdsNotice ? <div className="smallMuted" style={{ marginTop: 8 }}>{googleAdsNotice}</div> : null}
            <div className="onboardingHeroActions" style={{ marginTop: 16 }}>
              <button
                className="btn btnPrimary"
                type="button"
                disabled={saving || (googlePickerProduct === "ads" && !googleAdsReady)}
                onClick={() => void onSaveGoogleSelection()}
              >
                {googlePickerProduct === "ads"
                  ? (saving ? "Conectando..." : "Conectar Google Ads")
                  : (saving ? "Salvando..." : "Salvar seleção")}
              </button>
              <button className="btn btnGhost" type="button" onClick={() => { setGooglePickerId(null); setGooglePickerProduct(null); }}>Cancelar</button>
            </div>
          </section>
        ) : null}

        {manualMetaConnectionId ? (
          <section ref={manualMetaFormRef} className="card cardWide onboardingFinalizeCard" aria-live="polite">
            <div className="h1">Configuração avançada por ID</div>
            <div className="p">Use IDs exibidos no Meta Business Suite. Os ativos serão consultados com a autorização atual antes de salvar; nenhum token é exibido.</div>
            <div className="smallMuted" data-testid="manual-meta-debug">
              Conexão Meta selecionada: {manualMetaConnectionId.slice(0, 8)} · Tenant: {getActiveClientId()} · Autorização: {selectedMetaAuthorizationId.slice(0, 8)} ·
              Provider: {metaGenericConnection?.provider || "-"} · Status: {metaGenericConnection?.status || "-"} · Client: {metaGenericConnection?.client_id || "-"} · Token disponível: {metaGenericConnection?.token_available === false ? "não" : "sim"}
            </div>
            <label className="smallMuted" style={{ display: "block", marginTop: 12 }}>
              Facebook Page ID — encontrado nas informações da Página
              <input value={manualPageId} onChange={(event) => { setManualPageId(event.target.value); setManualMetaValidation(null); }} placeholder="Ex.: 123456789012345" style={{ width: "100%", marginTop: 6 }} />
            </label>
            <label className="smallMuted" style={{ display: "block", marginTop: 12 }}>
              Instagram Business Account ID — ID da conta profissional vinculada
              <input value={manualInstagramId} onChange={(event) => { setManualInstagramId(event.target.value); setManualMetaValidation(null); }} placeholder="Ex.: 17841400000000000" style={{ width: "100%", marginTop: 6 }} />
            </label>
            <label className="smallMuted" style={{ display: "block", marginTop: 12 }}>
              Meta Ad Account ID — Gerenciador de Anúncios
              <input value={manualAdAccountId} onChange={(event) => { setManualAdAccountId(event.target.value); setManualMetaValidation(null); }} placeholder="Ex.: act_123456789 ou 123456789" style={{ width: "100%", marginTop: 6 }} />
            </label>
            {manualMetaValidation ? <div className="smallMuted" style={{ marginTop: 14 }}>
              Página: {manualMetaValidation.page?.name || "não alterada"}<br />
              Instagram: {manualMetaValidation.instagram?.username ? `@${manualMetaValidation.instagram.username}` : "não alterado"}<br />
              Conta Ads: {manualMetaValidation.ad_account?.name || "não alterada"}
            </div> : null}
            <div className="onboardingHeroActions" style={{ marginTop: 16 }}>
              <button className="btn btnGhost" type="button" disabled={saving} onClick={() => void onValidateManualMetaAssets()}>{saving ? "Validando..." : "Validar IDs"}</button>
              <button className="btn btnPrimary" type="button" disabled={saving || !manualMetaValidation} onClick={() => void onSaveManualMetaAssets()}>Salvar ativos</button>
              <button className="btn btnGhost" type="button" onClick={() => { setManualMetaConnectionId(null); setManualMetaValidation(null); }}>Cancelar</button>
            </div>
          </section>
        ) : null}

        {metaAdsPickerOpen ? (
          <section className="card cardWide onboardingFinalizeCard" aria-live="polite">
            <div className="h1">Selecionar conta Meta Ads</div>
            <div className="p">Somente contas acessíveis pela autorização da empresa ativa são exibidas.</div>
            <AssetCombobox
              label="Conta de anúncios"
              placeholder="Selecione uma conta"
              value={selectedMetaAdsAccount}
              onChange={setSelectedMetaAdsAccount}
              emptyMessage="Nenhuma conta encontrada."
              options={metaAdsAccounts.map((account) => ({
                value: account.ad_account_id,
                label: account.ad_account_name || "Conta Meta Ads",
                subtitle: "Meta Ads",
                meta: account.ad_account_id,
              }))}
            />
            <div className="onboardingHeroActions" style={{ marginTop: 16 }}>
              <button className="btn btnPrimary" type="button" disabled={saving || !selectedMetaAdsAccount} onClick={() => void onSaveMetaAdsAccount()}>
                {saving ? "Salvando..." : "Salvar conta"}
              </button>
              <button className="btn btnGhost" type="button" onClick={() => setMetaAdsPickerOpen(false)}>Cancelar</button>
            </div>
          </section>
        ) : null}

        {pendingAssets ? (
          <section className="card cardWide">
            <div className="sectionHeader">
              <div>
                <div className="h1">Concluir conexão Meta</div>
                <div className="p">
                  A autorização foi concluída. Selecione os ativos e salve para manter a conexão após sair ou recarregar.
                </div>
              </div>
            </div>

            <div className="smallMuted" style={{ marginBottom: 10 }}>
              Conta autorizada: {pendingAssets.meta_user?.name || "-"} ({pendingAssets.meta_user?.id || "-"})
            </div>

            <div className="onboardingAssets">
              <div className="onboardingAssetBlock">
                <div className="smallMuted">Gerenciadores de Negócios</div>
                {(pendingAssets.business_managers || []).length === 0 ? (
                  <div className="smallMuted">
                    {(pendingAssets.scopes || []).includes("business_management")
                      ? "A conta autorizada não possui acesso a um Gerenciador de Negócios."
                      : "A permissão business_management não foi concedida."}
                  </div>
                ) : (
                  <div className="onboardingChecks">
                    {(pendingAssets.business_managers || []).map((business: MetaDiscoveredBusinessManager) => (
                      <div key={business.business_id} className="smallMuted">
                        {business.business_name || business.business_id} ({business.business_id})
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="onboardingAssetBlock">
                <div className="smallMuted">Páginas do Facebook</div>
                {(pendingAssets.pages || []).length === 0 ? (
                  <div className="smallMuted">Nenhuma Página acessível foi encontrada para a autorização atual.</div>
                ) : (
                  <div className="onboardingChecks">
                    {(pendingAssets.pages || []).map((page: MetaDiscoveredPageAsset) => (
                      <label key={page.page_id} className="onboardingCheck">
                        {(() => {
                          const linked = (pendingAssets.instagram_accounts || []).some(
                            (ig) => String(ig.business_id || "") === String(page.page_id || "")
                          );
                          return <>
                        <input
                          type="checkbox"
                          checked={Boolean(selectedPages[page.page_id])}
                          disabled={!linked}
                          onChange={(event) =>
                            setSelectedPages(event.target.checked ? { [page.page_id]: true } : {})
                          }
                        />
                        <span>{page.page_name || page.page_id} <span className="smallMuted">({linked ? page.page_id : "sem Instagram profissional"})</span></span>
                          </>;
                        })()}
                      </label>
                    ))}
                  </div>
                )}
              </div>

              <div className="onboardingAssetBlock">
                <div className="smallMuted">Instagram organico</div>
                {(pendingAssets.instagram_accounts || []).length === 0 ? (
                  <div className="smallMuted">Nenhum ativo de Instagram encontrado.</div>
                ) : (
                  <div className="onboardingChecks">
                    {(pendingAssets.instagram_accounts || []).map((ig: MetaDiscoveredInstagramAsset) => {
                      const id = String(ig.ig_user_id || "").trim();
                      if (!id) return null;
                      return (
                        <label key={id} className="onboardingCheck">
                          <input
                            type="checkbox"
                            checked={Boolean(selectedIg[id])}
                            onChange={(event) =>
                              setSelectedIg(event.target.checked ? { [id]: true } : {})
                            }
                          />
                          <span>
                            @{ig.username || id}{" "}
                            <span className="smallMuted">({ig.business_name || ig.business_id || "-"})</span>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="onboardingAssetBlock">
                <div className="smallMuted">Meta Ads</div>
                {(pendingAssets.ad_accounts || []).length === 0 ? (
                  <div className="smallMuted">Nenhuma conta de anuncios encontrada.</div>
                ) : (
                  <div className="onboardingChecks">
                    {(pendingAssets.ad_accounts || []).map((ad: MetaDiscoveredAdAccount) => {
                      const id = String(ad.ad_account_id || "").trim();
                      if (!id) return null;
                      return (
                        <label key={id} className="onboardingCheck">
                          <input
                            type="checkbox"
                            checked={Boolean(selectedAds[id])}
                            onChange={(event) =>
                              setSelectedAds(event.target.checked ? { [id]: true } : {})
                            }
                          />
                          <span>
                            {ad.ad_account_name || id} <span className="smallMuted">({id})</span>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            <div className="onboardingHeroActions" style={{ marginTop: 16 }}>
              <button className="btn btnPrimary" type="button" onClick={() => {
                void onLinkSelectedAssets();
              }} disabled={saving}>
                {saving ? "Salvando e importando..." : "Salvar conexão e importar dados"}
              </button>
              <button
                className="btn btnGhost"
                type="button"
                onClick={() => {
                  setPendingAssets(null);
                  setSelectedIg({});
                  setSelectedPages({});
                  setSelectedAds({});
                }}
              >
                Cancelar
              </button>
            </div>
          </section>
        ) : null}

        <section className="card cardWide">
          <div className="sectionHeader">
            <div>
              <div className="h1">Conexões cadastradas</div>
              <div className="p">
                Defina qual conexao organica alimenta o dashboard e desconecte ativos que nao devem mais ser usados.
              </div>
            </div>
          </div>

          {loading ? (
            <div className="smallMuted" style={{ marginTop: 12 }}>
              Carregando integracoes do cliente ativo...
            </div>
          ) : !connections.length ? (
            <div className="smallMuted" style={{ marginTop: 12 }}>
              Nenhuma integracao cadastrada ainda para o cliente ativo.
            </div>
          ) : (
            <div className="onboardingConnList" style={{ marginTop: 10 }}>
              {connections.map((connection) => {
                const organic = isOrganicConnection(connection);
                const isActiveOnDashboard = activeConnectionId === connection.id;
                const status = String(connection.status || "").toLowerCase();

                return (
                  <div key={connection.id} className="onboardingConnItem">
                    <div>
                      <b>{connectionLabel(connection)}</b>
                      <div className="smallMuted">
                        {organic ? "Instagram / Orgânico" : "Meta Ads / Pago"} • {statusLabel(status)}
                      </div>
                      <div className="smallMuted">Conectada em: {fmtDate(connection.connected_at)}</div>
                      <div className="smallMuted">
                        Ultimo sync: {fmtDate(connection.last_synced_at || connection.last_sync_at)}
                      </div>
                      {connection.last_error ? (
                        <div className="smallMuted">Erro recente: {connection.last_error}</div>
                      ) : null}
                    </div>

                    <div className="onboardingConnActions">
                      {organic && status === "active" ? (
                        <button
                          className="btn btnGhost"
                          type="button"
                          disabled={isActiveOnDashboard}
                          onClick={() => onUseConnection(connection)}
                        >
                          {isActiveOnDashboard ? "Ativa no painel" : "Usar no painel"}
                        </button>
                      ) : null}
                      <button
                        className="btn btnGhost"
                        type="button"
                        disabled={disconnectingId === connection.id}
                        onClick={() => void onDisconnect(connection)}
                      >
                        {disconnectingId === connection.id ? "Desconectando..." : "Desconectar"}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </main>
      <footer data-integration-build={INTEGRATION_BUILD_FEATURES} className="smallMuted" style={{ maxWidth: 1200, margin: "0 auto", padding: "0 20px 20px" }}>
        Versão: {shortCommit(FRONTEND_COMMIT_SHA)} · API: {shortCommit(backendCommitSha)}
      </footer>
    </div>
  );
}
