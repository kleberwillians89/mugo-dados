import { useCallback, useEffect, useMemo, useState } from "react";
import {
  disconnectClientConnection,
  configureExistingMetaOrganic,
  ApiError,
  disconnectGenericConnection,
  discoverClientMetaAssets,
  linkClientAssets,
  listClientConnections,
  listClientMetaAdsAccounts,
  listGenericConnections,
  isUsableGoogleConnection,
  listGoogleAdsAccounts,
  listGoogleGa4Properties,
  listGoogleGa4Streams,
  refreshAll,
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
import {
  getActiveConnectionId,
  setActiveConnectionId,
} from "../app/connectionState";
import type {
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
import MugoLogo from "../components/MugoLogo";
import "../components/mugo-logo.css";
import {
  INTEGRATION_REGISTRY,
  unavailableIntegrationLabel,
} from "../app/integrationRegistry";
import "../styles/onboarding.css";

type Props = {
  isAuthenticated?: boolean;
  initialError?: string | null;
  onCompleted?: () => Promise<void> | void;
  onLogout?: () => Promise<void> | void;
};

function fmtDate(value?: string | null): string {
  if (!value) return "-";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "-";
  return dt.toLocaleString("pt-BR");
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return `${error.message}${error.requestId ? ` Request ID: ${error.requestId}.` : ""}`;
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

function integrationLogoSrc(id: string): string | null {
  if (id === "meta") return "/logoinstagram.png";
  return null;
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

function pickDefaultOrganicConnectionId(
  connections: MetaConnection[],
  preferredConnectionId: string | null
): string | null {
  const organicConnections = connections.filter(isOrganicConnection);
  if (!organicConnections.length) return null;

  if (
    preferredConnectionId &&
    organicConnections.some((connection) => connection.id === preferredConnectionId)
  ) {
    return preferredConnectionId;
  }

  const activeOrganic = organicConnections.find(
    (connection) => String(connection.status || "").toLowerCase() === "active"
  );
  if (activeOrganic?.id) return activeOrganic.id;

  return organicConnections[0]?.id || null;
}

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
  const activeRole = getActiveClient()?.role || "viewer";
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
  const [activeConnectionId, setActiveConnection] = useState<string | null>(null);
  const [pendingAssets, setPendingAssets] = useState<MetaDiscoverAssetsResponse | null>(null);
  const [selectedIg, setSelectedIg] = useState<Record<string, boolean>>({});
  const [selectedPages, setSelectedPages] = useState<Record<string, boolean>>({});
  const [selectedAds, setSelectedAds] = useState<Record<string, boolean>>({});
  const [googlePickerId, setGooglePickerId] = useState<string | null>(null);
  const [googlePickerProduct, setGooglePickerProduct] = useState<"ga4" | "ads" | null>(null);
  const [googleProperties, setGoogleProperties] = useState<GoogleGa4Property[]>([]);
  const [googleStreams, setGoogleStreams] = useState<GoogleGa4Stream[]>([]);
  const [googleAdsAccounts, setGoogleAdsAccounts] = useState<GoogleAdsAccount[]>([]);
  const [selectedGoogleProperty, setSelectedGoogleProperty] = useState("");
  const [selectedGoogleStream, setSelectedGoogleStream] = useState("");
  const [selectedGoogleAds, setSelectedGoogleAds] = useState("");
  const [googleAdsNotice, setGoogleAdsNotice] = useState("");
  const [metaAdsPickerOpen, setMetaAdsPickerOpen] = useState(false);
  const [metaAdsAccounts, setMetaAdsAccounts] = useState<MetaAdsSelectableAccount[]>([]);
  const [selectedMetaAdsAccount, setSelectedMetaAdsAccount] = useState("");
  const [oauthRetry, setOauthRetry] = useState<"meta_discover" | null>(null);
  const [manualMetaConnectionId, setManualMetaConnectionId] = useState<string | null>(null);
  const [manualPageId, setManualPageId] = useState("");
  const [manualInstagramId, setManualInstagramId] = useState("");
  const [manualAdAccountId, setManualAdAccountId] = useState("");
  const [manualMetaValidation, setManualMetaValidation] = useState<ManualMetaAssetsValidation | null>(null);

  const configWarning = getActiveClientConfigurationWarning();

  const prepareMetaAssets = useCallback((data: MetaDiscoverAssetsResponse) => {
    setPendingAssets(data);
    setSelectedIg(Object.fromEntries((data.instagram_accounts || []).map((item) => [String(item.ig_user_id || ""), true]).filter(([id]) => id)));
    setSelectedPages(Object.fromEntries((data.instagram_accounts || []).map((item) => [String(item.business_id || ""), true]).filter(([id]) => id)));
    setSelectedAds(Object.fromEntries((data.ad_accounts || []).map((item) => [String(item.ad_account_id || ""), true]).filter(([id]) => id)));
  }, []);

  const loadConnections = useCallback(async () => {
    const [response, genericResponse] = await Promise.all([
      listClientConnections(),
      listGenericConnections(),
    ]);
    const nextConnections = response.connections || [];
    setConnections(nextConnections);
    setGenericConnections(genericResponse.connections || []);

    const nextActiveConnectionId = pickDefaultOrganicConnectionId(
      nextConnections,
      getActiveConnectionId()
    );
    setActiveConnection(nextActiveConnectionId);
    setActiveConnectionId(nextActiveConnectionId);

    return nextConnections;
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
    const oauthError = String(params.get("error") || "").trim();

    if (!oauthStatus) return;
    let preserveMetaRetry = false;

    try {
      if (clientFromCallback && clientFromCallback !== getActiveClientId()) {
        throw new Error("O retorno da conexão não corresponde à empresa ativa.");
      }

      if (oauthStatus === "error") {
        throw new Error(oauthError || "Falha no OAuth da integracao.");
      }

      if (oauthStatus === "success" && handoff) {
        preserveMetaRetry = true;
        const data = await discoverClientMetaAssets(handoff);
        prepareMetaAssets(data);
        await loadConnections();
        setOauthRetry(null);
        preserveMetaRetry = false;
        setInfo("Autorizacao concluida. Revise os ativos do cliente ativo e finalize o vinculo.");
      } else if (oauthStatus === "success") {
         await loadConnections();
         const connectionId = String(params.get("connection_id") || "").trim();
         if (provider === "Google" && connectionId) {
           const product = params.get("integration_product") === "google_ads" ? "google_ads" : "ga4";
           const callbackConnections = (await listGenericConnections()).connections || [];
           const callbackConnection = callbackConnections.find((item) =>
             item.id === connectionId && isUsableGoogleConnection(item, product, getActiveClientId())
           );
           if (!callbackConnection) {
             throw new Error(`A conexão ${product === "google_ads" ? "Google Ads" : "GA4"} retornada não está ativa. Conecte novamente.`);
           }
          if (product === "ga4") {
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
            const ads = await listGoogleAdsAccounts(connectionId);
            setGooglePickerId(connectionId);
            setGooglePickerProduct("ads");
            setGoogleAdsAccounts(ads.accounts || []);
            setGoogleAdsNotice(ads.reason || "");
            setInfo("Google Ads autorizado. Selecione a conta para concluir.");
          }
        } else if (provider === "Shopify" && connectionId) {
          await syncShopifyConnection(connectionId);
          await loadConnections();
          setInfo("Shopify conectada e importação inicial concluída.");
        } else {
          setInfo(`${provider || "Integração"} conectada com sucesso.`);
        }
      }
    } catch (error: unknown) {
      setErr(errorMessage(error, "Falha ao processar o retorno do OAuth."));
      if (preserveMetaRetry) setOauthRetry("meta_discover");
    } finally {
      if (!preserveMetaRetry) clearOauthParamsFromUrl();
    }
  }, [loadConnections, prepareMetaAssets]);

  useEffect(() => {
    if (!isAuthenticated) return;

    let alive = true;
    setLoading(true);

    (async () => {
      try {
        const search = new URLSearchParams(window.location.search);
        const hasOauthReturn = search.has("meta_oauth") || search.has("google_oauth") || search.has("shopify_oauth");
        if (hasOauthReturn) await handleOauthRedirectParams();
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
  }, [handleOauthRedirectParams, isAuthenticated, loadConnections]);

  useEffect(() => {
    if (!initialError) return;
    setErr(initialError);
  }, [initialError]);

  const organicConnections = useMemo(
    () => connections.filter(isOrganicConnection),
    [connections]
  );
  const paidConnections = useMemo(
    () => connections.filter(isPaidConnection),
    [connections]
  );

  const activeOrganicConnection =
    organicConnections.find((connection) => connection.id === activeConnectionId) ||
    organicConnections.find((connection) => String(connection.status || "").toLowerCase() === "active") ||
    null;

  const dashboardReady = organicConnections.some(
    (connection) => String(connection.status || "").toLowerCase() === "active"
  );
  const metaGenericConnection = genericConnections.find((item) => item.provider === "meta") || null;
  const selectedPaidConnection = paidConnections.find((connection) =>
    String(connection.ad_account_id || "") === String(metaGenericConnection?.metadata?.selected_ad_account_id || "")
  ) || paidConnections.find((connection) => String(connection.status || "").toLowerCase() === "active") || null;
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
    if (!manualMetaConnectionId) return;
    setSaving(true);
    setErr(null);
    setManualMetaValidation(null);
    try {
      const result = await validateManualMetaAssets(manualMetaConnectionId, {
        page_id: manualPageId.trim() || undefined,
        instagram_id: manualInstagramId.trim() || undefined,
        ad_account_id: manualAdAccountId.trim() || undefined,
      });
      setManualMetaValidation(result);
      setInfo("Ativos validados com a autorização Meta atual. Revise os nomes antes de salvar.");
    } catch (error: unknown) {
      setErr(error instanceof ApiError && error.status === 404
        ? "A configuração manual Meta não está disponível nesta versão do servidor. Atualize o deploy do backend e tente novamente."
        : errorMessage(error, "Não foi possível validar os IDs Meta. Verifique os IDs, permissões e o vínculo entre Página e Instagram."));
    } finally {
      setSaving(false);
    }
  }

  async function onSaveManualMetaAssets() {
    if (!manualMetaConnectionId || !manualMetaValidation) return;
    const connection = genericConnections.find((item) => item.id === manualMetaConnectionId);
    const metadata = connection?.metadata || {};
    const replacing =
      (manualPageId.trim() && metadata.selected_page_id && manualPageId.trim() !== String(metadata.selected_page_id)) ||
      (manualInstagramId.trim() && metadata.selected_instagram_id && manualInstagramId.trim() !== String(metadata.selected_instagram_id)) ||
      (manualAdAccountId.trim() && metadata.selected_ad_account_id && manualAdAccountId.replace(/^act_/, "") !== String(metadata.selected_ad_account_id).replace(/^act_/, ""));
    if (replacing && !window.confirm("Substituir o ativo Meta atualmente selecionado para esta empresa?")) return;
    setSaving(true);
    setErr(null);
    try {
      await saveManualMetaAssets(manualMetaConnectionId, {
        page_id: manualPageId.trim() || undefined,
        instagram_id: manualInstagramId.trim() || undefined,
        ad_account_id: manualAdAccountId.trim() || undefined,
      });
      await loadConnections();
      setManualMetaConnectionId(null);
      setManualMetaValidation(null);
      setInfo("Ativos Meta validados e salvos para a empresa ativa.");
    } catch (error: unknown) {
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
    try {
      const result = await syncClientMetaAdsAccount(selectedPaidConnection.id);
      await loadConnections();
      const outcome = String(result.sync_outcome || result.job_status || "");
      setInfo(outcome === "success" ? "Meta Ads sincronizado e persistido." : `Sincronização Meta Ads: ${outcome || "resultado indisponível"}.`);
    } catch (error: unknown) {
      setErr(errorMessage(error, "A sincronização Meta Ads falhou."));
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

  async function onStartShopifyOAuth() {
    if (!canManageConnections) return;
    setOauthLoading(true);
    setErr(null);
    try {
      const response = await startShopifyOAuth(shopifyDomain);
      window.location.assign(response.authorization_url);
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
    try {
      await syncShopifyConnection(connectionId);
      await loadConnections();
      setInfo("Pedidos, clientes e produtos da Shopify foram atualizados.");
    } catch (error: unknown) {
      setErr(errorMessage(error, "Não foi possível sincronizar a loja Shopify."));
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
      const result = await linkClientAssets({
        handoff: pendingAssets.handoff,
        page_ids: pageIds,
        instagram_ig_user_ids: instagramIds,
        ad_account_ids: adAccountIds,
      });
      const savedConnections = Array.isArray(result.connections) ? result.connections : [];
      const organic = savedConnections.find((item) => item && typeof item === "object" && item.platform === "instagram");
      let initialSyncWarning = "";
      if (organic && typeof organic === "object" && typeof organic.id === "string") {
        try {
          await refreshAll(200, { connectionId: organic.id });
        } catch {
          initialSyncWarning = " A conexão foi salva; use Atualizar dados para repetir a importação.";
        }
      }
      setPendingAssets(null);
      setSelectedIg({});
      setSelectedPages({});
      setSelectedAds({});
      await loadConnections();
      setInfo(
        initialSyncWarning
          ? `Meta conectada.${initialSyncWarning}`
          : "Meta conectada. Ativos persistidos e importação inicial concluída."
      );
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
    try {
      const provider = product === "ga4" ? "ga4" : "google_ads";
      if (!isUsableGoogleConnection(connection, provider, getActiveClientId())) {
        setInfo(`Conecte ${product === "ga4" ? "o Google Analytics" : "o Google Ads"} antes de selecionar ativos.`);
        return;
      }
      if (product === "ga4") {
        const ga4 = await listGoogleGa4Properties(connection.id);
        setGooglePickerId(connection.id);
        setGooglePickerProduct(product);
        setGoogleProperties(ga4.properties || []);
        if (!(ga4.properties || []).length) setInfo(ga4.message || "O usuário Google autorizado não possui acesso a nenhuma propriedade GA4.");
      } else {
        const ads = await listGoogleAdsAccounts(connection.id);
        setGooglePickerId(connection.id);
        setGooglePickerProduct(product);
        setGoogleAdsAccounts(ads.accounts || []);
        setGoogleAdsNotice(ads.reason || "");
      }
      setSelectedGoogleProperty(String(connection.metadata?.ga4_property_id || ""));
      setSelectedGoogleStream(String(connection.metadata?.ga4_stream_id || ""));
      setSelectedGoogleAds(String(connection.metadata?.google_ads_customer_id || ""));
    } catch (error: unknown) {
      setErr(errorMessage(error, "Não foi possível consultar os ativos Google."));
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
    setSaving(true);
    setErr(null);
    try {
      if (googlePickerProduct === "ga4") {
        const property = googleProperties.find((item) => item.property === selectedGoogleProperty);
        await selectGoogleGa4Property(googlePickerId, selectedGoogleProperty, {
          accountId: property?.account,
          propertyName: property?.property_name,
          streamId: selectedGoogleStream,
        });
        await syncGoogleConnection(googlePickerId);
      } else if (selectedGoogleAds) {
        await selectGoogleAdsAccount(googlePickerId, selectedGoogleAds);
      }
      await loadConnections();
      setGooglePickerId(null);
      setGooglePickerProduct(null);
      setInfo(googlePickerProduct === "ga4" ? "Propriedade GA4 salva e sincronizada." : "Conta Google Ads salva.");
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
      if (streams.length === 1) {
        setSelectedGoogleStream(String(streams[0].name || "").split("/").pop() || "");
      }
      if (!streams.length) setErr("A propriedade não possui streams acessíveis.");
    } catch (error: unknown) {
      setErr(errorMessage(error, "Não foi possível listar os streams da propriedade."));
    } finally {
      setSaving(false);
    }
  }

  async function onSyncGoogle(connection: GenericConnection) {
    setSaving(true);
    setErr(null);
    try {
      await syncGoogleConnection(connection.id);
      await loadConnections();
      setInfo("Sincronização manual do GA4 concluída.");
    } catch (error: unknown) {
      setErr(errorMessage(error, "Não foi possível sincronizar o GA4."));
    } finally {
      setSaving(false);
    }
  }

  async function onDisconnectGeneric(connection: GenericConnection) {
    if (disconnectingId) return;
    if (!window.confirm("Desconectar esta integração? O histórico importado será preservado.")) return;
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
            ) : !metaGenericConnection || ["disconnected", "expired", "token_expired", "error", "reauth_required"].includes(String(metaGenericConnection.status || "").toLowerCase()) ? (
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
        {err ? <div className="pill pillDanger">
          {err}
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
                ? `Ativa: ${connectionLabel(activeOrganicConnection || organicConnections[0]!)}` 
                : "Nenhuma conexao organica ativa"}
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
          </div>
          <div className="onboardingConnections">
            {INTEGRATION_REGISTRY.map((definition) => {
              const activeClientId = getActiveClientId();
              const matchingConnections =
                definition.id === "ga4"
                  ? genericConnections.filter((item) =>
                      isUsableGoogleConnection(item, "ga4", activeClientId) && item.capabilities?.ga4_authorized === true
                    )
                  : definition.id === "google_ads"
                    ? genericConnections.filter((item) =>
                        isUsableGoogleConnection(item, "google_ads", activeClientId) && item.capabilities?.ads_authorized === true
                      )
                    : genericConnections.filter((item) => definition.providerIds.includes(item.provider));
              const connection =
                definition.id === "shopify"
                  ? matchingConnections.find(
                      (item) => Boolean(item.metadata?.selected_for_reporting)
                    ) || matchingConnections[0]
                  : matchingConnections[0];
              const metaConnected =
                definition.id === "meta" && (dashboardReady || paidConnections.length > 0);
              const productStatus = definition.id === "ga4"
                ? connection?.capabilities?.ga4_status
                : definition.id === "google_ads"
                  ? connection?.capabilities?.ads_status
                  : null;
              const status = productStatus === "authorization_required"
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
              const actionable = definition.availability === "available";
              const connectionState = String(connection?.status || "").toLowerCase();
              const shouldAuthorize = actionable && (
                !connection || ["disconnected", "expired", "token_expired", "error", "reauth_required"].includes(connectionState)
              );
              const tone = definition.availability === "platform_update_pending"
                ? "yellow"
                : definition.id === "meta" && !metaAdsOperational
                  ? "yellow"
                : connectionTone(productStatus || connection?.status || (metaConnected ? "connected" : ""));
              const logoSrc = integrationLogoSrc(definition.id);
              return (
              <div className={`onboardingConnBlock is-${tone}`} key={definition.id}>
                <div className="integrationCardHeading">
                  {logoSrc ? <img className="integrationOfficialLogo" src={logoSrc} alt={`${definition.name} logo`} /> : null}
                  <div>
                    <div className="h1">{definition.name}</div>
                    <div className="smallMuted">{definition.resources.join(" · ")}</div>
                  </div>
                </div>
                <div className="integrationStateRow">
                  <span className={`integrationLight is-${tone}`} aria-hidden="true" />
                  <strong>{definition.availability === "platform_update_pending" ? "Em desenvolvimento" : status}</strong>
                </div>
                {definition.id === "meta" ? <div className="smallMuted" style={{ marginTop: 8 }}>
                  Meta Ads: {metaAdsOperational ? "conectado" : "pendente"}<br />
                  Instagram orgânico: {dashboardReady ? "conectado" : "configuração pendente"}
                </div> : null}
                {(definition.id === "meta" ? selectedPaidConnection?.ad_account_name : connection?.account_name) ? (
                  <div className="smallMuted" style={{ marginTop: 10 }}>
                    Conta: {definition.id === "meta" ? selectedPaidConnection?.ad_account_name : connection?.account_name}<br />
                    {definition.id === "meta" && selectedPaidConnection?.ad_account_id ? <>{selectedPaidConnection.ad_account_id}<br /></> : null}
                    Última sincronização: {fmtDate(definition.id === "meta" ? selectedPaidConnection?.last_sync_at || selectedPaidConnection?.last_synced_at : connection?.last_sync_at)}
                  </div>
                ) : null}
                {connection ? <div className={`syncStateChip ${(definition.id === "meta" ? selectedPaidConnection?.last_error : connection.last_error) ? "is-error" : (definition.id === "meta" ? selectedPaidConnection?.last_sync_at : connection.last_sync_at) ? "is-updated" : "is-never"}`}>
                  {(definition.id === "meta" ? selectedPaidConnection?.last_error : connection.last_error) ? "Falha na sincronização" : (definition.id === "meta" ? selectedPaidConnection?.last_sync_at : connection.last_sync_at) ? `Atualizado · ${fmtDate(definition.id === "meta" ? selectedPaidConnection?.last_sync_at : connection.last_sync_at)}` : "Nunca sincronizado"}
                </div> : null}
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
                      <button
                        className="btn btnGhost"
                        type="button"
                        disabled={!canManageConnections || saving}
                        onClick={() => void onSyncShopify(connection.id)}
                      >
                        Atualizar dados
                      </button>
                    ) : null}
                    <button className="btn btnGhost" type="button" disabled={!canManageConnections || disconnectingId === connection.id} onClick={() => void onDisconnectGeneric(connection)}>
                      {disconnectingId === connection.id ? "Desconectando..." : "Desconectar"}
                    </button>
                  </div>
                ) : null}
              </div>
              );
            })}
          </div>
        </section>

        {googlePickerId ? (
          <section className="card cardWide onboardingFinalizeCard" aria-live="polite">
            <div className="h1">{googlePickerProduct === "ga4" ? "Selecionar propriedade GA4" : "Selecionar conta Google Ads"}</div>
            <div className="p">A seleção será vinculada somente à empresa ativa.</div>
            {googlePickerProduct === "ga4" ? <label className="smallMuted">
              Propriedade GA4
              <select value={selectedGoogleProperty} onChange={(event) => void onSelectGooglePropertyForStreams(event.target.value)} style={{ display: "block", width: "100%", marginTop: 8 }}>
                <option value="">Selecione uma propriedade</option>
                {googleProperties.map((property) => (
                  <option key={property.property} value={property.property}>
                    {property.account_name || "Conta"} — {property.property_name || property.property}
                  </option>
                ))}
              </select>
              <span style={{ display: "block", marginTop: 14 }}>Stream GA4</span>
              <select value={selectedGoogleStream} onChange={(event) => setSelectedGoogleStream(event.target.value)} style={{ display: "block", width: "100%", marginTop: 8 }}>
                <option value="">Selecione um stream</option>
                {googleStreams.map((stream) => {
                  const streamId = String(stream.name || "").split("/").pop() || "";
                  return <option key={stream.name || streamId} value={streamId}>{stream.display_name || streamId} — {stream.type || "STREAM"}</option>;
                })}
              </select>
            </label> : null}
            {googlePickerProduct === "ads" ? <label className="smallMuted" style={{ display: "block", marginTop: 14 }}>
              Conta Google Ads
              <select value={selectedGoogleAds} onChange={(event) => setSelectedGoogleAds(event.target.value)} style={{ display: "block", width: "100%", marginTop: 8 }}>
                <option value="">Nenhuma conta selecionada</option>
                {googleAdsAccounts.map((account) => (
                  <option key={account.customer_id} value={account.customer_id}>{account.customer_id}</option>
                ))}
              </select>
            </label> : null}
            {googlePickerProduct === "ads" && googleAdsNotice ? <div className="smallMuted" style={{ marginTop: 8 }}>{googleAdsNotice}</div> : null}
            <div className="onboardingHeroActions" style={{ marginTop: 16 }}>
              <button className="btn btnPrimary" type="button" disabled={saving} onClick={() => void onSaveGoogleSelection()}>
                {saving ? "Salvando..." : "Salvar seleção"}
              </button>
              <button className="btn btnGhost" type="button" onClick={() => { setGooglePickerId(null); setGooglePickerProduct(null); }}>Cancelar</button>
            </div>
          </section>
        ) : null}

        {manualMetaConnectionId ? (
          <section className="card cardWide onboardingFinalizeCard" aria-live="polite">
            <div className="h1">Configuração avançada por ID</div>
            <div className="p">Use IDs exibidos no Meta Business Suite. Os ativos serão consultados com a autorização atual antes de salvar; nenhum token é exibido.</div>
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
            <label className="smallMuted">
              Conta de anúncios
              <select value={selectedMetaAdsAccount} onChange={(event) => setSelectedMetaAdsAccount(event.target.value)} style={{ display: "block", width: "100%", marginTop: 8 }}>
                <option value="">Selecione uma conta</option>
                {metaAdsAccounts.map((account) => (
                  <option key={account.ad_account_id} value={account.ad_account_id}>
                    {account.ad_account_name || "Conta Meta Ads"} — {account.ad_account_id}
                  </option>
                ))}
              </select>
            </label>
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
                  <div className="smallMuted">Nenhuma Página associada a um Instagram profissional foi encontrada.</div>
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
                            setSelectedPages((prev) => ({
                              ...prev,
                              [page.page_id]: event.target.checked,
                            }))
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
                              setSelectedIg((prev) => ({
                                ...prev,
                                [id]: event.target.checked,
                              }))
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
                              setSelectedAds((prev) => ({
                                ...prev,
                                [id]: event.target.checked,
                              }))
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
              <button className="btn btnPrimary" type="button" onClick={() => void onLinkSelectedAssets()} disabled={saving}>
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
    </div>
  );
}
