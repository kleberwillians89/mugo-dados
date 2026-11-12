// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "curavino", getActiveClientName: () => "Curavino" }));
vi.mock("../app/media", async (original) => ({ ...(await original<typeof import("../app/media")>()),
  getPlan: vi.fn(async () => ({ month: "2026-12-01", plan: null, elapsed_days: 0, days_in_month: 31, channels: [] })),
  listStrategies: vi.fn(async () => ({ strategies: [] })),
  generateStrategy: vi.fn(async () => { throw new Error("Sem dados de mídia ainda."); }),
}));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: unknown }) => children }));
vi.mock("../components/data/PageHeader", () => ({ default: () => null }));
vi.mock("../components/studio/BrandContextPanel", () => ({ default: () => null }));
vi.mock("../components/studio/MetaAdsPanel", () => ({ default: () => null }));

import * as media from "../app/media";
import MediaOn from "./MediaOn";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
afterEach(() => { host?.remove(); vi.clearAllMocks(); });

describe("Mídia On", () => {
  it("mês vazio: a equipe já abre com a IA gerando a estratégia (uma vez só)", async () => {
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => { root.render(<MediaOn canManage />); });
    await act(async () => {});
    expect(media.generateStrategy).toHaveBeenCalledTimes(1);
    expect(vi.mocked(media.generateStrategy).mock.calls[0][0].objective).toBe("vendas");
    expect(host.textContent).toContain("Sem dados de mídia ainda.");
    act(() => root.unmount());
  });

  it("cliente (sem gestão) nunca gera sozinho", async () => {
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => { root.render(<MediaOn canManage={false} />); });
    await act(async () => {});
    expect(media.generateStrategy).not.toHaveBeenCalled();
    act(() => root.unmount());
  });
});
