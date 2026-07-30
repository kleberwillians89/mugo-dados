import { useCallback, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import {
  disableLocalAuth,
  getSupabaseBootstrapError,
  isLocalAuthEnabled,
  supabase,
} from "./app/supabase";
import { listClients, listClientConnections, type ClientMembership } from "./app/api";
import {
  getCurrentAppRoute,
  navigateToAppRoute,
  type AppRoute,
} from "./app/routes";
import { clearActiveClient, getActiveClient, MUGO_APP_NAME, setActiveClient } from "./app/activeClient";
import { setActiveConnectionId } from "./app/connectionState";
import ClientSwitcher from "./components/ClientSwitcher";
import Login from "./pages/Login";
import Onboarding from "./pages/Onboarding";
import Dashboard from "./pages/Dashboard";
import GoogleAnalytics from "./pages/GoogleAnalytics";
import DashboardErrorBoundary from "./components/dashboard/DashboardErrorBoundary";

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
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background:
          "radial-gradient(900px 360px at 12% -10%, rgba(215,219,106,.24), transparent 62%), #f2f0ec",
      }}
    >
      <span className="pill">Carregando {MUGO_APP_NAME}...</span>
    </div>
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
  const [activeClientId, setActiveClientId] = useState(() => getActiveClient()?.id || "");

  const isOrganicConnection = useCallback(
    (connection: { platform?: string | null; connection_type?: string | null; status?: string | null }) => {
      const platform = String(connection.platform || "").toLowerCase();
      const connectionType = String(connection.connection_type || "").toLowerCase();
      const status = String(connection.status || "").toLowerCase();
      return status === "active" && (platform === "instagram" || connectionType === "organic");
    },
    []
  );

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

      setView("loading");
      setBootError(null);

      if (!localMode) {
        const clientsResponse = await listClients();
        const availableClients = clientsResponse.clients || [];
        setClients(availableClients);
        const stored = getActiveClient();
        const selected =
          availableClients.find((client) => client.client_id === stored?.id) ||
          availableClients[0];
        if (!selected) {
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

      if (requestedRoute === "google") {
        authDebug("route.decision", {
          target: requestedRoute,
          reason: `authenticated_${requestedRoute}_report`,
        });
        setView("dashboard");
        return;
      }

      try {
        const setupRequestedFromUrl = hasSetupSignalInUrl();
        const connectionsRes = await listClientConnections();
        const connections = connectionsRes.connections || [];
        const hasActiveOrganicConnection = connections.some(isOrganicConnection);

        if (setupRequestedFromUrl) {
          authDebug("route.decision", {
            target: "setup",
            reason: "setup_signal_in_url",
            connectionsCount: connections.length,
          });
          setView("setup");
          return;
        }

        if (!hasActiveOrganicConnection) {
          authDebug("route.decision", {
            target: "dashboard",
            reason: "authenticated_without_active_client_connection",
            connectionsCount: connections.length,
          });
          setView("dashboard");
          return;
        }

        authDebug("route.decision", {
          target: "dashboard",
            reason: "authenticated_with_active_client_connection",
          connectionsCount: connections.length,
        });
        setView("dashboard");
      } catch (error: unknown) {
        const message = toErrorMessage(error);
        authDebug("route.decision", {
          target: "dashboard",
          reason: "resolve_authenticated_view_error",
          error: message,
        });
        setBootError(message);
        setView("dashboard");
      }
    },
    [isOrganicConnection, localMode, route, session]
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

  const openRoute = useCallback(
    (nextRoute: AppRoute) => {
      navigateToAppRoute(nextRoute);
      setRoute(nextRoute);
    },
    []
  );

  async function handleLogout() {
    clearActiveClient();
    setActiveConnectionId(null);
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
    setActiveClient({ id: client.client_id, name: client.name, role: client.role });
    setActiveConnectionId(null);
    setActiveClientId(client.client_id);
    window.location.reload();
  }, [clients]);

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
      <ClientSwitcher
        clients={clients}
        activeClientId={activeClientId}
        onChange={handleClientChange}
      />
      {route === "google" ? (
        <GoogleAnalytics
          isAuthenticated={!!session || localMode}
          onLogout={handleLogout}
          onOpenDashboard={() => openRoute("dashboard")}
        />
      ) : (
        <Dashboard
          onLogout={handleLogout}
          isAuthenticated={!!session || localMode}
          bootstrapError={bootError}
          onOpenSetup={() => setView("setup")}
          onOpenGoogleAnalytics={() => openRoute("google")}
        />
      )}
    </DashboardErrorBoundary>
  );
}
