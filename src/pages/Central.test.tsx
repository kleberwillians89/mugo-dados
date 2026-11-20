// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CentralView } from "../app/studio";

const activeClient = vi.hoisted(() => ({ id: "tenant-a" }));
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => activeClient.id, getActiveClientName: () => "Maison Demo" }));
const getCentral = vi.fn();
vi.mock("../app/studio", async (original) => ({ ...(await original<typeof import("../app/studio")>()), getCentral: (...args: unknown[]) => getCentral(...args) }));
const navigate = vi.fn();
vi.mock("../app/routes", async (original) => ({ ...(await original<typeof import("../app/routes")>()), navigateToAppRoute: (route: string) => navigate(route) }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("../components/data/PageHeader", () => ({ default: ({ title, controls }: { title: string; controls: React.ReactNode }) => <header><h1>{title}</h1>{controls}</header> }));
vi.mock("../components/studio/AiUsageButton", () => ({ default: () => null }));
vi.mock("../components/data/KpiFigure", () => ({ default: ({ label, value }: { label: string; value: string }) => <div>{label}: {value}</div> }));
vi.mock("../components/clipping/HealthIndexCard", () => ({ default: ({ compact }: { compact?: boolean }) => <div>Saúde compacta: {String(compact)}</div> }));
vi.mock("../components/home/HomeChannels", () => ({ default: () => <div>Canais operacionais</div> }));
vi.mock("../components/data/PageSkeleton", () => ({ default: ({ label }: { label: string }) => <p>{label}</p> }));

import Central, { buildDashboardSummary, isCurrentClientRequest } from "./Central";

const fixture: CentralView = {
  month: "2026-11", agency: true,
  numbers: { start: "2026-11-01", end: "2026-11-15", investimento: 1200, faturamento: 8300, pedidos: 7, retorno: 6.9, melhor_campanha: null },
  calendar: {
    total: 6, waiting_client: 1, off_brand: [],
    counts: { rascunho: 1, revisao_interna: 2, com_cliente: 1, ajuste: 0, aprovado: 1, publicado: 1 },
    upcoming: [{ id: "post-1", title: "Editorial de verão", format: "reels", scheduled_at: "2026-11-20T15:00:00Z", stage: "aprovado", pillar: "Marca" }],
  },
  media: null, clipping: null,
  tasks: { available: true, open: 4, late: 0, next: [{ title: "Revisar campanha", due_date: "2026-11-18", status: "doing" }] },
  campaigns: [], alerts: [{ level: "atencao", module: "tasks", text: "Uma tarefa precisa de revisão." }],
};

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe("Dashboard gerencial", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    activeClient.id = "tenant-a";
    getCentral.mockReset();
    navigate.mockReset();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("distingue zero de dado indisponível e usa apenas estados reais", () => {
    expect(buildDashboardSummary(fixture)).toEqual({ inProgress: 4, waitingApproval: 3, overdue: 0, completed: null, onTime: null });
    expect(buildDashboardSummary({ ...fixture, tasks: { available: false }, calendar: null })).toEqual({ inProgress: null, waitingApproval: null, overdue: null, completed: null, onTime: null });
  });

  it("prioriza marca e resultados, mantém fluxos operacionais recolhidos", async () => {
    getCentral.mockResolvedValue(fixture);
    await act(async () => { root.render(<Central isAgency />); });
    expect(container.textContent).toContain("Dashboard");
    expect(container.textContent).toContain("Maison Demo, em perspectiva.");
    expect(container.textContent).toContain("Saúde compacta: true");
    expect(container.textContent).toContain("Faturamento da loja");
    expect(container.textContent?.replace(/\u00a0/g, " ")).toContain("R$ 8.300,00");
    expect(container.textContent).toContain("Ticket médio estimado");
    expect(container.textContent).not.toContain("Trabalhos em andamento");
    const hero = container.querySelector(".clientExecutiveWelcome");
    const health = container.querySelector(".clientExecutiveHealth");
    const results = container.querySelector(".clientExecutiveResults");
    expect(hero).not.toBeNull();
    expect(health).not.toBeNull();
    expect(results).not.toBeNull();
    expect(Boolean(hero && health && (hero.compareDocumentPosition(health) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
    expect(Boolean(health && results && (health.compareDocumentPosition(results) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
    expect(container.querySelector(".centralManagementGrid")?.closest("details")).not.toBeNull();
    expect(container.textContent).toContain("Revisão interna");
    expect(container.textContent).toContain("Editorial de verão");
    const ecommerce = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("Faturamento da loja"))!;
    await act(async () => { ecommerce.click(); });
    expect(navigate).toHaveBeenCalledWith("ecommerce");
  });

  it("só aceita a resposta do tenant que iniciou a leitura", () => {
    expect(isCurrentClientRequest("tenant-a", "tenant-a")).toBe(true);
    expect(isCurrentClientRequest("tenant-a", "tenant-b")).toBe(false);
    expect(isCurrentClientRequest(null, "tenant-a")).toBe(false);
  });
});
