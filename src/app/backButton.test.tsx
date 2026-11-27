// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import PageHeader from "../components/data/PageHeader";
import { appHistoryDepth, goBackInApp, navigateToAppRoute } from "./routes";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => { vi.restoreAllMocks(); window.history.replaceState(null, "", "/"); document.body.innerHTML = ""; });

describe("Voltar das páginas internas", () => {
  it("conta as telas do Mugoverso no histórico (replace não conta)", () => {
    window.history.replaceState(null, "", "/");
    expect(appHistoryDepth()).toBe(0);
    navigateToAppRoute("process_planning");
    expect(appHistoryDepth()).toBe(1);
    navigateToAppRoute("planning");
    expect(appHistoryDepth()).toBe(2);
    navigateToAppRoute("media", { replace: true });
    expect(appHistoryDepth()).toBe(2);
  });

  it("com histórico interno, volta à tela anterior", () => {
    navigateToAppRoute("planning");
    const back = vi.spyOn(window.history, "back").mockImplementation(() => undefined);
    goBackInApp();
    expect(back).toHaveBeenCalledTimes(1);
  });

  it("sem histórico interno (link direto), vai ao Início e avisa o app", () => {
    window.history.replaceState(null, "", "/midia-on");
    const back = vi.spyOn(window.history, "back");
    const pop = vi.fn();
    window.addEventListener("popstate", pop);
    goBackInApp();
    window.removeEventListener("popstate", pop);
    expect(back).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe("/inicio");
    expect(pop).toHaveBeenCalledTimes(1);
  });

  it("PageHeader mostra 'Voltar' perto do título; Home e link público não", async () => {
    const host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => root.render(<PageHeader title="Mídia On" />));
    const button = host.querySelector(".ds-backButton");
    expect(button?.textContent).toContain("Voltar");
    expect(button?.nextElementSibling?.textContent).toBe("Mídia On");
    await act(async () => root.render(<PageHeader title="O que vamos fazer hoje?" back={false} />));
    expect(host.querySelector(".ds-backButton")).toBeNull();
    window.history.replaceState(null, "", "/aprovar/abcdefghijabcdefghijabcdefghij12");
    await act(async () => root.render(<PageHeader title="Aprovação" />));
    expect(host.querySelector(".ds-backButton")).toBeNull();
    await act(async () => root.unmount());
  });
});
