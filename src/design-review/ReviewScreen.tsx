// HARNESS DE REVISÃO VISUAL — escolhe a tela a partir da URL (?tela=...).

import {DataHealthProvider} from "../app/DataHealthContext";
import {DataHealthSummary} from "../components/data/DataFreshness";
import { PeriodProvider } from "../app/PeriodContext";
import type { AppRoute } from "../app/routes";
import type { LoginMode } from "../pages/Login";
import { REVIEW_PROFILES, type ReviewChannelScenario, type ReviewCompany, type ReviewProfile, type ReviewScenario } from "./fixtures";
import ReviewApp from "./ReviewApp";
import ReviewBanner from "./ReviewBanner";
import ReviewIndex from "./ReviewIndex";
import ReviewInvite from "./ReviewInvite";
import ReviewLogin from "./ReviewLogin";
import MetricHelp from "../components/data/MetricHelp";
import {METRIC_GLOSSARY, type MetricId} from "../app/metricGlossary";

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
  if (screen === "saude") return <PeriodProvider><DataHealthProvider clientId={initialCompanyId} enabled>
    <main className="ds-page"><h1>Saúde dos Dados — revisão local</h1><DataHealthSummary /></main>
  </DataHealthProvider></PeriodProvider>;
  if (screen === "glossario") return <main className="ds-page"><h1>Glossário de métricas — dados de exemplo</h1>
    <ul>{(Object.keys(METRIC_GLOSSARY) as MetricId[]).map(id => <li key={id}>{METRIC_GLOSSARY[id].name}<MetricHelp label={METRIC_GLOSSARY[id].name} metricId={id} /></li>)}</ul>
  </main>;
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
