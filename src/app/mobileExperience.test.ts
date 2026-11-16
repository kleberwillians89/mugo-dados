import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();

describe("mobile product experience contracts", () => {
  it("uses the same navigation as a mobile drawer, opened from a minimal top bar with safe-area support", () => {
    const nav = readFileSync(path.join(root, "src/components/shell/AppNavigation.tsx"), "utf8");
    const app = readFileSync(path.join(root, "src/App.tsx"), "utf8");
    const css = readFileSync(path.join(root, "src/styles/shell.css"), "utf8");
    expect(app).toContain("<AppNavigation");
    expect(nav).toContain('className="appTopbar"');
    expect(nav).toContain('aria-controls="app-sidebar"');
    // O grupo "Visão Geral" abre o Dashboard; Saúde da Marca permanece em Estratégia.
    expect(nav.match(/label: "Visão Geral"/g)?.length).toBe(1);
    expect(nav.match(/label: "Dashboard"/g)?.length).toBe(1);
    expect(nav).toMatch(/id: "estrategia"[\s\S]*?routes: \["clipping", "brand_health"/);
    expect(nav).not.toContain('label: "Central da Marca"');
    expect(nav).not.toContain('label: "IA da marca"');
    expect(nav).toContain("Ecommerce");
    expect(nav).toContain("Social Media");
    expect(nav).not.toContain('{ route: "calendar", label: "Calendário" }');
    expect(css).toContain("env(safe-area-inset-top)");
    expect(css).toMatch(/@media \(max-width: 1023px\)[\s\S]*?\.appSidebar\{[\s\S]*?transform: translateX\(-100%\)/);
  });

  it("keeps restricted destinations behind the existing role checks", () => {
    const nav = readFileSync(path.join(root, "src/components/shell/AppNavigation.tsx"), "utf8");
    expect(nav).toMatch(/showIntegrations = canManageIntegrations \?\? \(platformAdmin \|\| agencyAdmin\)/);
    expect(nav).toMatch(/if \(showIntegrations\) adminItems\.push\(\{ route: "integrations"/);
    expect(nav).toMatch(/if \(platformAdmin \|\| agencyAdmin\) adminItems\.push\(\{ route: "companies"/);
  });

  it("prevents long campaign names from controlling mobile width", () => {
    const css = readFileSync(path.join(root, "src/styles/dashboard.css"), "utf8");
    expect(css).toMatch(/\.topCampaignsName\{[^}]*white-space:normal[^}]*overflow-wrap:anywhere/);
    expect(css).toMatch(/\.topCampaignsHighlights\{ grid-template-columns:1fr/);
  });
});
