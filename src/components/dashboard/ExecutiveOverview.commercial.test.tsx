// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import ExecutiveOverview, { type ExecutiveMetric } from "./ExecutiveOverview";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

describe("ExecutiveOverview — KPIs comerciais Meta", () => {
  it("mostra receita, investimento, ROAS, compras e ticket da mesma fonte", async () => {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    const metrics: ExecutiveMetric[] = [
      { key: "revenue", label: "Receita atribuída Meta", value: 900, format: "currency", context: "", source: "Meta Ads" },
      { key: "spend", label: "Investimento", value: 300, format: "currency", context: "", source: "Meta Ads" },
      { key: "roas", label: "ROAS", value: 3, format: "ratio", context: "", source: "Meta Ads" },
      { key: "conversions", label: "Compras", value: 3, format: "number", context: "", source: "Meta Ads" },
      { key: "ticket", label: "Ticket médio", value: 300, format: "currency", context: "", source: "Meta Ads" },
    ];
    await act(async () => root.render(
      <ExecutiveOverview companyName="Amalie" periodLabel="Agosto" comparisonLabel="Anterior" updatedLabel="Agora" metrics={metrics} sources={[]} />
    ));
    const performance = host.querySelector(".performanceHero");
    expect(performance?.textContent).toContain("Receita atribuída Meta");
    expect(performance?.textContent).toContain("Investimento");
    expect(performance?.textContent).toContain("ROAS");
    expect(performance?.textContent).toContain("Compras");
    expect(performance?.textContent).toContain("Ticket médio");
  });
});
