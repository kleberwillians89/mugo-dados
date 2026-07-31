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
    expect(onboarding).toContain("discoverPendingClientMetaAssets");
    expect(onboarding).toContain("Selecionar ativos");
    expect(onboarding).toContain('connectionState === "selection_required"');
  });
});
