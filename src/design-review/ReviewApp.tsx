// HARNESS DE REVISÃO VISUAL — somente desenvolvimento (fora do build).
// Monta o frame real (AppNavigation + páginas reais) com um perfil simulado.

import { useState } from "react";
import { setActiveClient } from "../app/activeClient";
import { DashboardDataProvider } from "../app/DashboardDataContext";
import type { AppRoute } from "../app/routes";
import DataNotice from "../components/data/DataNotice";
import PageHeader from "../components/data/PageHeader";
import Shell from "../components/Shell";
import AppNavigation from "../components/shell/AppNavigation";
import Ecommerce from "../pages/Ecommerce";
import Onboarding from "../pages/Onboarding";
import { REVIEW_PROFILES, type ReviewCompany, type ReviewProfile } from "./fixtures";

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
};

export default function ReviewApp({ profile, companies, initialCompanyId, initialRoute }: Props) {
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
