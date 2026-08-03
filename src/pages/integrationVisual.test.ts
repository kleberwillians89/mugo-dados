import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

function source(relative: string) {
  return readFileSync(new URL(relative, import.meta.url), "utf8");
}

describe("professional integration states and official identity", () => {
  it("uses the official Mugô assets instead of the legacy SVG", () => {
    const app = source("../App.tsx");
    const login = source("./Login.tsx");
    const onboarding = source("./Onboarding.tsx");
    const logo = source("../components/MugoLogo.tsx");
    const html = source("../../index.html");
    const combined = `${app}\n${login}\n${onboarding}\n${logo}\n${html}`;
    expect(combined).toContain("MugoLogo");
    expect(combined).toContain("/mugo_logo1.png");
    expect(combined).toContain("MUG%C3%94_LOGO5.png");
    expect(combined).not.toContain("assets/mugo-logo.svg");
  });

  it("renders accessible text alongside red yellow and green status lights", () => {
    const onboarding = source("./Onboarding.tsx");
    const css = source("../styles/onboarding.css");
    expect(onboarding).toContain("integrationLight");
    expect(onboarding).toContain("Em desenvolvimento");
    expect(css).toContain(".integrationLight.is-red");
    expect(css).toContain(".integrationLight.is-yellow");
    expect(css).toContain(".integrationLight.is-green");
    expect(css).toContain("prefers-reduced-motion");
  });

  it("resumes Meta asset selection without starting a second OAuth flow", () => {
    const onboarding = source("./Onboarding.tsx");
    expect(onboarding).toContain("configureExistingMetaOrganic");
    expect(onboarding).toContain("Selecionar ativos");
    expect(onboarding).toContain('connectionState === "selection_required"');
  });

  it("does not manage disconnected Google Ads connections", () => {
    const onboarding = source("./Onboarding.tsx");
    const api = source("../app/api.ts");
    expect(onboarding).toContain('isUsableGoogleConnection(item, "google_ads", activeClientId)');
    expect(onboarding).toContain('onStartGoogleOAuth("google_ads")');
    expect(api).toContain('["connected", "selection_required"].includes(status)');
    expect(api).toContain("!connection.disconnected_at");
    expect(api).toContain("connection.token_available === true");
  });

  it("ships the manual Meta routes and explicit deployment error", () => {
    const onboarding = source("./Onboarding.tsx");
    const api = source("../app/api.ts");
    expect(onboarding).toContain("Configuração avançada por ID");
    expect(onboarding).toContain("Validar IDs");
    expect(onboarding).toContain("Atualize o deploy do backend");
    expect(api).toContain("manual-assets/validate");
    expect(api).toContain("manual-assets");
  });

  it("does not present disconnected commerce or empty Ads jobs as successful", () => {
    const dashboard = source("./Dashboard.tsx");
    const executive = source("../components/dashboard/ExecutiveOverview.tsx");
    expect(dashboard).toContain('paidSyncStatus === "skipped"');
    expect(dashboard).toContain('"Aguardando sincronização válida"');
    expect(dashboard).toContain('["connected", "active", "updated"].includes');
    expect(executive).toContain("E-commerce não conectado");
  });

  it("separates Meta identity from the selected Ads account", () => {
    const onboarding = source("./Onboarding.tsx");
    expect(onboarding).toContain("Selecionar conta Meta Ads");
    expect(onboarding).toContain("Sincronizar agora");
    expect(onboarding).toContain("selectedPaidConnection?.ad_account_id");
    expect(onboarding).not.toContain('Conta: {connection.account_name}');
  });
});
