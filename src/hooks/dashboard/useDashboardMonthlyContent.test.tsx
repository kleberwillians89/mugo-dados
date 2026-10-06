// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
import { getMediaMonthly } from "../../app/api";
import useDashboardMonthlyContent from "./useDashboardMonthlyContent";
import { clearDashboardCacheByPrefix } from "./cache";
vi.mock("../../app/api", () => ({ getMediaMonthly: vi.fn(async () => ({ months: [] })) }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
test("histórico mensal lê tenant e período 7/30/90, sem all-time de 3650 dias", async () => {
  clearDashboardCacheByPrefix("media-monthly");
  function Capture({ start }: { start: string }) {
    const result = useDashboardMonthlyContent({ isAuthenticated: true, activeClientId: "monthly-tenant", activeConnectionId: "conn", period: { start, end: "2026-10-05" } });
    return <output>{result.monthlyRows.length}</output>;
  }
  const node = document.createElement("div"), root = createRoot(node);
  for (const start of ["2026-09-29", "2026-09-06", "2026-07-08"]) {
    await act(async () => root.render(<Capture start={start} />));
    expect(vi.mocked(getMediaMonthly).mock.lastCall?.[0]).toEqual({start, end:"2026-10-05"});
    expect(vi.mocked(getMediaMonthly).mock.lastCall?.[1]?.clientId).toBe("monthly-tenant");
  }
  expect(getMediaMonthly).toHaveBeenCalledTimes(3);
  act(() => root.unmount());
});
