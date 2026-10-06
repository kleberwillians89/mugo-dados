// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { DashboardDataContext, type DashboardSnapshot } from "../../app/DashboardDataContext";
import useDashboardSummary from "./useDashboardSummary";
import { clearDashboardCacheByPrefix } from "./cache";
const api = vi.hoisted(() => ({ getMedia: vi.fn(), getComments: vi.fn(), getStories: vi.fn() }));
vi.mock("../../app/api", () => api);
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let node: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const snapshot = { daily: [{ metric_date: "2026-10-01", instagram_reach: 144 }], sources: [], campaigns: [], products: [], fetchedAt: "fixture", queryCount: 4 } as unknown as DashboardSnapshot;
function Harness({ secondary = false, comments = false, loading = false, tenant = "performance-a" }) {
  return <DashboardDataContext.Provider value={{ snapshot, loading, refreshing: false, error: null, refetch: async () => snapshot }}><Result secondary={secondary} comments={comments} tenant={tenant} /></DashboardDataContext.Provider>;
}
function Result({ secondary, comments, tenant }: { secondary: boolean; comments: boolean; tenant: string }) {
  const result = useDashboardSummary({ isAuthenticated: true, activeClientId: tenant, activeConnectionId: "conn", period: { start: "2026-10-01", end: "2026-10-05" }, secondaryEnabled: secondary, commentsEnabled: comments });
  return <output>{result.data.dash?.period_totals?.reach}:{result.data.media.length}:{result.data.comments.length}</output>;
}
beforeEach(() => {
  for (const key of ["summary-media", "summary-comments", "summary-dash"]) clearDashboardCacheByPrefix(key);
  api.getMedia.mockReset().mockResolvedValue({ media: [{ id: "fixture-media" }], has_more: false });
  api.getComments.mockReset().mockResolvedValue({ comments: [{ id: "fixture-comment" }], total: 1, top_words: [] });
  api.getStories.mockReset();
  node = document.createElement("div"); root = createRoot(node);
});
afterEach(() => act(() => root.unmount()));
test("first render apresenta snapshot sem media/comments/stories antecipados", async () => {
  await act(async () => root.render(<Harness />));
  expect(node.textContent).toBe("144:0:0");
  expect(api.getMedia).not.toHaveBeenCalled(); expect(api.getComments).not.toHaveBeenCalled(); expect(api.getStories).not.toHaveBeenCalled();
});
test("StrictMode dispara cada leitura secundária uma vez quando demandada", async () => {
  await act(async () => root.render(<React.StrictMode><Harness secondary comments /></React.StrictMode>));
  expect(api.getMedia).toHaveBeenCalledOnce(); expect(api.getComments).toHaveBeenCalledOnce();
  expect(node.textContent).toBe("144:1:1");
});
test("comentários posteriores reutilizam publicações já carregadas", async () => {
  await act(async () => root.render(<Harness secondary />));
  expect(api.getMedia).toHaveBeenCalledOnce(); expect(api.getComments).not.toHaveBeenCalled();
  await act(async () => root.render(<Harness secondary comments />));
  expect(api.getMedia).toHaveBeenCalledOnce(); expect(api.getComments).toHaveBeenCalledOnce();
});
test("rerender não refaz requests idênticos e cache continua separado por tenant", async () => {
  await act(async () => root.render(<Harness secondary comments />));
  await act(async () => root.render(<Harness secondary comments />));
  expect(api.getMedia).toHaveBeenCalledOnce(); expect(api.getComments).toHaveBeenCalledOnce();
  await act(async () => root.render(<Harness secondary comments tenant="performance-b" />));
  expect(api.getMedia).toHaveBeenCalledTimes(2); expect(api.getComments).toHaveBeenCalledTimes(2);
});
test("snapshot ainda pendente não é renderizado como leitura vazia concluída", async () => {
  await act(async () => root.render(<Harness loading />));
  expect(node.textContent).toBe(":0:0");
  await act(async () => root.render(<Harness />));
  expect(node.textContent).toBe("144:0:0");
});
