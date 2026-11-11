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

  function groupLinks(label: string) {
    const heading = [...container.querySelectorAll<HTMLElement>(".appNavGroupLabel")]
      .find((item) => item.textContent?.trim() === label);
    return [...(heading?.nextElementSibling?.querySelectorAll<HTMLAnchorElement>("a") || [])]
      .map((item) => item.textContent?.trim());
  }

  it("separa produto, empresa, navegação e conta; o ativo é marcado com aria-current", async () => {
    await render();
    expect(container.querySelector(".appProductName")?.textContent).toBe("MUGOVERSO");
    expect(container.querySelector(".appSidebar .clientSwitcherStatic")).toBeTruthy();
    expect(link("Ecommerce")?.getAttribute("aria-current")).toBe("page");
    expect(link("Meta")?.getAttribute("href")).toBe("/meta");
    expect(link("Metas")).toBeUndefined();
    expect(link("Inteligência")).toBeUndefined();
    expect(link("Integrações")?.getAttribute("href")).toBe("/integracoes");
    expect(link("Calendário")).toBeUndefined();
    expect(link("Empresas")).toBeUndefined();
  });

  it("organiza os itens na nova ordem visual sem alterar suas rotas", async () => {
    await render({ agencyAdmin: true });
    expect(groupLinks("Operação")).toEqual([
      "Mugoverso IA", "Central da Marca", "Briefing", "Planejamento", "Evento", "Tarefas", "Social Media", "Redação", "Criadores", "Biblioteca",
    ]);
    expect(groupLinks("Inteligência")).toEqual([
      "Meta", "Google", "Ecommerce", "Origem das vendas", "WhatsApp", "Mídia On",
      "Clientes", "Comentários", "Clipping", "Radar Cultural", "Relatório",
    ]);
    expect(groupLinks("Administração")).toEqual([
      "Integrações", "Usuários", "Empresas", "Consumo de IA", "Automações", "IA da marca", "Central da Marca",
    ]);
    expect(container.querySelectorAll('a[href="/central"]')).toHaveLength(2);
    expect(link("Radar Cultural")?.getAttribute("href")).toBe("/radar");
    expect(link("Relatório social")).toBeUndefined();
    expect(link("Relatório")?.getAttribute("href")).toBe("/relatorio-social");
  });

  it("mantém Clientes e Origem das vendas separados e marca a rota ativa", async () => {
    await render({ route: "origins" });
    expect(link("Clientes")?.getAttribute("href")).toBe("/clientes");
    expect(link("Origem das vendas")?.getAttribute("href")).toBe("/origem-das-vendas");
    expect(link("Origem das vendas")?.getAttribute("aria-current")).toBe("page");
    expect(link("Clientes")?.getAttribute("aria-current")).toBeNull();
    expect(link("Clientes e vendas")).toBeUndefined();
  });

  it("preserva acesso independente para quem pode ver somente Clientes", async () => {
    await render({ route: "customers", canView: (route) => route === "customers" });
    expect(link("Clientes")?.getAttribute("href")).toBe("/clientes");
    expect(link("Clientes")?.getAttribute("aria-current")).toBe("page");
    expect(link("Origem das vendas")).toBeUndefined();
  });

  it("preserva acesso independente para quem pode ver somente Origem das vendas", async () => {
    await render({ route: "origins", canView: (route) => route === "origins" });
    expect(link("Clientes")).toBeUndefined();
    expect(link("Origem das vendas")?.getAttribute("href")).toBe("/origem-das-vendas");
    expect(link("Origem das vendas")?.getAttribute("aria-current")).toBe("page");
  });

  it("cliente vê Tarefas, Clipping e Criadores; Social Media e Redação ficam com a agência", async () => {
    await render();
    expect(link("Tarefas")?.getAttribute("href")).toBe("/tarefas");
    expect(link("Clipping")?.getAttribute("href")).toBe("/clipping");
    expect(link("Criadores")?.getAttribute("href")).toBe("/criadores");
    expect(link("Social Media")).toBeUndefined();
    expect(link("Redação")).toBeUndefined();
    expect(link("Automações")).toBeUndefined();
    await render({ agencyAdmin: true });
    expect(link("Social Media")?.getAttribute("href")).toBe("/social-media");
    expect(link("Redação")?.getAttribute("href")).toBe("/redacao"); // página própria
    expect(link("Automações")?.getAttribute("href")).toBe("/automacoes");
  });

  it("cliente com o módulo Social Media liberado pela Mugô vê o item; sem ele, não", async () => {
    await render({ canView: (r) => r !== "users" });
    expect(link("Social Media")?.getAttribute("href")).toBe("/social-media");
    expect(link("Redação")?.getAttribute("href")).toBe("/redacao");
    await render({ canView: (r) => r !== "campaigns" && r !== "redacao" && r !== "users" });
    expect(link("Social Media")).toBeUndefined();
    expect(link("Redação")).toBeUndefined();
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

  it("administração exibe somente os itens permitidos pelas regras existentes", async () => {
    await render({ canManageIntegrations: false });
    expect(link("Integrações")).toBeUndefined();
    expect(groupLinks("Administração")).toEqual(["IA da marca", "Central da Marca"]);
    expect(link("Empresas")).toBeUndefined();
    expect(link("Automações")).toBeUndefined();

    await render({ agencyAdmin: true });
    expect(container.textContent).toContain("Administração");
    expect(link("Integrações")).toBeTruthy();
    expect(link("Empresas")?.getAttribute("href")).toBe("/empresas");
  });

  it("aplica a permissão da Central da Marca aos dois atalhos", async () => {
    await render({ agencyAdmin: true, canView: (route) => route !== "central" });
    expect(container.querySelectorAll('a[href="/central"]')).toHaveLength(0);
    expect(groupLinks("Administração")).not.toContain("Central da Marca");
  });

  it("mantém IA da marca visível pela permissão do módulo, sem exigir papel administrativo", async () => {
    await render({ canManageIntegrations: false, canView: (route) => route !== "users" });
    expect(groupLinks("Operação")).not.toContain("IA da marca");
    expect(groupLinks("Administração")).toContain("IA da marca");
    expect(link("IA da marca")?.getAttribute("href")).toBe("/ia-da-marca");

    await render({ canManageIntegrations: false, canView: (route) => route !== "users" && route !== "brand_ai" });
    expect(link("IA da marca")).toBeUndefined();
  });
});
