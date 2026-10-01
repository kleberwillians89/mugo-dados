// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AppNavigation from "./AppNavigation";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe("AppNavigation — sidebar global", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  async function render(props: Partial<React.ComponentProps<typeof AppNavigation>> = {}) {
    const onOpen = vi.fn();
    const onLogout = vi.fn();
    await act(async () => root.render(
      <AppNavigation
        route="ecommerce"
        platformAdmin={false}
        agencyAdmin={false}
        canManageIntegrations
        onOpen={onOpen}
        clients={[{ client_id: "vinhos", name: "Curavino", role: "client_admin" }]}
        activeClientId="vinhos"
        onClientChange={() => {}}
        onLogout={onLogout}
        user={{ name: "Ana Souza", email: "ana@exemplo.com.br" }}
        {...props}
      />
    ));
    return { onOpen, onLogout };
  }

  function link(text: string) {
    return [...container.querySelectorAll<HTMLAnchorElement>(".appSidebar a")].find((item) => item.textContent?.trim() === text);
  }

  it("separa produto, empresa, navegação e conta; o ativo é marcado com aria-current", async () => {
    await render();
    expect(container.querySelector(".appProductName")?.textContent).toBe("Mugô Dados");
    expect(container.querySelector(".appSidebar .clientSwitcherStatic")).toBeTruthy();
    expect(link("Ecommerce")?.getAttribute("aria-current")).toBe("page");
    expect(link("Meta")?.getAttribute("href")).toBe("/meta");
    expect(link("Integrações")?.getAttribute("href")).toBe("/integracoes");
    expect(link("Empresas")).toBeUndefined();
  });

  it("links reais: clique simples navega no app; Ctrl/Cmd+clique fica com o navegador", async () => {
    const { onOpen } = await render();
    const meta = link("Meta")!;
    const plain = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    await act(async () => { meta.dispatchEvent(plain); });
    expect(onOpen).toHaveBeenCalledWith("meta");
    expect(plain.defaultPrevented).toBe(true);

    const withCtrl = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0, ctrlKey: true });
    await act(async () => { meta.dispatchEvent(withCtrl); });
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(withCtrl.defaultPrevented).toBe(false);
  });

  it("gaveta móvel: abre pelo botão, Esc fecha e devolve o foco", async () => {
    await render();
    const menuButton = container.querySelector(".appTopbarMenu") as HTMLButtonElement;
    expect(menuButton.getAttribute("aria-expanded")).toBe("false");
    await act(async () => { menuButton.click(); });
    expect(menuButton.getAttribute("aria-expanded")).toBe("true");
    expect(container.querySelector(".appSidebar")?.classList.contains("is-open")).toBe(true);
    expect(container.querySelector(".appSidebar")?.contains(document.activeElement)).toBe(true);
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(container.querySelector(".appSidebar")?.classList.contains("is-open")).toBe(false);
    expect(document.activeElement).toBe(menuButton);
  });

  it("menu da conta: Esc e clique fora fecham; Sair chama o logout recebido", async () => {
    const { onLogout } = await render();
    const trigger = container.querySelector(".userMenuTrigger") as HTMLButtonElement;
    expect(trigger.textContent).toContain("Ana Souza");

    await act(async () => { trigger.click(); });
    expect(container.querySelector('[role="menu"]')?.textContent).toContain("ana@exemplo.com.br");
    await act(async () => {
      document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(container.querySelector('[role="menu"]')).toBeNull();
    expect(document.activeElement).toBe(trigger);

    await act(async () => { trigger.click(); });
    await act(async () => { document.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true })); });
    expect(container.querySelector('[role="menu"]')).toBeNull();

    await act(async () => { trigger.click(); });
    const logout = container.querySelector('[role="menuitem"]') as HTMLButtonElement;
    expect(logout.textContent).toBe("Sair");
    await act(async () => { logout.click(); });
    expect(onLogout).toHaveBeenCalledTimes(1);
  });

  it("administração só aparece com as permissões já existentes", async () => {
    await render({ canManageIntegrations: false });
    expect(link("Integrações")).toBeUndefined();
    expect(container.textContent).not.toContain("Administração");

    await render({ agencyAdmin: true });
    expect(container.textContent).toContain("Administração");
    expect(link("Integrações")).toBeTruthy();
    expect(link("Empresas")?.getAttribute("href")).toBe("/empresas");
  });
});
