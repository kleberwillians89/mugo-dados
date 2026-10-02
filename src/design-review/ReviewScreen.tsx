// HARNESS DE REVISÃO VISUAL — escolhe a tela a partir da URL (?tela=...).

import { PeriodProvider } from "../app/PeriodContext";
import type { AppRoute } from "../app/routes";
import type { LoginMode } from "../pages/Login";
import { REVIEW_PROFILES, type ReviewChannelScenario, type ReviewCompany, type ReviewProfile, type ReviewScenario } from "./fixtures";
import ReviewApp from "./ReviewApp";
import ReviewBanner from "./ReviewBanner";
import ReviewIndex from "./ReviewIndex";
import ReviewInvite from "./ReviewInvite";
import ReviewLogin from "./ReviewLogin";

const LOGIN_STATES: Record<string, { mode: LoginMode; error: string | null }> = {
  padrao: { mode: "login", error: null },
  erro: { mode: "login", error: "E-mail ou senha incorretos." },
  recuperar: { mode: "recover", error: null },
  definir: { mode: "set-password", error: null },
};

const SCREEN_TO_ROUTE: Record<string, AppRoute> = {
  ecommerce: "ecommerce",
  integracoes: "integrations",
  meta: "meta",
  google: "google",
  "google-ads": "google",
  ga4: "google",
  inteligencia: "intelligence",
  empresas: "companies",
};

type Props = {
  screen: string;
  loginState: string;
  profile: ReviewProfile;
  companies: ReviewCompany[];
  initialCompanyId: string;
  scenario: ReviewScenario;
  channelScenario: ReviewChannelScenario;
  showBanner: boolean;
};

export default function ReviewScreen({ screen, loginState, profile, companies, initialCompanyId, scenario, channelScenario, showBanner }: Props) {
  if (screen === "login") {
    const state = LOGIN_STATES[loginState] || LOGIN_STATES.padrao;
    return <ReviewLogin initialMode={state.mode} initialError={state.error} />;
  }
  if (screen === "convite") {
    return (
      <>
        <ReviewInvite state={loginState} />
        {showBanner ? <ReviewBanner profileLabel="Pessoa já autenticada com convite pendente" /> : null}
      </>
    );
  }
  const route = SCREEN_TO_ROUTE[screen];
  if (!route) return <ReviewIndex />;
  return (
    <PeriodProvider>
      <ReviewApp
        profile={profile}
        companies={companies}
        initialCompanyId={initialCompanyId}
        initialRoute={route}
        googleView={screen === "google-ads" ? "ads" : screen === "ga4" ? "ga4" : undefined}
        channelScenario={route === "meta" || route === "google" ? channelScenario : "padrao"}
      />
      {showBanner ? (
        <ReviewBanner
          profileLabel={REVIEW_PROFILES[profile].label}
          scenario={route === "ecommerce" ? scenario : undefined}
          channelScenario={route === "meta" || route === "google" ? channelScenario : undefined}
        />
      ) : null}
    </PeriodProvider>
  );
}
