// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
import { DashboardDataContext, type DashboardSnapshot } from "../../app/DashboardDataContext";
import useDashboardSummary from "./useDashboardSummary";
const api = vi.hoisted(() => ({ getMedia: vi.fn(), getComments: vi.fn(), getStories: vi.fn() }));
vi.mock("../../app/api", () => api);
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

test("refresh substitui resumo e mídias antigos usando o snapshot retornado após sync", async () => {
  sessionStorage.clear();
  api.getMedia.mockResolvedValue({ media: [{ id: "new-media" }] });
  api.getComments.mockResolvedValue({ comments: [], total: 0, top_words: [] });
  api.getStories.mockResolvedValue({ stories: [] });
  const old = { daily: [{ metric_date: "2026-09-01", instagram_reach: 1 }], sources: [{ provider: "instagram", last_success_at: "2026-09-01T01:00:00Z" }], campaigns: [], products: [], fetchedAt: "old", queryCount: 4 } as unknown as DashboardSnapshot;
  const fresh = { ...old, daily: [{ ...old.daily[0], instagram_reach: 99 }], sources: [{ ...old.sources[0], last_success_at: "2026-09-01T02:00:00Z" }] };
  let reload: ReturnType<typeof useDashboardSummary>["reloadSummary"];
  function Consumer() {
    const summary = useDashboardSummary({ isAuthenticated: true, activeClientId: "summary-refresh", secondaryEnabled: false, period: { start: "2026-09-01", end: "2026-09-01" } });
    React.useEffect(() => { reload = summary.reloadSummary; }, [summary.reloadSummary]);
    return <span>{summary.data.dash?.period_totals?.reach}:{summary.data.media[0]?.id}:{summary.data.dash?.last_sync_at}</span>;
  }
  const node = document.createElement("div"); const root = createRoot(node);
  await act(async () => root.render(<DashboardDataContext.Provider value={{ snapshot: old, loading: false, refreshing: false, error: null, refetch: async () => fresh }}><Consumer /></DashboardDataContext.Provider>));
  expect(node.textContent).toContain("1:");
  await act(async () => { await reload!({ snapshot: fresh, includeSecondary: true }); });
  expect(node.textContent).toContain("99:new-media:2026-09-01T02:00:00Z");
  expect(api.getMedia).toHaveBeenCalledOnce();
  act(() => root.unmount());
});
