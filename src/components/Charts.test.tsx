// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MonthCompareLines, MonthMixChart } from "./Charts";
import type { MonthAgg } from "../app/types";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

function makeMonth(overrides: Partial<MonthAgg> = {}): MonthAgg {
  return {
    month: "2026-08",
    posts: 0,
    reels: 0,
    reach: 0,
    views: 0,
    interactions: 0,
    profile_visits: 0,
    ...overrides,
  } as MonthAgg;
}

describe("MonthMixChart — estado vazio real (não desenha eixos sem dado)", () => {
  it("mostra o estado vazio, não um gráfico com barras zeradas, quando não há posts nem alcance", async () => {
    await act(async () => {
      root.render(<MonthMixChart data={[makeMonth(), makeMonth({ month: "2026-07" })]} />);
    });
    await act(async () => Promise.resolve());
    expect(container.querySelector(".chartEmptyState")).toBeTruthy();
    expect(container.querySelector("svg")).toBeNull();
  });

  it("renderiza o gráfico normalmente quando há dado real", async () => {
    await act(async () => {
      root.render(<MonthMixChart data={[makeMonth({ posts: 5, reach: 1200 })]} />);
    });
    await act(async () => Promise.resolve());
    expect(container.querySelector(".chartEmptyState")).toBeNull();
  });
});

describe("MonthCompareLines — estado vazio real", () => {
  it("mostra o estado vazio quando os dois meses não têm nenhum valor", async () => {
    await act(async () => {
      root.render(
        <MonthCompareLines aLabel="Julho" bLabel="Agosto" a={makeMonth()} b={makeMonth()} />
      );
    });
    await act(async () => Promise.resolve());
    expect(container.querySelector(".chartEmptyState")).toBeTruthy();
  });

  it("renderiza a comparação quando ao menos um mês tem dado", async () => {
    await act(async () => {
      root.render(
        <MonthCompareLines aLabel="Julho" bLabel="Agosto" a={makeMonth({ posts: 3 })} b={makeMonth()} />
      );
    });
    await act(async () => Promise.resolve());
    expect(container.querySelector(".chartEmptyState")).toBeNull();
  });
});
