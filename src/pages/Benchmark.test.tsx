// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BENCHMARK_FIXTURE as FIXTURE, PRICES_FIXTURE } from "./benchmark.fixture";

vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "roove", getActiveClientName: () => "Roove", getActiveClient: () => ({ id: "roove", role: "agency_admin" }) }));
const api = vi.hoisted(() => ({ getBenchmarkOverview: vi.fn(), refreshBenchmarkInstagram: vi.fn(), removeBenchmarkCompetitor: vi.fn(),
  addBenchmarkCompetitor: vi.fn(), addBenchmarkEvidence: vi.fn(), getBenchmarkPrices: vi.fn(async () => PRICES_FIXTURE), addBenchmarkProduct: vi.fn(),
  checkBenchmarkProduct: vi.fn(), removeBenchmarkProduct: vi.fn(), getStoreCatalog: vi.fn(),
  autoBenchmarkCompetitors: vi.fn(async () => ({ status: "sem_ia", added: [] })) }));
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

  it("lista vazia: a IA cadastra os concorrentes sozinha e a tela recarrega", async () => {
    api.getBenchmarkOverview.mockResolvedValueOnce({ ...FIXTURE, competitors: [], instagram: { available: true, rows: [], collected_at: null } })
      .mockResolvedValue(FIXTURE);
    api.autoBenchmarkCompetitors.mockResolvedValueOnce({ status: "feito", added: [{ ...FIXTURE.competitors[0], why: "mesma categoria" }] });
    api.refreshBenchmarkInstagram.mockResolvedValue({ updated: 1, errors: [] });
    const root = await mount();
    await act(async () => {});
    expect(api.autoBenchmarkCompetitors).toHaveBeenCalledWith(false);
    expect(api.refreshBenchmarkInstagram).toHaveBeenCalled();
    expect(host.textContent).toContain("A IA cadastrou 1 concorrente");
    expect(api.getBenchmarkOverview).toHaveBeenCalledTimes(2);
    act(() => root.unmount());
  });

  it("preços: mostra a mudança, o motivo quando não lê e o atalho da Biblioteca de Anúncios", async () => {
    api.getBenchmarkOverview.mockResolvedValue(FIXTURE);
    await mount();
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(host.textContent).toContain("Preços dos concorrentes");
    expect(host.textContent).toContain("-17,4% em 07/11");
    expect(host.textContent).toContain("Sem leitura: A página não mostra o preço");
    expect(host.querySelectorAll(".bmAdLinks a")).toHaveLength(2);
  });

  it("preços: acompanhar um produto novo manda o link e o dono", async () => {
    api.getBenchmarkOverview.mockResolvedValue(FIXTURE);
    api.addBenchmarkProduct.mockResolvedValue({ ...PRICES_FIXTURE.products[0], error: null, price: 189.9 });
    await mount();
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    const input = host.querySelector<HTMLInputElement>('[aria-label="Link do produto"]')!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(input, "https://loja.com/products/x");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { btn("Acompanhar").click(); await new Promise((r) => setTimeout(r, 0)); });
    expect(api.addBenchmarkProduct).toHaveBeenCalledWith({ url: "https://loja.com/products/x", competitor_id: null });
    expect(host.textContent).toContain("Ele será conferido todo dia.");
  });
});
