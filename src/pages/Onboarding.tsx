import { useCallback, useEffect, useMemo, useState } from "react";
import {
  disconnectClientConnection,
  disconnectGenericConnection,
  discoverClientMetaAssets,
  linkClientAssets,
  listClientConnections,
  listGenericConnections,
  listGoogleAdsAccounts,
  listGoogleGa4Properties,
  selectGoogleAdsAccount,
  selectGoogleGa4Property,
  syncGoogleConnection,
  type GenericConnection,
  type GoogleAdsAccount,
  type GoogleGa4Property,
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
import logo from "../assets/mugo-logo.svg";
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
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return fallback;
}

function statusLabel(status: string): string {
  if (status === "active") return "Ativa";
  if (status === "needs_reauth") return "Reconectar";
  if (status === "error") return "Erro";
  if (status === "disconnected") return "Desconectada";
  return status || "-";
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
  const canManageConnections = activeRole === "agency_admin" || activeRole === "client_admin" || activeRole === "owner" || activeRole === "admin";
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
  const [googleProperties, setGoogleProperties] = useState<GoogleGa4Property[]>([]);
  const [googleAdsAccounts, setGoogleAdsAccounts] = useState<GoogleAdsAccount[]>([]);
  const [selectedGoogleProperty, setSelectedGoogleProperty] = useState("");
  const [selectedGoogleAds, setSelectedGoogleAds] = useState("");
  const [googleAdsNotice, setGoogleAdsNotice] = useState("");

  const configWarning = getActiveClientConfigurationWarning();

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

    try {
      if (clientFromCallback && clientFromCallback !== getActiveClientId()) {
        throw new Error("O retorno da conexão não corresponde à empresa ativa.");
      }

      if (oauthStatus === "error") {
        throw new Error(oauthError || "Falha no OAuth da integracao.");
      }

      if (oauthStatus === "success" && handoff) {
        const data = await discoverClientMetaAssets(handoff);
        setPendingAssets(data);

        const igMap: Record<string, boolean> = {};
        for (const ig of data.instagram_accounts || []) {
          const id = String(ig.ig_user_id || "").trim();
          if (id) igMap[id] = true;
        }
        const pageMap: Record<string, boolean> = {};
        for (const page of data.pages || []) {
          const id = String(page.page_id || "").trim();
          if (id) pageMap[id] = true;
        }

        const adMap: Record<string, boolean> = {};
        for (const ad of data.ad_accounts || []) {
          const id = String(ad.ad_account_id || "").trim();
          if (id) adMap[id] = true;
        }

        setSelectedIg(igMap);
        setSelectedPages(pageMap);
        setSelectedAds(adMap);
        await loadConnections();
        setInfo("Autorizacao concluida. Revise os ativos do cliente ativo e finalize o vinculo.");
      } else if (oauthStatus === "success") {
        await loadConnections();
        setInfo(`${provider || "Integração"} conectada com sucesso.`);
      }
    } catch (error: unknown) {
      setErr(errorMessage(error, "Falha ao processar o retorno do OAuth."));
    } finally {
      clearOauthParamsFromUrl();
    }
  }, [loadConnections]);

  useEffect(() => {
    if (!isAuthenticated) return;

    let alive = true;
    setLoading(true);

    (async () => {
      try {
        await loadConnections();
        await handleOauthRedirectParams();
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

  async function onStartGoogleOAuth() {
    if (!canManageConnections) return;
    setOauthLoading(true);
    setErr(null);
    try {
      const response = await startGoogleOAuth();
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
      await linkClientAssets({
        handoff: pendingAssets.handoff,
        page_ids: pageIds,
        instagram_ig_user_ids: instagramIds,
        ad_account_ids: adAccountIds,
      });
      setPendingAssets(null);
      setSelectedIg({});
      setSelectedPages({});
      setSelectedAds({});
      await loadConnections();
      setInfo("Ativos do cliente ativo vinculados com sucesso.");
    } catch (error: unknown) {
      setErr(errorMessage(error, "Erro ao vincular os ativos do cliente ativo."));
    } finally {
      setSaving(false);
    }
  }

  async function onDisconnect(connection: MetaConnection) {
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

  async function onManageGoogle(connection: GenericConnection) {
    setSaving(true);
    setErr(null);
    setInfo(null);
    try {
      const [ga4, ads] = await Promise.all([
        listGoogleGa4Properties(connection.id),
        listGoogleAdsAccounts(connection.id),
      ]);
      setGooglePickerId(connection.id);
      setGoogleProperties(ga4.properties || []);
      setGoogleAdsAccounts(ads.accounts || []);
      setGoogleAdsNotice(ads.reason || "");
      setSelectedGoogleProperty(String(connection.metadata?.ga4_property_id || ""));
      setSelectedGoogleAds(String(connection.metadata?.google_ads_customer_id || ""));
    } catch (error: unknown) {
      setErr(errorMessage(error, "Não foi possível consultar os ativos Google."));
    } finally {
      setSaving(false);
    }
  }

  async function onSaveGoogleSelection() {
    if (!googlePickerId || !selectedGoogleProperty) {
      setErr("Selecione ao menos uma propriedade GA4.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      await selectGoogleGa4Property(googlePickerId, selectedGoogleProperty);
      if (selectedGoogleAds) {
        await selectGoogleAdsAccount(googlePickerId, selectedGoogleAds);
      }
      await loadConnections();
      setGooglePickerId(null);
      setInfo("Ativos Google vinculados à empresa ativa.");
    } catch (error: unknown) {
      setErr(errorMessage(error, "Não foi possível salvar a seleção Google."));
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
          <img src={logo} alt={getActiveClientName()} className="onboardingLogo" />
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
            <button className="btn btnGold" type="button" disabled={oauthLoading || !canManageConnections} onClick={() => void onStartOAuth()}>
              {oauthLoading ? "Redirecionando..." : "Conectar com Facebook"}
            </button>
            <button className="btn btnPrimary" type="button" disabled={!dashboardReady} onClick={() => void onContinue()}>
              Abrir dashboard
            </button>
          </div>
        </section>

        {configWarning ? <div className="pill pillDanger">{configWarning}</div> : null}
        {err ? <div className="pill pillDanger">{err}</div> : null}
        {info ? <div className="pill pillSoft">{info}</div> : null}

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
              <div className="p">Meta, Google e Shopify usam autorização oficial e ficam isoladas por empresa.</div>
            </div>
          </div>
          <div className="onboardingConnections">
            {[
              ["Instagram e Meta Ads", dashboardReady || paidConnections.length ? "Conectada" : "Não configurada"],
              ["Google Ads e GA4", "Não configurada"],
              ["Shopify", "Não configurada"],
              ["TikTok", "Aguardando atualização da plataforma"],
              ["Pinterest", "Aguardando atualização da plataforma"],
              ["FBits", "Legado preservado"],
            ].map(([name, defaultStatus]) => {
              const providers =
                name === "Google Ads e GA4"
                  ? ["ga4", "google_ads"]
                  : name === "Shopify"
                    ? ["shopify"]
                    : [];
              const connection = genericConnections.find((item) => providers.includes(item.provider));
              const status = connection?.status || defaultStatus;
              return (
              <div className="onboardingConnBlock" key={name}>
                <div className="h1">{name}</div>
                <div className="pill pillSoft" style={{ marginTop: 10 }}>{status}</div>
                {connection?.account_name ? (
                  <div className="smallMuted" style={{ marginTop: 10 }}>
                    Conta: {connection.account_name}<br />
                    Última sincronização: {fmtDate(connection.last_sync_at)}
                  </div>
                ) : null}
                {name === "Shopify" ? (
                  <input
                    type="text"
                    value={shopifyDomain}
                    onChange={(event) => setShopifyDomain(event.target.value)}
                    placeholder="minhaloja.myshopify.com"
                    disabled={!canManageConnections || oauthLoading}
                    style={{ marginTop: 12, width: "100%" }}
                  />
                ) : null}
                {name === "Instagram e Meta Ads" || name === "Google Ads e GA4" || name === "Shopify" ? (
                  <button
                    className="btn btnGhost"
                    type="button"
                    style={{ marginTop: 12 }}
                    disabled={!canManageConnections || oauthLoading}
                    onClick={
                      name === "Instagram e Meta Ads"
                        ? () => void onStartOAuth()
                        : name === "Google Ads e GA4"
                          ? () => void onStartGoogleOAuth()
                          : () => void onStartShopifyOAuth()
                    }
                  >
                    {name === "Instagram e Meta Ads"
                      ? "Conectar com Facebook"
                      : name === "Google Ads e GA4"
                        ? "Conectar com Google"
                        : "Conectar minha loja"}
                  </button>
                ) : null}
                {connection ? (
                  <div className="onboardingConnActions" style={{ marginTop: 10 }}>
                    {name === "Google Ads e GA4" ? (
                      <>
                        <button className="btn btnGhost" type="button" disabled={!canManageConnections || saving} onClick={() => void onManageGoogle(connection)}>
                          Selecionar contas
                        </button>
                        <button className="btn btnGhost" type="button" disabled={!canManageConnections || saving || connection.status === "selection_required"} onClick={() => void onSyncGoogle(connection)}>
                          Atualizar dados
                        </button>
                      </>
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
          <section className="card cardWide">
            <div className="h1">Selecionar ativos Google</div>
            <div className="p">A seleção será vinculada somente à empresa ativa.</div>
            <label className="smallMuted">
              Propriedade GA4
              <select value={selectedGoogleProperty} onChange={(event) => setSelectedGoogleProperty(event.target.value)} style={{ display: "block", width: "100%", marginTop: 8 }}>
                <option value="">Selecione uma propriedade</option>
                {googleProperties.map((property) => (
                  <option key={property.property} value={property.property}>
                    {property.account_name || "Conta"} — {property.property_name || property.property}
                  </option>
                ))}
              </select>
            </label>
            <label className="smallMuted" style={{ display: "block", marginTop: 14 }}>
              Conta Google Ads (opcional)
              <select value={selectedGoogleAds} onChange={(event) => setSelectedGoogleAds(event.target.value)} style={{ display: "block", width: "100%", marginTop: 8 }}>
                <option value="">Nenhuma conta selecionada</option>
                {googleAdsAccounts.map((account) => (
                  <option key={account.customer_id} value={account.customer_id}>{account.customer_id}</option>
                ))}
              </select>
            </label>
            {googleAdsNotice ? <div className="smallMuted" style={{ marginTop: 8 }}>{googleAdsNotice}</div> : null}
            <div className="onboardingHeroActions" style={{ marginTop: 16 }}>
              <button className="btn btnPrimary" type="button" disabled={saving} onClick={() => void onSaveGoogleSelection()}>
                {saving ? "Salvando..." : "Salvar seleção"}
              </button>
              <button className="btn btnGhost" type="button" onClick={() => setGooglePickerId(null)}>Cancelar</button>
            </div>
          </section>
        ) : null}

        {pendingAssets ? (
          <section className="card cardWide">
            <div className="sectionHeader">
              <div>
                <div className="h1">Vincular ativos autorizados</div>
                <div className="p">
                  Revise os ativos descobertos para o cliente ativo e confirme o que deve ficar disponivel no painel.
                </div>
              </div>
            </div>

            <div className="smallMuted" style={{ marginBottom: 10 }}>
              Conta autorizada: {pendingAssets.meta_user?.name || "-"} ({pendingAssets.meta_user?.id || "-"})
            </div>

            <div className="onboardingAssets">
              <div className="onboardingAssetBlock">
                <div className="smallMuted">Páginas do Facebook</div>
                {(pendingAssets.pages || []).length === 0 ? (
                  <div className="smallMuted">Nenhuma Página associada a um Instagram profissional foi encontrada.</div>
                ) : (
                  <div className="onboardingChecks">
                    {(pendingAssets.pages || []).map((page: MetaDiscoveredPageAsset) => (
                      <label key={page.page_id} className="onboardingCheck">
                        <input
                          type="checkbox"
                          checked={Boolean(selectedPages[page.page_id])}
                          onChange={(event) =>
                            setSelectedPages((prev) => ({
                              ...prev,
                              [page.page_id]: event.target.checked,
                            }))
                          }
                        />
                        <span>{page.page_name || page.page_id} <span className="smallMuted">({page.page_id})</span></span>
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
                {saving ? "Vinculando..." : "Vincular ativos do cliente ativo"}
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
