// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
import ShopifyChartCard from "./ShopifyChartCard";

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AreaChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Area: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

test("ticket no cabeçalho usa receita total dividida pelos pedidos, não soma tickets diários", async () => {
  const node = document.createElement("div");
  const root = createRoot(node);
  await act(async () => {
    root.render(
      <ShopifyChartCard
        title="Ticket médio"
        data={[
          { date: "2026-08-09", average_ticket: 4500 },
          { date: "2026-08-10", average_ticket: 610 },
        ]}
        dataKey="average_ticket"
        color="#111"
        periodValue={9118.41 / 15}
        valueFormatter={(value) => value.toFixed(2)}
      />
    );
  });
  expect(node.querySelector(".shopifyChartValue")?.textContent).toBe("607.89");
  act(() => root.unmount());
});
