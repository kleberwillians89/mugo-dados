import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import {
  disableLocalAuth,
  getSupabaseBootstrapError,
  isLocalAuthEnabled,
  supabase,
} from "./app/supabase";
import { getMyPendingInvitations, listClients, openPlatformCompany, setApiAccessToken, type ClientMembership, type PendingInvitation, type PlatformCompany } from "./app/api";
import {
  getCurrentAppRoute,
  getPublicAppRouteFromPath,
  navigateToAppRoute,
  type AppRoute,
} from "./app/routes";
import { routeAfterInvitationAccepted, shouldOpenMetaAfterSignIn } from "./app/authNavigation";
import { canonicalizeClientId, clearTenantBrowserState, getActiveClient, MUGO_APP_NAME, setActiveClient } from "./app/activeClient";
import { setActiveConnectionId } from "./app/connectionState";
import AppNavigation, { type NavigationUser } from "./components/shell/AppNavigation";
import Login from "./pages/Login";
import DashboardErrorBoundary from "./components/dashboard/DashboardErrorBoundary";
import MugoLogo from "./components/MugoLogo";
import "./components/mugo-logo.css";
import { DashboardDataProvider } from "./app/DashboardDataContext";
import { DataDeletionPage, DataProtectionPage, PrivacyPage, TermsPage } from "./pages/LegalPages";

const loadOnboarding = () => import("./pages/Onboarding");
const loadDashboard = () => import("./pages/Dashboard");
const loadGoogleAnalytics = () => import("./pages/GoogleAnalytics");
const loadEcommerce = () => import("./pages/Ecommerce");
const Goals = lazy(() => import("./pages/Goals"));
const GoalsSummary = lazy(() => import("./components/GoalsSummary"));
const loadCustomers = () => import("./pages/Customers");
const loadCompanies = () => import("./pages/Companies");
const loadIntelligence = () => import("./pages/Intelligence");
const loadNotFound = () => import("./pages/NotFound");
const loadAcceptInvitation = () => import("./pages/AcceptInvitation");

const Onboarding = lazy(loadOnboarding);
const Dashboard = lazy(loadDashboard);
const GoogleAnalytics = lazy(loadGoogleAnalytics);
const Ecommerce = lazy(loadEcommerce);
const Customers = lazy(loadCustomers);
const Companies = lazy(loadCompanies);
const Intelligence = lazy(loadIntelligence);
const NotFound = lazy(loadNotFound);
const AcceptInvitation = lazy(loadAcceptInvitation);

type AppView = "loading" | "login" | "setup" | "dashboard" | "accept-invitation";

const AUTH_BOOTSTRAP_RETRY_MS = 350;
const AUTH_BOOTSTRAP_RETRY_ATTEMPTS = 3;
const AUTH_DEBUG = import.meta.env.DEV && import.meta.env.VITE_AUTH_DEBUG === "true";

function authDebug(event: string, payload?: Record<string, unknown>) {
  if (!AUTH_DEBUG) return;
  if (payload) {
    console.info(`[auth-debug] ${event}`, payload);
    return;
  }
  console.info(`[auth-debug] ${event}`);
}

function hasSupabaseCallbackSignalInUrl(): boolean {
  try {
    const search = new URLSearchParams(window.location.search);
    if (
      search.has("code") ||
      search.has("access_token") ||
      search.has("error") ||
      search.has("error_description")
    ) {
      return true;
    }

    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    return Boolean(
      hash.get("access_token") ||
      hash.get("refresh_token") ||
      hash.get("error") ||
      hash.get("error_description")
    );
  } catch {
    return false;
  }
}

function hasSetupSignalInUrl(): boolean {
  try {
    const search = new URLSearchParams(window.location.search);
    return (
      search.get("onboarding") === "1" ||
      search.has("meta_oauth") ||
      search.has("handoff")
    );
  } catch {
    return false;
  }
}

function clearSetupUrlParams() {
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

function toErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return "Erro ao carregar a configuração do Mugô Dados.";
}

// Antes da sessão/empresa existirem: só o produto e o estado.
function AppLoading() {
  return (
    <main className="appBootShell" aria-busy="true" aria-live="polite">
      <header className="appBootHeader">
        <MugoLogo variant="symbol" className="appBootMark" alt="" />
        <div><strong>{MUGO_APP_NAME}</strong></div>
      </header>
      <section className="appBootContent">
        <div className="appBootIntro">
          <span className="appBootSpinner" aria-hidden="true" />
          <p>Carregando…</p>
        </div>
      </section>
    </main>
  );
}

// Dentro do frame (sidebar já visível): carregamento da página, sem repetir a marca.
function PageLoading() {
  return (
    <div className="appPageLoading" role="status" aria-live="polite">
      <span className="appBootSpinner" aria-hidden="true" />
      Carregando…
    </div>
  );
}

// Perfil somente-leitura (cliente final) nunca acessa configuração de OAuth,
// reconexões nem detalhe técnico de integração — só quem gerencia a conta
// (agency_admin/client_admin/owner/admin) chega em "Integrações".
// Identidade exibida na área da conta: nome do perfil quando existir; senão a
// parte local do e-mail. Só leitura da sessão já carregada pelo Supabase.
function resolveNavigationUser(session: Session | null, localMode: boolean): NavigationUser | null {
  if (localMode) return { name: "Modo local", email: null };
  const user = session?.user;
  if (!user) return null;
  const metadata = (user.user_metadata || {}) as Record<string, unknown>;
  const fullName = String(metadata.full_name || metadata.name || "").trim();
  const email = String(user.email || "").trim();
  return { name: fullName || email.split("@")[0] || "Conta", email: email || null };
}

function isReadOnlyClientRole(role: string | null | undefined): boolean {
  const normalized = String(role || "").toLowerCase();
  return !["platform_admin", "agency_admin", "client_admin", "owner", "admin"].includes(normalized);
}

async function resolveTenantBootstrap(userId: string): Promise<{ platformAdmin: boolean; agencyAdmin: boolean; clients: ClientMembership[] }> {
  if (!supabase) return { platformAdmin: false, agencyAdmin: false, clients: [] };
  const [adminResult, membershipsResult] = await Promise.all([
    supabase.from("platform_admins").select("user_id").eq("user_id", userId).maybeSingle(),
    supabase.from("client_memberships").select("client_id,role").eq("user_id", userId),
  ]);
  if (membershipsResult.error) throw membershipsResult.error;
  const platformAdmin = Boolean(adminResult.data) && !adminResult.error;
  const membershipRows = membershipsResult.data || [];
  const agencyAdmin = membershipRows.some((row) => String(row.role || "") === "agency_admin");
  if (agencyAdmin && !platformAdmin) {
    const response = await listClients();
    return { platformAdmin, agencyAdmin, clients: response.clients || [] };
  }
  const ids = membershipRows.map((row) => String(row.client_id));
  const clientsResult = platformAdmin
    ? await supabase.from("clients").select("id,name,trade_name").order("name")
    : ids.length
      ? await supabase.from("clients").select("id,name,trade_name").in("id", ids)
      : { data: [], error: null };
  if (clientsResult.error) throw clientsResult.error;
  const clientRows = clientsResult.data || [];
  const nativeCanonicalIds = new Set(
    clientRows
      .map((row) => String(row.id))
      .filter((id) => canonicalizeClientId(id) === id)
  );
  const canonicalRows = clientRows.filter((row) => {
    const rawId = String(row.id);
    const canonicalId = canonicalizeClientId(rawId);
    return rawId === canonicalId || !nativeCanonicalIds.has(canonicalId);
  });
  const names = new Map(canonicalRows.map((row) => [canonicalizeClientId(String(row.id)), String(row.trade_name || row.name || row.id)]));
  const candidates = platformAdmin
    ? canonicalRows.map((row) => ({ client_id: canonicalizeClientId(String(row.id)), name: String(row.trade_name || row.name || row.id), role: "platform_admin" }))
    : membershipRows.map((row) => { const id = canonicalizeClientId(String(row.client_id)); return { client_id: id, name: names.get(id) || id, role: String(row.role || "viewer") }; });
  const clients = [...new Map(candidates.map((client) => [client.client_id, client])).values()];
  return { platformAdmin, agencyAdmin, clients };
}

function PrivateApp() {
  const authBootstrapError = getSupabaseBootstrapError();
  const [session, setSession] = useState<Session | null>(null);
  const [view, setView] = useState<AppView>("loading");
  const [route, setRoute] = useState<AppRoute>(() => getCurrentAppRoute());
  const [bootError, setBootError] = useState<string | null>(authBootstrapError);
  const [authInitializing, setAuthInitializing] = useState(true);
  const [localMode, setLocalMode] = useState(() => isLocalAuthEnabled());
  const [clients, setClients] = useState<ClientMembership[]>([]);
  const [platformAdmin, setPlatformAdmin] = useState(false);
  const [agencyAdmin, setAgencyAdmin] = useState(false);
  const [activeClientId, setActiveClientId] = useState("");
  const [tenantReady, setTenantReady] = useState(false);
  const [pendingInvitations, setPendingInvitations] = useState<PendingInvitation[]>([]);
  const [resolvedUserId, setResolvedUserId] = useState<string | null>(null);
  const authBootstrapCompletedRef = useRef(false);
  const knownSessionUserRef = useRef<string | null>(null);
  // Evita reabrir a tela de aceitação de convite depois que o usuário
  // escolheu "Pular por agora" na mesma sessão.
  const invitationPromptDismissedRef = useRef(false);
  // Tenant de destino logo após entrar pelo onboarding (link de ativação ou
  // aceitação explícita de invitation). Só é honrado quando a membership
  // correspondente aparece na lista já validada pelo backend — nunca confia
  // num client_id solto do frontend. Consumido uma única vez.
  const preferredClientIdRef = useRef<string | null>(null);

  useEffect(() => {
    setApiAccessToken(localMode ? null : session?.access_token ?? null);
  }, [localMode, session]);

  const resolveAuthenticatedView = useCallback(
    async (candidateSession?: Session | null, requestedRoute: AppRoute = route) => {
      const activeSession = candidateSession ?? session;
      if (!activeSession && !localMode) {
        authDebug("route.decision", {
          target: "login",
          reason: "missing_session",
        });
        setView("login");
        return;
      }

      // O retorno de OAuth chega em "/?onboarding=1&meta_oauth=…&handoff=…".
      // Normalizar para /meta descartaria a query antes de o Onboarding
      // consumir o handoff, então o sinal de setup tem precedência.
      if (
        requestedRoute === "meta" &&
        window.location.pathname !== "/meta" &&
        !hasSetupSignalInUrl()
      ) {
        navigateToAppRoute("meta", { replace: true });
      }

      const sameAuthenticatedContext =
        Boolean(activeSession?.user.id) && resolvedUserId === activeSession?.user.id;
      if (sameAuthenticatedContext) {
        if (pendingInvitations.length > 0 && !invitationPromptDismissedRef.current) {
          setView("accept-invitation");
          return;
        }
        if (requestedRoute === "companies" && !platformAdmin && !agencyAdmin) {
          setBootError("Você não tem permissão para acessar a administração de empresas.");
          navigateToAppRoute("meta", { replace: true });
          setRoute("meta");
        }
        const wantsSetupView = requestedRoute === "integrations" || hasSetupSignalInUrl();
        if (wantsSetupView && isReadOnlyClientRole(getActiveClient()?.role)) {
          navigateToAppRoute("meta", { replace: true });
          setRoute("meta");
          setView("dashboard");
          return;
        }
        setView(wantsSetupView ? "setup" : "dashboard");
        return;
      }

      setView("loading");
      setBootError(null);
      setTenantReady(false);

      if (!localMode) {
        const bootstrap = await resolveTenantBootstrap(activeSession?.user.id || "");
        setPlatformAdmin(bootstrap.platformAdmin);
        setAgencyAdmin(bootstrap.agencyAdmin);
        if (requestedRoute === "companies" && !bootstrap.platformAdmin && !bootstrap.agencyAdmin) {
          setBootError("Você não tem permissão para acessar a administração de empresas.");
          navigateToAppRoute("meta", { replace: true });
          setRoute("meta");
          requestedRoute = "meta";
        }
        const availableClients = bootstrap.clients;
        setClients(availableClients);
        setResolvedUserId(activeSession?.user.id || null);

        // Usuário JÁ existente que entrou por um link de ativação: aceita
        // EXPLICITAMENTE o convite (a membership é derivada da invitation no
        // backend — nunca de client_id do frontend). Só verifica num retorno
        // de autenticação ou quando ainda não há nenhuma empresa vinculada,
        // para não incomodar o retorno normal.
        let pending: PendingInvitation[] = [];
        const shouldCheckInvitations =
          !invitationPromptDismissedRef.current &&
          (hasSupabaseCallbackSignalInUrl() || availableClients.length === 0);
        if (shouldCheckInvitations) {
          try {
            const response = await getMyPendingInvitations();
            const memberIds = new Set(availableClients.map((client) => client.client_id));
            pending = (response.invitations || []).filter(
              (invitation) => !memberIds.has(canonicalizeClientId(invitation.client_id))
            );
          } catch {
            pending = [];
          }
        }
        setPendingInvitations(pending);

        const stored = getActiveClient();
        // O tenant recém-entrado pelo onboarding vence o activeClient antigo,
        // mas só se a membership realmente existe na lista validada pelo
        // backend. Caso contrário, o comportamento anterior é preservado.
        const preferredClientId = preferredClientIdRef.current
          ? canonicalizeClientId(preferredClientIdRef.current)
          : "";
        const preferredClient = preferredClientId
          ? availableClients.find((client) => client.client_id === preferredClientId)
          : undefined;
        if (preferredClient) preferredClientIdRef.current = null;
        const selected =
          preferredClient ||
          availableClients.find((client) => client.client_id === stored?.id) ||
          availableClients[0];
        if (selected) {
          setActiveClient({
            id: selected.client_id,
            name: selected.name,
            role: selected.role,
          });
          setActiveClientId(selected.client_id);
          setTenantReady(true);
        }

        if (pending.length > 0) {
          setView("accept-invitation");
          return;
        }

        if (!selected) {
          if (bootstrap.platformAdmin) {
            setActiveClientId("");
            setView("dashboard");
            return;
          }
          setBootError("Sua conta ainda não está vinculada a nenhuma empresa.");
          setView("dashboard");
          return;
        }
      }

      // Novo usuário que chegou por um link de onboarding: o backend gravou
      // invitation_id nos metadados do Supabase ao emitir o link e o trigger
      // já criou a membership. Cai direto nas Integrações da empresa, sem
      // depender do activeClient anterior. Login normal (sem invitation_id nos
      // metadados) nunca entra aqui — Cenário C segue para o dashboard. viewer
      // é barrado pela guarda de rota logo abaixo.
      const linkInvitationId = String(
        (activeSession?.user?.user_metadata as Record<string, unknown> | undefined)?.invitation_id || ""
      ).trim();
      if (
        !localMode &&
        requestedRoute !== "integrations" &&
        linkInvitationId &&
        hasSupabaseCallbackSignalInUrl() &&
        !isReadOnlyClientRole(getActiveClient()?.role)
      ) {
        navigateToAppRoute("integrations", { replace: true });
        setRoute("integrations");
        requestedRoute = "integrations";
      }

      if (requestedRoute === "not_found") {
        setView("dashboard");
        return;
      }

      if (requestedRoute === "companies") {
        setView("dashboard");
        return;
      }

      if (requestedRoute === "integrations") {
        if (isReadOnlyClientRole(getActiveClient()?.role)) {
          navigateToAppRoute("meta", { replace: true });
          setRoute("meta");
          setView("dashboard");
          return;
        }
        setView("setup");
        return;
      }

      if (requestedRoute === "google") {
        authDebug("route.decision", {
          target: requestedRoute,
          reason: `authenticated_${requestedRoute}_report`,
        });
        setView("dashboard");
        return;
      }

      if (hasSetupSignalInUrl()) {
        if (isReadOnlyClientRole(getActiveClient()?.role)) {
          navigateToAppRoute("meta", { replace: true });
          setRoute("meta");
          setView("dashboard");
          return;
        }
        setView("setup");
        return;
      }
      // O shell autenticado não espera integrações nem relatórios. Cada página
      // carrega seus dados progressivamente e mantém seu último estado válido.
      setView("dashboard");
    },
    [agencyAdmin, localMode, pendingInvitations, platformAdmin, resolvedUserId, route, session]
  );

  useEffect(() => {
    let mounted = true;
    const authClient = supabase;

    const bootstrapAuth = async () => {
      const callbackSignal = hasSupabaseCallbackSignalInUrl();
      authDebug("bootstrap.start", { callbackSignalInUrl: callbackSignal });

      if (localMode) {
        if (!mounted) return;
        const localClientId = getActiveClient()?.id || "";
        setActiveClientId(localClientId);
        setTenantReady(Boolean(localClientId));
        setSession(null);
        setBootError(null);
        setView("dashboard");
        setAuthInitializing(false);
        return;
      }

      if (!authClient || authBootstrapError) {
        authDebug("bootstrap.config_error", {
          message: authBootstrapError || "supabase_client_unavailable",
        });
        if (!mounted) return;
        setSession(null);
        setBootError(authBootstrapError || "Supabase Auth nao esta configurado no frontend.");
        setView("login");
        setAuthInitializing(false);
        return;
      }

      try {
        const first = await authClient.auth.getSession();
        if (first.error) {
          authDebug("getSession.error", { message: first.error.message });
        }

        let nextSession = first.data.session ?? null;
        authDebug("getSession.result", {
          hasSession: !!nextSession,
          userId: nextSession?.user?.id ?? null,
        });

        if (!nextSession && callbackSignal) {
          for (let attempt = 1; attempt <= AUTH_BOOTSTRAP_RETRY_ATTEMPTS; attempt += 1) {
            await new Promise<void>((resolve) => {
              window.setTimeout(resolve, AUTH_BOOTSTRAP_RETRY_MS);
            });

            const retry = await authClient.auth.getSession();
            if (retry.error) {
              authDebug("getSession.retry.error", {
                attempt,
                message: retry.error.message,
              });
            }
            nextSession = retry.data.session ?? null;
            authDebug("getSession.retry.result", {
              attempt,
              hasSession: !!nextSession,
              userId: nextSession?.user?.id ?? null,
            });
            if (nextSession) break;
          }
        }

        if (!mounted) return;
        knownSessionUserRef.current = nextSession?.user.id ?? null;
        setSession(nextSession);
      } catch (error: unknown) {
        if (!mounted) return;
        authDebug("getSession.exception", { message: toErrorMessage(error) });
        setSession(null);
      } finally {
        if (mounted) {
          authBootstrapCompletedRef.current = true;
          setAuthInitializing(false);
        }
      }
    };

    void bootstrapAuth();

    if (!authClient || authBootstrapError) {
      return () => {
        mounted = false;
      };
    }

    const { data: sub } = authClient.auth.onAuthStateChange((event, next) => {
      if (!mounted) return;
      const nextSession = next ?? null;
      const nextUserId = nextSession?.user.id ?? null;
      const openMeta = shouldOpenMetaAfterSignIn({
        event,
        bootstrapCompleted: authBootstrapCompletedRef.current,
        knownUserId: knownSessionUserRef.current,
        nextUserId,
      });
      authDebug("onAuthStateChange", {
        event,
        hasSession: !!nextSession,
        userId: nextSession?.user?.id ?? null,
      });
      setSession(nextSession);
      setAuthInitializing(false);
      knownSessionUserRef.current = nextUserId;
      if (openMeta) {
        navigateToAppRoute("meta", { replace: true });
        setRoute("meta");
      }
      if (!nextSession) {
        clearTenantBrowserState();
      setClients([]);
      setActiveClientId("");
      setTenantReady(false);
        setPendingInvitations([]);
        invitationPromptDismissedRef.current = false;
        setResolvedUserId(null);
        clearSetupUrlParams();
        setBootError(null);
        setView("login");
      }
    });

    return () => {
      mounted = false;
      sub.subscription.unsubscribe();
    };
  }, [authBootstrapError, localMode]);

  useEffect(() => {
    const handlePopState = () => {
      setRoute(getCurrentAppRoute());
    };

    window.addEventListener("popstate", handlePopState);
    return () => {
      window.removeEventListener("popstate", handlePopState);
    };
  }, []);

  useEffect(() => {
    if (authInitializing) {
      setView("loading");
      return;
    }
    if (localMode) {
      setView("dashboard");
      return;
    }
    if (!session) {
      setView("login");
      return;
    }
    void resolveAuthenticatedView(session, route);
  }, [authInitializing, localMode, resolveAuthenticatedView, route, session]);

  useEffect(() => {
    if (view !== "dashboard" || (!session && !localMode)) return;
    const preload = () => {
      void Promise.allSettled([
        loadDashboard(),
        loadGoogleAnalytics(),
        loadOnboarding(),
        loadNotFound(),
        loadIntelligence(),
        ...(platformAdmin ? [loadCompanies()] : []),
      ]);
    };
    const idleWindow = window as Window & {
      requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
      cancelIdleCallback?: (handle: number) => void;
    };
    if (idleWindow.requestIdleCallback) {
      const handle = idleWindow.requestIdleCallback(preload, { timeout: 2500 });
      return () => idleWindow.cancelIdleCallback?.(handle);
    }
    const handle = window.setTimeout(preload, 1200);
    return () => window.clearTimeout(handle);
  }, [localMode, platformAdmin, session, view]);

  const openRoute = useCallback(
    (nextRoute: AppRoute) => {
      navigateToAppRoute(nextRoute);
      setRoute(nextRoute);
    },
    []
  );

  async function handleLogout() {
    clearTenantBrowserState();
    setActiveConnectionId(null);
    setResolvedUserId(null);
    setPendingInvitations([]);
    invitationPromptDismissedRef.current = false;
    if (localMode) {
      disableLocalAuth();
      setLocalMode(false);
      clearSetupUrlParams();
      setSession(null);
      setBootError(null);
      setAuthInitializing(false);
      setView("login");
      return;
    }
    if (!supabase) {
      authDebug("logout", { cleared: true, mode: "no_supabase_client" });
      clearSetupUrlParams();
      setSession(null);
      setBootError(authBootstrapError);
      setAuthInitializing(false);
      setView("login");
      return;
    }
    try {
      await supabase.auth.signOut();
    } finally {
      authDebug("logout", { cleared: true });
      clearSetupUrlParams();
      setSession(null);
      setBootError(null);
      setAuthInitializing(false);
      setView("login");
    }
  }

  const handleSetupCompleted = useCallback(async () => {
    clearSetupUrlParams();
    openRoute("meta");
    setView("dashboard");
  }, [openRoute]);

  const handleInvitationsAccepted = useCallback(
    async (accepted?: { clientId: string | null; role: string | null }) => {
      // Reprocessa o bootstrap para trazer a nova membership ao seletor de
      // empresas. O tenant e o papel de destino vêm da invitation aceita e
      // validada pelo backend (RPC accept_user_invitation) — nunca do
      // activeClient antigo do localStorage. Quem gerencia integrações cai
      // direto nas Integrações; viewer segue para o dashboard (guard de rota).
      preferredClientIdRef.current = accepted?.clientId ?? null;
      setPendingInvitations([]);
      clearSetupUrlParams();
      setResolvedUserId(null);
      setView("loading");
      openRoute(routeAfterInvitationAccepted(accepted?.role ?? null));
    },
    [openRoute]
  );

  const handleSkipInvitations = useCallback(() => {
    invitationPromptDismissedRef.current = true;
    setPendingInvitations([]);
    clearSetupUrlParams();
    setResolvedUserId(null);
    setView("loading");
    void resolveAuthenticatedView(session, route);
  }, [resolveAuthenticatedView, route, session]);

  const handlePasswordLoginSuccess = useCallback(
    async (nextSession: Session | null) => {
      setSession(nextSession);
      await resolveAuthenticatedView(nextSession ?? session, route);
    },
    [resolveAuthenticatedView, route, session]
  );

  const handleLocalLogin = useCallback(() => {
    const localClientId = getActiveClient()?.id || "";
    setLocalMode(true);
    setBootError(null);
    setSession(null);
    setAuthInitializing(false);
    setActiveClientId(localClientId);
    setTenantReady(Boolean(localClientId));
    setView("dashboard");
  }, []);

  const handleClientChange = useCallback((clientId: string) => {
    const canonicalId = canonicalizeClientId(clientId);
    const client = clients.find((item) => item.client_id === canonicalId);
    if (!client) return;
    setTenantReady(false);
    clearTenantBrowserState();
    setActiveClient({ id: client.client_id, name: client.name, role: client.role });
    setActiveConnectionId(null);
    setActiveClientId(client.client_id);
    setTenantReady(true);
  }, [clients]);

  const handleOpenCompany = useCallback(async (company: PlatformCompany, targetRoute: AppRoute = "meta") => {
    // Mantém o mecanismo de acesso/suporte auditado (openPlatformCompany) antes
    // de trocar de tenant — "Fazer onboarding" e "Abrir para suporte" só se
    // diferenciam pela rota de destino.
    const canonicalId = canonicalizeClientId(company.id);
    const companyName = company.trade_name || company.name;
    await openPlatformCompany(canonicalId);
    setTenantReady(false);
    clearTenantBrowserState();
    // Empresa recém-criada ainda não está na lista carregada no bootstrap:
    // entra no seletor já, sem esperar F5. Nenhuma membership é criada — o
    // acesso continua vindo do papel de plataforma validado no backend.
    setClients((current) =>
      current.some((client) => client.client_id === canonicalId)
        ? current
        : [...current, { client_id: canonicalId, name: companyName, role: "platform_admin" }]
    );
    setActiveClient({ id: canonicalId, name: companyName, role: "platform_admin" });
    setActiveConnectionId(null);
    setActiveClientId(canonicalId);
    setTenantReady(true);
    openRoute(targetRoute);
  }, [openRoute]);

  const activeClientRole = String(
    clients.find((client) => client.client_id === activeClientId)?.role
      || getActiveClient()?.role
      || ""
  ).toLowerCase();
  const canManageIntegrations =
    platformAdmin
    || agencyAdmin
    || ["client_admin", "owner", "admin"].includes(activeClientRole);
  const navigationUser = resolveNavigationUser(session, localMode);

  if (view === "loading") {
    return <AppLoading />;
  }

  if (view === "login" || (!session && !localMode)) {
    return (
      <Login
        initialError={bootError}
        authChecking={authInitializing}
        onPasswordLoginSuccess={handlePasswordLoginSuccess}
        onLocalLogin={handleLocalLogin}
      />
    );
  }

  if (view === "accept-invitation") {
    return (
      <Suspense fallback={<AppLoading />}>
        <AcceptInvitation
          invitations={pendingInvitations}
          onAccepted={handleInvitationsAccepted}
          onSkip={handleSkipInvitations}
          onLogout={handleLogout}
        />
      </Suspense>
    );
  }

  if (view === "setup") {
    return (
      <div className="appFrame">
        <AppNavigation
          route="integrations"
          platformAdmin={platformAdmin}
          agencyAdmin={agencyAdmin}
          canManageIntegrations={canManageIntegrations}
          onOpen={openRoute}
          clients={clients}
          activeClientId={activeClientId}
          onClientChange={handleClientChange}
          onLogout={handleLogout}
          user={navigationUser}
        />
        <div className="appFrameMain">
          <Suspense fallback={<PageLoading />}>
            <Onboarding
              isAuthenticated={!!session}
              initialError={bootError}
              onLogout={handleLogout}
              onCompleted={handleSetupCompleted}
            />
          </Suspense>
        </div>
      </div>
    );
  }

  return (
    <DashboardErrorBoundary>
      <DashboardDataProvider clientId={activeClientId} tenantReady={tenantReady || localMode} enabled={!!activeClientId && (!!session || localMode)}>
      <div className="appFrame">
      <AppNavigation
        route={route}
        platformAdmin={platformAdmin}
        agencyAdmin={agencyAdmin}
        canManageIntegrations={canManageIntegrations}
        onOpen={openRoute}
        clients={clients}
        activeClientId={activeClientId}
        onClientChange={handleClientChange}
        onLogout={handleLogout}
        user={navigationUser}
      />
      <div className="appFrameMain">
      <Suspense fallback={<PageLoading />}>
      {route === "not_found" ? (
        <NotFound onGoHome={() => openRoute("meta")} />
      ) : route === "companies" && (platformAdmin || agencyAdmin) ? (
        <Companies
          onLogout={handleLogout}
          onOpenCompany={(company, targetRoute) => void handleOpenCompany(company, targetRoute)}
          onOpenDashboard={() => openRoute("meta")}
          canCreateCompany={platformAdmin}
          canDeleteCompany={platformAdmin}
          canEditBusinessContext={canManageIntegrations}
        />
      ) : (
      <>
      {route === "goals" ? (
        <Goals key={`goals:${activeClientId}`} canManage={platformAdmin || agencyAdmin || ["client_admin", "owner", "admin"].includes(activeClientRole)} />
      ) : route === "intelligence" ? (
        <Intelligence
          key={`intelligence:${activeClientId}`}
          onLogout={handleLogout}
          canEditBusinessContext={canManageIntegrations}
        />
      ) : route === "google" ? (
        <GoogleAnalytics
          key={`google:${activeClientId}`}
          isAuthenticated={!!session || localMode}
          canSync={canManageIntegrations}
          onLogout={handleLogout}
          onOpenDashboard={() => openRoute("meta")}
        />
      ) : route === "customers" ? (
        <Customers key={`customers:${activeClientId}`} />
      ) : route === "ecommerce" ? (
        <Ecommerce
          key={`ecommerce:${activeClientId}`}
          isAuthenticated={!!session || localMode}
          canSync={canManageIntegrations}
          onLogout={handleLogout}
          onOpenDashboard={() => openRoute("meta")}
          onOpenGoogleReport={() => openRoute("google")}
          onOpenIntegrations={canManageIntegrations ? () => openRoute("integrations") : undefined}
        />
      ) : (
        <>
        <Dashboard
          key={`dashboard:${activeClientId}`}
          onLogout={handleLogout}
          isAuthenticated={!!session || localMode}
          canSync={canManageIntegrations}
          bootstrapError={bootError}
          onOpenSetup={canManageIntegrations ? () => setView("setup") : undefined}
          onOpenGoogleAnalytics={() => openRoute("google")}
        />
        <GoalsSummary key={`goals-summary:${activeClientId}`} onOpen={() => openRoute("goals")} />
        </>
      )}
      </>
      )}
      </Suspense>
      </div>
      </div>
      </DashboardDataProvider>
    </DashboardErrorBoundary>
  );
}

export default function App() {
  const publicRoute = getPublicAppRouteFromPath(window.location.pathname);
  if (publicRoute === "privacy") return <PrivacyPage />;
  if (publicRoute === "data_deletion") return <DataDeletionPage />;
  if (publicRoute === "data_protection") return <DataProtectionPage />;
  if (publicRoute === "terms") return <TermsPage />;
  return <PrivateApp />;
}
