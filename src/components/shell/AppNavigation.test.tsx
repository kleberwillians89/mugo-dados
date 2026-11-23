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

  // Subitens de um grupo do menu (data-group); grupo de um item só devolve o próprio link.
  function groupLinks(id: string) {
    const group = container.querySelector<HTMLElement>(`[data-group="${id}"]`);
    const subs = [...(group?.querySelectorAll<HTMLAnchorElement>(".appNavSubList a") || [])];
    return (subs.length ? subs : [...(group?.querySelectorAll<HTMLAnchorElement>("a") || [])]).map((item) => item.textContent?.trim());
  }
  const groupNames = () => [...container.querySelectorAll<HTMLElement>("[data-group]")].map((g) => g.querySelector(".appNavGroupLink")?.textContent?.trim());

  it("separa produto, empresa, navegação e conta; o ativo é marcado com aria-current", async () => {
    await render({ route: "home" });
    expect(container.querySelector(".appProductName")?.textContent).toBe("MUGOVERSO");
    expect(container.querySelector(".appSidebar .clientSwitcherStatic")).toBeTruthy();
    expect(link("Início")?.getAttribute("aria-current")).toBe("page");
    expect(link("Início")?.getAttribute("href")).toBe("/inicio");
    expect(link("Dashboard")?.getAttribute("href")).toBe("/central");
    expect(link("Meu trabalho")?.getAttribute("href")).toBe("/tarefas");
    expect(link("Biblioteca")?.getAttribute("href")).toBe("/biblioteca");
    expect(link("Integrações")?.getAttribute("href")).toBe("/integracoes");
    expect(link("Fornecedores")).toBeUndefined();
    expect(link("Empresas")).toBeUndefined();
  });

  it("abrir e fechar Configurações pelo botão ao lado do nome", async () => {
    await render({ agencyAdmin: true });
    const toggle = container.querySelector<HTMLButtonElement>('[aria-controls="app-nav-config"]')!;
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    await act(async () => { toggle.click(); });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(container.querySelector<HTMLElement>("#app-nav-config")?.hidden).toBe(false);
  });

  it("mantém somente os pontos transversais aprovados e as configurações autorizadas", async () => {
    await render({ agencyAdmin: true });
    expect(groupNames()).toEqual(["Configurações"]);
    expect([...container.querySelectorAll(".appNavPrimaryList a")].map((item) => item.textContent?.trim())).toEqual([
      "Início", "Dashboard", "Meu trabalho", "Biblioteca",
    ]);
    expect(groupLinks("config")).toEqual([
      "Contexto da Marca", "Integrações", "Usuários", "Empresas", "Saúde das integrações", "Plano e implantação", "Planos e cobrança", "Consumo de IA", "Automações",
    ]);
    expect(link("Meta")).toBeUndefined();
    expect(link("Social Media")).toBeUndefined();
    expect(link("Fornecedores")).toBeUndefined();
  });

  it("links reais: clique simples navega no app; Ctrl/Cmd+clique fica com o navegador", async () => {
    const { onOpen } = await render();
    const home = link("Início")!;
    const plain = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    await act(async () => { home.dispatchEvent(plain); });
    expect(onOpen).toHaveBeenCalledWith("home");
    expect(plain.defaultPrevented).toBe(true);

    const withCtrl = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0, ctrlKey: true });
    await act(async () => { home.dispatchEvent(withCtrl); });
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

  it("administração exibe somente os itens permitidos pelas regras existentes", async () => {
    await render({ canManageIntegrations: false });
    expect(link("Integrações")).toBeUndefined();
    // Admin do cliente sem integrações: em Configurações só o Contexto da Marca da própria empresa.
    expect(groupLinks("config")).toEqual(["Contexto da Marca"]);
    expect(link("Contexto da Marca")?.getAttribute("href")).toBe("/contexto-da-marca");
    expect(link("IA da marca")).toBeUndefined();
    expect(link("Empresas")).toBeUndefined();
    expect(link("Automações")).toBeUndefined();

    await render({ agencyAdmin: true });
    expect(container.textContent).toContain("Configurações");
    expect(link("Integrações")).toBeTruthy();
    expect(link("Empresas")?.getAttribute("href")).toBe("/empresas");
  });

  it("aplica as permissões existentes aos atalhos transversais", async () => {
    await render({ agencyAdmin: true, canView: (route) => route !== "central" });
    expect(container.querySelectorAll('a[href="/central"]')).toHaveLength(0);
    expect(link("Início")).toBeTruthy();
    expect(link("Meu trabalho")).toBeTruthy();
  });

  it("mantém IA da marca fora da navegação sem alterar suas permissões de rota", async () => {
    await render({ canManageIntegrations: false, canView: (route) => route !== "users" });
    expect(link("IA da marca")).toBeUndefined();
    expect(container.querySelector('[data-group="marca"]')).toBeNull();
  });

  it("Contexto da Marca some do menu para quem não vê o módulo da marca", async () => {
    await render({ canManageIntegrations: false, canView: (route) => route !== "brand_ai" && route !== "users" });
    expect(link("Contexto da Marca")).toBeUndefined();
    expect(container.querySelector('[data-group="config"]')).toBeNull();
  });
});
