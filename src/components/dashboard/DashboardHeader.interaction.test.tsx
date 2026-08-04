// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import DashboardHeader from "./DashboardHeader";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe("DashboardHeader refresh runtime", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  afterEach(async () => {
    if (root) await act(async () => root.unmount());
    container?.remove();
  });

  it("dispatches Atualizar dados and exposes its loading state", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const onRefresh = vi.fn();
    const render = async (refreshing: boolean) => act(async () => root.render(
      <DashboardHeader
        activeView="meta"
        statusChips={[]}
        periodPreset="30d"
        refreshing={refreshing}
        onRefresh={onRefresh}
        onLogout={() => undefined}
      />
    ));

    await render(false);
    const button = [...container.querySelectorAll("button")].find((item) => item.textContent === "Atualizar dados");
    expect(button).toBeTruthy();
    await act(async () => button?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(onRefresh).toHaveBeenCalledTimes(1);

    await render(true);
    const loadingButton = [...container.querySelectorAll("button")].find((item) => item.textContent === "Atualizando...");
    expect(loadingButton).toBeTruthy();
    expect(loadingButton?.disabled).toBe(true);
  });
});
