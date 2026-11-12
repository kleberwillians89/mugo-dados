// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BENCHMARK_FIXTURE as FIXTURE } from "./benchmark.fixture";

vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "roove", getActiveClientName: () => "Roove" }));
const api = vi.hoisted(() => ({ getBenchmarkOverview: vi.fn(), refreshBenchmarkInstagram: vi.fn(), removeBenchmarkCompetitor: vi.fn(),
  addBenchmarkCompetitor: vi.fn(), addBenchmarkEvidence: vi.fn() }));
vi.mock("../app/benchmark", () => api);
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: unknown }) => children }));
vi.mock("../components/data/PageHeader", () => ({ default: ({ title, controls }: { title: string; controls: unknown }) => <header><h1>{title}</h1>{controls as never}</header> }));

import Benchmark from "./Benchmark";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
afterEach(() => { host?.remove(); vi.clearAllMocks(); });
async function mount() {
  host = document.createElement("div"); document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<Benchmark />); });
  return root;
}
const btn = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.includes(label)) as HTMLButtonElement;

describe("Benchmarking", () => {
  it("compara a marca com os concorrentes no Instagram e mostra o share de atenção", async () => {
    api.getBenchmarkOverview.mockResolvedValue(FIXTURE);
    const root = await mount();
    expect(host.querySelector(".bmBig")?.textContent).toContain("38,4%");
    const rows = [...host.querySelectorAll(".bmTable tbody tr")];
    expect(rows[0].className).toBe("is-brand");
    expect(rows[1].textContent).toContain("amostra");
    expect(host.querySelector(".bmShare .is-brand")?.getAttribute("style")).toContain("38.4%");
    act(() => root.unmount());
  });

  it("atualiza o Instagram e remove concorrente", async () => {
    api.getBenchmarkOverview.mockResolvedValue(FIXTURE);
    api.refreshBenchmarkInstagram.mockResolvedValue({ updated: 2, errors: [{ handle: "altogiro", error: "x" }] });
    api.removeBenchmarkCompetitor.mockResolvedValue({ removed: "c2" });
    const root = await mount();
    await act(async () => { btn("Atualizar Instagram").click(); });
    expect(host.querySelector("[role=status]")?.textContent).toContain("@altogiro não respondeu");
    await act(async () => { (host.querySelector('button[aria-label="Remover Alto Giro"]') as HTMLButtonElement).click(); });
    expect(api.removeBenchmarkCompetitor).toHaveBeenCalledWith("c2");
    expect(api.getBenchmarkOverview).toHaveBeenCalledTimes(3);
    act(() => root.unmount());
  });

  it("sem @ de concorrente, explica o primeiro passo", async () => {
    api.getBenchmarkOverview.mockResolvedValue({ ...FIXTURE, competitors: [], instagram: { available: true, rows: [], collected_at: null } });
    const root = await mount();
    expect(host.querySelector(".bmEmpty")?.textContent).toContain("Cadastre o @");
    act(() => root.unmount());
  });
});
