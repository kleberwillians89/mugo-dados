import type { ReactNode } from "react";
// HARNESS DE REVISÃO VISUAL — somente desenvolvimento (fora do build).
// Monta o frame real (AppNavigation + páginas reais) com um perfil simulado.

import { useState } from "react";
import { setActiveClient } from "../app/activeClient";
import { DashboardDataContext, DashboardDataProvider, type DashboardDataValue } from "../app/DashboardDataContext";
import type { AppRoute } from "../app/routes";
import DataNotice from "../components/data/DataNotice";
import PageHeader from "../components/data/PageHeader";
import Shell from "../components/Shell";
import AppNavigation from "../components/shell/AppNavigation";
import Dashboard from "../pages/Dashboard";
import Ecommerce from "../pages/Ecommerce";
import GoogleAnalytics from "../pages/GoogleAnalytics";
import Onboarding from "../pages/Onboarding";
import { REVIEW_PROFILES, type ReviewChannelScenario, type ReviewCompany, type ReviewProfile } from "./fixtures";

const ROUTE_TITLE: Record<AppRoute, string> = {
  ecommerce: "Ecommerce",
  meta: "Meta",
  google: "Google",
  intelligence: "Inteligência",
  integrations: "Integrações",
  companies: "Empresas",
  not_found: "Página não encontrada",
};

const ROUTE_TO_SCREEN: Partial<Record<AppRoute, string>> = {
  ecommerce: "ecommerce",
  integrations: "integracoes",
  meta: "meta",
  google: "google",
  intelligence: "inteligencia",
  companies: "empresas",
};

function ReviewPlaceholder({ route, company }: { route: AppRoute; company: string }) {
  return (
    <Shell variant="editorial" themeClass="theme-editorial" title={ROUTE_TITLE[route]}>
      <div className="ds-page">
        <PageHeader company={company} title={ROUTE_TITLE[route]} />
        <DataNotice title="Fora desta revisão">
          Esta página ainda não foi migrada para a nova linguagem e não faz parte do harness desta etapa.
          Use Ecommerce e Integrações para revisar o shell com conteúdo.
        </DataNotice>
      </div>
    </Shell>
  );
}

type Props = {
  profile: ReviewProfile;
  companies: ReviewCompany[];
  initialCompanyId: string;
  initialRoute: AppRoute;
  googleView?: "ads" | "ga4";
  channelScenario: ReviewChannelScenario;
};

/**
 * Carregamento e erro do read model (Supabase, fora do harness): o mesmo
 * contexto da página real, com o estado simulado. Só existe aqui.
 */
function ReviewReadModelState({ scenario, children }: { scenario: ReviewChannelScenario; children: ReactNode }) {
  if (scenario !== "carregando" && scenario !== "erro") return <>{children}</>;
  const value: DashboardDataValue = {
    snapshot: null,
    loading: scenario === "carregando",
    refreshing: false,
    error: scenario === "erro" ? "Falha simulada na leitura do read model." : null,
    refetch: async () => null,
  };
  return <DashboardDataContext.Provider value={value}>{children}</DashboardDataContext.Provider>;
}

export default function ReviewApp({ profile, companies, initialCompanyId, initialRoute, googleView, channelScenario }: Props) {
  const role = REVIEW_PROFILES[profile].role;
  const [route, setRoute] = useState<AppRoute>(initialRoute);
  const [activeId, setActiveId] = useState(initialCompanyId);
  const active = companies.find((company) => company.client_id === activeId) || companies[0];
  const memberships = companies.map((company) => ({ client_id: company.client_id, name: company.name, role }));

  function open(next: AppRoute) {
    setRoute(next);
    const params = new URLSearchParams(window.location.search);
    params.set("tela", ROUTE_TO_SCREEN[next] || "ecommerce");
    window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
    window.scrollTo(0, 0);
  }

  function changeCompany(clientId: string) {
    const next = companies.find((company) => company.client_id === clientId);
    if (!next) return;
    // Mesmo efeito do App real: a empresa ativa vai para o storage antes de remontar a página.
    setActiveClient({ id: next.client_id, name: next.name, role });
    setActiveId(next.client_id);
    const params = new URLSearchParams(window.location.search);
    params.set("empresa", next.client_id);
    window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
  }

  const noop = () => undefined;
  // Mesma derivação do App: agência e administrador do cliente; viewer não.
  const canManage = profile !== "viewer";

  return (
    <div className="appFrame">
      <AppNavigation
        route={route}
        platformAdmin={false}
        agencyAdmin={profile === "agencia"}
        canManageIntegrations={canManage}
        onOpen={open}
        clients={memberships}
        activeClientId={active.client_id}
        onClientChange={changeCompany}
        onLogout={() => window.location.assign(`${window.location.pathname}?tela=login`)}
        user={REVIEW_PROFILES[profile].user}
      />
      <div className="appFrameMain">
        <DashboardDataProvider clientId={active.client_id} tenantReady enabled>
        {route === "ecommerce" ? (
          <Ecommerce
            key={`ecommerce:${active.client_id}`}
            isAuthenticated
            canSync={canManage}
            onLogout={noop}
            onOpenDashboard={() => open("meta")}
            onOpenGoogleReport={() => open("google")}
            onOpenIntegrations={canManage ? () => open("integrations") : undefined}
          />
        ) : route === "meta" ? (
          <ReviewReadModelState scenario={channelScenario}>
            <Dashboard
              key={`dashboard:${active.client_id}`}
              isAuthenticated
              canSync={canManage}
              onOpenSetup={canManage ? () => open("integrations") : undefined}
            />
          </ReviewReadModelState>
        ) : route === "google" ? (
          <ReviewReadModelState scenario={channelScenario}>
            <GoogleAnalytics
              key={`google:${active.client_id}`}
              isAuthenticated
              canSync={canManage}
              initialView={googleView}
              onLogout={noop}
              onOpenDashboard={() => open("meta")}
            />
          </ReviewReadModelState>
        ) : route === "integrations" && canManage ? (
          <Onboarding key={`integrations:${active.client_id}`} isAuthenticated onCompleted={() => open("meta")} />
        ) : (
          <ReviewPlaceholder route={route} company={active.name} />
        )}
        </DashboardDataProvider>
      </div>
    </div>
  );
}
