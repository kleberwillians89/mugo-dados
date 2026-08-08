// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import useExecutiveDashboard from "./useExecutiveDashboard";
import { clearDashboardCacheByPrefix } from "./cache";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Nenhuma função de sincronização (runExclusiveSync/POST) é mockada aqui de
// propósito: se o hook tentasse disparar sync em vez de só ler dados
// persistidos, a chamada não mockada quebraria o teste.
vi.mock("../../app/api", () => ({
  getExecutiveDashboard: vi.fn(),
}));

import { getExecutiveDashboard } from "../../app/api";

let container: HTMLDivElement | null = null;
let root: Root | null = null;

async function mount(node: React.ReactElement) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root!.render(node);
  });
}

function unmount() {
  if (root) {
    act(() => {
      root!.unmount();
    });
    root = null;
  }
  if (container) {
    container.remove();
    container = null;
  }
}

beforeEach(() => {
  clearDashboardCacheByPrefix("executive");
});

afterEach(() => {
  unmount();
  vi.clearAllMocks();
});

function Harness({
  clientId,
  start,
  end,
  onState,
}: {
  clientId: string;
  start: string;
  end: string;
  onState: (state: ReturnType<typeof useExecutiveDashboard>) => void;
}) {
  const state = useExecutiveDashboard({
    isAuthenticated: true,
    activeClientId: clientId,
    period: { start, end },
  });
  onState(state);
  return null;
}

describe("useExecutiveDashboard — leitura persistida, nunca sincroniza sozinho", () => {
  it("mount faz uma leitura GET só (nunca POST/sync); dado cacheado aparece de imediato ao remontar com o mesmo período", async () => {
    const response = { ok: true, shopify: null, total_paid_media: { paid_media_spend: 0, included_paid_sources: [], blended_roas: null } };
    const mocked = vi.mocked(getExecutiveDashboard);
    mocked.mockResolvedValueOnce(response as never);
    // A segunda chamada (remount) fica pendurada de propósito — prova que o
    // dado exibido vem do cache, nunca de uma sincronização nova.
    mocked.mockImplementationOnce(() => new Promise(() => {}) as never);

    let latest: ReturnType<typeof useExecutiveDashboard> | null = null;
    await mount(
      <Harness clientId="amalie" start="2026-08-01" end="2026-08-08" onState={(s) => { latest = s; }} />
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(mocked).toHaveBeenCalledTimes(1);
    expect(latest?.executiveData).toEqual(response);

    unmount();
    latest = null;
    await mount(
      <Harness clientId="amalie" start="2026-08-01" end="2026-08-08" onState={(s) => { latest = s; }} />
    );
    expect(latest?.executiveData).toEqual(response);
    expect(latest?.loadingExecutive).toBe(false);
  });

  it("mudar o período faz uma nova leitura GET (nunca sync) com a nova janela", async () => {
    const mocked = vi.mocked(getExecutiveDashboard);
    mocked.mockResolvedValue({ ok: true } as never);

    let latest: ReturnType<typeof useExecutiveDashboard> | null = null;
    await mount(
      <Harness clientId="amalie" start="2026-08-01" end="2026-08-08" onState={(s) => { latest = s; }} />
    );
    await act(async () => {
      await Promise.resolve();
    });
    unmount();

    await mount(
      <Harness clientId="amalie" start="2026-07-01" end="2026-07-08" onState={(s) => { latest = s; }} />
    );
    await act(async () => {
      await Promise.resolve();
    });

    expect(mocked).toHaveBeenLastCalledWith(
      { start: "2026-07-01", end: "2026-07-08" },
      expect.objectContaining({ signal: expect.anything() })
    );
    expect(latest).not.toBeNull();
  });
});
