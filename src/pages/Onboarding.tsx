import { useCallback, useEffect, useMemo, useState } from "react";
import {
  disconnectClientConnection,
  discoverClientMetaAssets,
  linkClientAssets,
  listClientConnections,
  startClientMetaOAuth,
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
} from "../app/types";
import {
  getActiveClientConfigurationWarning,
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
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [connections, setConnections] = useState<MetaConnection[]>([]);
  const [activeConnectionId, setActiveConnection] = useState<string | null>(null);
  const [pendingAssets, setPendingAssets] = useState<MetaDiscoverAssetsResponse | null>(null);
  const [selectedIg, setSelectedIg] = useState<Record<string, boolean>>({});
  const [selectedAds, setSelectedAds] = useState<Record<string, boolean>>({});

  const configWarning = getActiveClientConfigurationWarning();

  const loadConnections = useCallback(async () => {
    const response = await listClientConnections();
    const nextConnections = response.connections || [];
    setConnections(nextConnections);

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
    const oauthStatus = String(params.get("meta_oauth") || "").trim();
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

        const adMap: Record<string, boolean> = {};
        for (const ad of data.ad_accounts || []) {
          const id = String(ad.ad_account_id || "").trim();
          if (id) adMap[id] = true;
        }

        setSelectedIg(igMap);
        setSelectedAds(adMap);
        await loadConnections();
        setInfo("Autorizacao concluida. Revise os ativos do cliente ativo e finalize o vinculo.");
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
    const adAccountIds = Object.entries(selectedAds)
      .filter(([, checked]) => checked)
      .map(([id]) => id);

    setSaving(true);
    setErr(null);
    setInfo(null);

    try {
      await linkClientAssets({
        handoff: pendingAssets.handoff,
        instagram_ig_user_ids: instagramIds,
        ad_account_ids: adAccountIds,
      });
      setPendingAssets(null);
      setSelectedIg({});
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
            <button className="btn btnGold" type="button" disabled={oauthLoading} onClick={() => void onStartOAuth()}>
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
              <div className="p">Somente a integração Meta está habilitada para autorização nesta versão.</div>
            </div>
          </div>
          <div className="onboardingConnections">
            {[
              ["Instagram e Meta Ads", dashboardReady || paidConnections.length ? "Conectada" : "Não configurada", "Conectar com Facebook"],
              ["Google Ads e GA4", "Configuração necessária", "Conectar com Google"],
              ["Shopify", "Configuração necessária", "Conectar minha loja"],
              ["TikTok", "Em implantação", ""],
              ["Pinterest", "Em implantação", ""],
              ["FBits", "Opcional", ""],
            ].map(([name, status, action]) => (
              <div className="onboardingConnBlock" key={name}>
                <div className="h1">{name}</div>
                <div className="pill pillSoft" style={{ marginTop: 10 }}>{status}</div>
                {action ? (
                  <button
                    className="btn btnGhost"
                    type="button"
                    style={{ marginTop: 12 }}
                    disabled={name !== "Instagram e Meta Ads" || oauthLoading}
                    onClick={name === "Instagram e Meta Ads" ? () => void onStartOAuth() : undefined}
                  >
                    {action}
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </section>

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
