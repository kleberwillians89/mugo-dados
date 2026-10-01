// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import PerformanceChart from "./PerformanceChart";

vi.mock("react-chartjs-2", () => ({ Line: () => <div data-testid="line-chart" /> }));

describe("PerformanceChart", () => {
  it("mostra um dia isolado como valor visível da métrica inicial", async () => {
    const node = document.createElement("div");
    const root = createRoot(node);
    await act(async () => root.render(<PerformanceChart daily={[{
      date: "2026-06-11", missing: false, revenue: 2172.27, spend: 306.15,
      reach: 0, impressions: 0, clicks: 0, roas: 7.09, conversions: 4,
      cpc: null, cpm: null, ctr: null,
    }]} />));
    expect(node.textContent).toContain("Investimento por dia");
    expect(node.textContent).toContain("R$ 306,15");
    expect(node.textContent).toContain("Fonte: Meta Ads");
    expect(node.querySelector('[data-testid="performance-single-day"]')).not.toBeNull();
    await act(async () => root.unmount());
  });

  it("distingue dia ausente de zero explícito", async () => {
    const node = document.createElement("div");
    const root = createRoot(node);
    await act(async () => root.render(<PerformanceChart daily={[{
      date: "2026-06-12", missing: true, revenue: null, spend: null,
      reach: null, impressions: null, clicks: null, roas: null, conversions: null,
      cpc: null, cpm: null, ctr: null,
    }]} />));
    expect(node.textContent).toContain("Sem dados Meta para esta data");
    await act(async () => root.render(<PerformanceChart daily={[{
      date: "2026-06-12", missing: false, revenue: 0, spend: 0,
      reach: 0, impressions: 0, clicks: 0, roas: null, conversions: 0,
      cpc: null, cpm: null, ctr: null,
    }]} />));
    expect(node.textContent).toContain("R$ 0");
    await act(async () => root.unmount());
  });
});
