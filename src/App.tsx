import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import {
  disableLocalAuth,
  getSupabaseBootstrapError,
  isLocalAuthEnabled,
  supabase,
} from "./app/supabase";
import { getPlatformProfile, listClients, listPlatformCompanies, openPlatformCompany, type ClientMembership, type PlatformCompany } from "./app/api";
import {
  getCurrentAppRoute,
  navigateToAppRoute,
  type AppRoute,
} from "./app/routes";
import { clearTenantBrowserState, getActiveClient, MUGO_APP_NAME, setActiveClient } from "./app/activeClient";
import { setActiveConnectionId } from "./app/connectionState";
import ClientSwitcher from "./components/ClientSwitcher";
import Login from "./pages/Login";
import DashboardErrorBoundary from "./components/dashboard/DashboardErrorBoundary";

const loadOnboarding = () => import("./pages/Onboarding");
const loadDashboard = () => import("./pages/Dashboard");
const loadGoogleAnalytics = () => import("./pages/GoogleAnalytics");
const loadCompanies = () => import("./pages/Companies");
const loadNotFound = () => import("./pages/NotFound");

const Onboarding = lazy(loadOnboarding);
const Dashboard = lazy(loadDashboard);
const GoogleAnalytics = lazy(loadGoogleAnalytics);
const Companies = lazy(loadCompanies);
const NotFound = lazy(loadNotFound);

type AppView = "loading" | "login" | "setup" | "dashboard";

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

function AppLoading() {
  return (
    <main className="appBootShell" aria-busy="true" aria-live="polite">
      <header className="appBootHeader">
        <span className="appBootMark" aria-hidden="true">M</span>
        <div><strong>{MUGO_APP_NAME}</strong><small>Preparando seu workspace</small></div>
      </header>
      <section className="appBootContent">
        <div className="appBootIntro">
          <span className="appBootSpinner" aria-hidden="true" />
          <div><h1>Visão geral</h1><p>Validando sessão e empresa ativa…</p></div>
        </div>
        <div className="appBootGrid" aria-hidden="true">
          <span /><span /><span /><span />
        </div>
      </section>
    </main>
  );
}

export default function App() {
  const authBootstrapError = getSupabaseBootstrapError();
  const [session, setSession] = useState<Session | null>(null);
  const [view, setView] = useState<AppView>("loading");
  const [route, setRoute] = useState<AppRoute>(() => getCurrentAppRoute());
  const [bootError, setBootError] = useState<string | null>(authBootstrapError);
  const [authInitializing, setAuthInitializing] = useState(true);
  const [localMode, setLocalMode] = useState(() => isLocalAuthEnabled());
  const [clients, setClients] = useState<ClientMembership[]>([]);
  const [platformAdmin, setPlatformAdmin] = useState(false);
  const [activeClientId, setActiveClientId] = useState(() => getActiveClient()?.id || "");
  const [resolvedUserId, setResolvedUserId] = useState<string | null>(null);

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

      const sameAuthenticatedContext =
        Boolean(activeSession?.user.id) && resolvedUserId === activeSession?.user.id;
      if (sameAuthenticatedContext) {
        if (requestedRoute === "companies" && !platformAdmin) {
          setBootError("Você não tem permissão para acessar a administração de empresas.");
          navigateToAppRoute("dashboard", { replace: true });
          setRoute("dashboard");
        }
        setView(hasSetupSignalInUrl() ? "setup" : "dashboard");
        return;
      }

      setView("loading");
      setBootError(null);

      if (!localMode) {
        const profile = await getPlatformProfile();
        setPlatformAdmin(profile.is_platform_admin);
        if (requestedRoute === "companies" && !profile.is_platform_admin) {
          setBootError("Você não tem permissão para acessar a administração de empresas.");
          navigateToAppRoute("dashboard", { replace: true });
          setRoute("dashboard");
          requestedRoute = "dashboard";
        }
        const availableClients = profile.is_platform_admin
          ? (await listPlatformCompanies()).companies.map((company) => ({
              client_id: company.id, name: company.trade_name || company.name, role: "platform_admin",
            }))
          : (await listClients()).clients || [];
        setClients(availableClients);
        setResolvedUserId(activeSession?.user.id || null);
        const stored = getActiveClient();
        if (profile.is_platform_admin && !stored && requestedRoute === "dashboard") {
          navigateToAppRoute("companies", { replace: true });
          setRoute("companies");
          setView("dashboard");
          return;
        }
        const selected =
          availableClients.find((client) => client.client_id === stored?.id) ||
          availableClients[0];
        if (!selected) {
          if (profile.is_platform_admin) {
            setActiveClientId("");
            setView("dashboard");
            return;
          }
          setBootError("Sua conta ainda não está vinculada a nenhuma empresa.");
          setView("dashboard");
          return;
        }
        setActiveClient({
          id: selected.client_id,
          name: selected.name,
          role: selected.role,
        });
        setActiveClientId(selected.client_id);
      }

      if (requestedRoute === "not_found") {
        setView("dashboard");
        return;
      }

      if (requestedRoute === "companies") {
        setView("dashboard");
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
        setView("setup");
        return;
      }
      // O shell autenticado não espera integrações nem relatórios. Cada página
      // carrega seus dados progressivamente e mantém seu último estado válido.
      setView("dashboard");
    },
    [localMode, platformAdmin, resolvedUserId, route, session]
  );

  useEffect(() => {
    let mounted = true;
    const authClient = supabase;

    const bootstrapAuth = async () => {
      const callbackSignal = hasSupabaseCallbackSignalInUrl();
      authDebug("bootstrap.start", { callbackSignalInUrl: callbackSignal });

      if (localMode) {
        if (!mounted) return;
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
        setSession(nextSession);
      } catch (error: unknown) {
        if (!mounted) return;
        authDebug("getSession.exception", { message: toErrorMessage(error) });
        setSession(null);
      } finally {
        if (mounted) {
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
      authDebug("onAuthStateChange", {
        event,
        hasSession: !!nextSession,
        userId: nextSession?.user?.id ?? null,
      });
      setSession(nextSession);
      setAuthInitializing(false);
      if (!nextSession) {
        clearTenantBrowserState();
        setClients([]);
        setActiveClientId("");
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
    await resolveAuthenticatedView(session, route);
  }, [resolveAuthenticatedView, route, session]);

  const handlePasswordLoginSuccess = useCallback(
    async (nextSession: Session | null) => {
      setSession(nextSession);
      await resolveAuthenticatedView(nextSession ?? session, route);
    },
    [resolveAuthenticatedView, route, session]
  );

  const handleLocalLogin = useCallback(() => {
    setLocalMode(true);
    setBootError(null);
    setSession(null);
    setAuthInitializing(false);
    setView("dashboard");
  }, []);

  const handleClientChange = useCallback((clientId: string) => {
    const client = clients.find((item) => item.client_id === clientId);
    if (!client) return;
    clearTenantBrowserState();
    setActiveClient({ id: client.client_id, name: client.name, role: client.role });
    setActiveConnectionId(null);
    setActiveClientId(client.client_id);
  }, [clients]);

  const handleOpenCompany = useCallback(async (company: PlatformCompany) => {
    await openPlatformCompany(company.id);
    clearTenantBrowserState();
    setActiveClient({ id: company.id, name: company.trade_name || company.name, role: "platform_admin" });
    setActiveConnectionId(null);
    setActiveClientId(company.id);
    openRoute("dashboard");
  }, [openRoute]);

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

  if (view === "setup") {
    return (
      <Onboarding
        isAuthenticated={!!session}
        initialError={bootError}
        onLogout={handleLogout}
        onCompleted={handleSetupCompleted}
      />
    );
  }

  return (
    <DashboardErrorBoundary>
      <Suspense fallback={<AppLoading />}>
      {route === "not_found" ? (
        <NotFound onGoHome={() => openRoute("dashboard")} />
      ) : route === "companies" && platformAdmin ? (
        <Companies
          onLogout={handleLogout}
          onOpenCompany={(company) => void handleOpenCompany(company)}
          onOpenDashboard={() => openRoute("dashboard")}
        />
      ) : (
      <>
      {platformAdmin && (
        <button className="btn" style={{position:"fixed",right:18,top:18,zIndex:100}} onClick={() => openRoute("companies")}>
          Empresas
        </button>
      )}
      <ClientSwitcher
        clients={clients}
        activeClientId={activeClientId}
        onChange={handleClientChange}
      />
      {route === "google" ? (
        <GoogleAnalytics
          key={`google:${activeClientId}`}
          isAuthenticated={!!session || localMode}
          onLogout={handleLogout}
          onOpenDashboard={() => openRoute("dashboard")}
        />
      ) : (
        <Dashboard
          key={`dashboard:${activeClientId}`}
          onLogout={handleLogout}
          isAuthenticated={!!session || localMode}
          bootstrapError={bootError}
          onOpenSetup={() => setView("setup")}
          onOpenGoogleAnalytics={() => openRoute("google")}
        />
      )}
      </>
      )}
      </Suspense>
    </DashboardErrorBoundary>
  );
}
