import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();

describe("mobile product experience contracts", () => {
  it("uses a five-item bottom navigation with safe-area support", () => {
    const app = readFileSync(path.join(root, "src/App.tsx"), "utf8");
    const css = readFileSync(path.join(root, "src/styles/App.css"), "utf8");
    expect(app).toContain('className="mobileBottomNav"');
    expect(app).toContain("Visão Geral");
    expect(app).toContain("E-commerce");
    expect(app).toContain("Inteligência");
    expect(css).toContain("env(safe-area-inset-bottom)");
    expect(css).toContain("grid-template-columns:repeat(5,minmax(0,1fr))");
  });

  it("keeps restricted destinations behind the existing role checks", () => {
    const app = readFileSync(path.join(root, "src/App.tsx"), "utf8");
    expect(app).toMatch(/!isReadOnlyClientRole\(getActiveClient\(\)\?\.role\)[\s\S]*onOpen\("integrations"\)/);
    expect(app).toMatch(/platformAdmin[\s\S]*onOpen\("companies"\)/);
  });

  it("prevents long campaign names from controlling mobile width", () => {
    const css = readFileSync(path.join(root, "src/styles/dashboard.css"), "utf8");
    expect(css).toMatch(/\.topCampaignsName\{[^}]*white-space:normal[^}]*overflow-wrap:anywhere/);
    expect(css).toMatch(/\.topCampaignsHighlights\{ grid-template-columns:1fr/);
  });
});
