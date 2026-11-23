// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AppRoute } from "../app/routes";
import Home from "./Home";
import ProcessEntry, { type ProcessKind } from "./ProcessEntry";

vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("../components/data/PageHeader", () => ({ default: ({ title }: { title: string }) => <h1>{title}</h1> }));
vi.mock("../app/activeClient", () => ({ getActiveClientName: () => "Empresa de teste" }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe("nova entrada e processos", () => {
  let host: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
  afterEach(async () => { await act(async () => root.unmount()); host.remove(); });

  it("Home abre os quatro processos e não inventa contadores de atenção", async () => {
    const open = vi.fn();
    await act(async () => root.render(<Home canView={() => true} onOpen={open} />));
    expect(host.textContent).toContain("O que vamos fazer hoje?");
    for (const label of ["Planejar", "Criar conteúdo", "Lançar campanha", "Analisar resultados"]) expect(host.textContent).toContain(label);
    expect(host.textContent).toContain("Precisa da sua atenção");
    expect(host.textContent).toContain("Ferramentas complementares");
    expect(host.textContent).toContain("Tira-dúvidas");
    expect(host.textContent).not.toMatch(/\d+ pendência/);
    const planning = [...host.querySelectorAll("a")].find((item) => item.textContent?.includes("Planejar"))!;
    await act(async () => planning.click());
    expect(open).toHaveBeenCalledWith("process_planning");
  });

  it("Home mostra atenção apenas quando Tarefas ou Calendário estão autorizados", async () => {
    await act(async () => root.render(<Home canView={(route) => route === "home" || route === "process_analysis"} onOpen={vi.fn()} />));
    expect(host.textContent).not.toContain("Precisa da sua atenção");
    expect(host.textContent).toContain("Analisar resultados");
    expect(host.textContent).not.toContain("Criar conteúdo");
    expect(host.textContent).not.toContain("Ferramentas complementares");
  });

  it("filtra ferramentas de cada processo pela autorização existente", async () => {
    const open = vi.fn();
    await act(async () => root.render(<ProcessEntry kind="planning" canView={(route) => route === "radar" || route === "calendar"} onOpen={open} />));
    expect(host.textContent).toContain("Radar");
    expect(host.textContent).toContain("Calendário");
    expect(host.textContent).not.toContain("Benchmarking");
    expect(host.textContent).not.toContain("Matriz Tática de Conteúdo");
    const calendar = [...host.querySelectorAll("a")].find((item) => item.textContent?.includes("Calendário"))!;
    await act(async () => calendar.click());
    expect(open).toHaveBeenCalledWith("calendar");
  });

  it("as quatro páginas usam somente links para ferramentas reais", async () => {
    const expected: Record<ProcessKind, AppRoute[]> = {
      planning: ["radar", "benchmark", "planning", "goals", "campaigns", "calendar"],
      content: ["campaigns", "redacao", "production", "briefing", "creators"],
      campaign: ["media", "calendar", "tasks"],
      analysis: ["central", "brand_health", "meta", "google", "channels", "origins", "ecommerce", "customers", "clipping", "social_report"],
    };
    for (const kind of Object.keys(expected) as ProcessKind[]) {
      await act(async () => root.render(<ProcessEntry kind={kind} canView={() => true} onOpen={vi.fn()} />));
      const hrefs = [...host.querySelectorAll<HTMLAnchorElement>(".processToolCard")].map((item) => item.getAttribute("href"));
      expect(hrefs.length).toBeGreaterThanOrEqual(expected[kind].length);
      expect(hrefs.every((href) => Boolean(href) && href !== "/404")).toBe(true);
    }
  });
});
