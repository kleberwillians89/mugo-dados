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

  it("abrir e fechar um grupo pelo botão ao lado do nome", async () => {
    await render({ agencyAdmin: true });
    const toggle = container.querySelector<HTMLButtonElement>('[aria-controls="app-nav-conteudo"]')!;
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    await act(async () => { toggle.click(); });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(container.querySelector<HTMLElement>("#app-nav-conteudo")?.hidden).toBe(false);
  });

  it("organiza o menu na hierarquia gerencial aprovada sem alterar rotas", async () => {
    await render({ agencyAdmin: true });
    expect(groupNames()).toEqual(["Visão Geral", "Tarefas", "Estratégia", "Conteúdo", "Relacionamento", "Vendas", "Mídia", "Tira-dúvidas", "Configurações"]);
    expect(groupLinks("visao-geral")).toEqual(["Dashboard"]);
    expect(groupLinks("tarefas")).toEqual(["Tarefas"]);
    expect(groupLinks("ia")).toEqual(["Tira-dúvidas"]);
    expect(groupLinks("vendas")).toEqual(["Ecommerce", "CRM"]);
    expect(groupLinks("midia")).toEqual(["Meta", "Google", "TikTok", "Pinterest", "LinkedIn", "Mídia On", "Benchmarking"]);
    expect(groupLinks("estrategia")).toEqual(["Clipping e Radar", "Saúde da Marca", "Planejamento", "Briefing", "Criadores", "Relatório"]);
    expect(groupLinks("conteudo")).toEqual(["Social Media", "Redação", "Evento", "Biblioteca"]);
    expect(groupLinks("relacionamento")).toEqual(["WhatsApp", "E-mail marketing", "Comentários"]);
    expect(groupLinks("config")).toEqual([
      "Contexto da Marca", "Integrações", "Usuários", "Empresas", "Saúde das integrações", "Plano e implantação", "Planos e cobrança", "Consumo de IA", "Automações",
    ]);
    // o grupo da tela aberta (Ecommerce) vem aberto; os outros fechados, mas com os links no lugar
    expect(container.querySelector<HTMLElement>("#app-nav-vendas")?.hidden).toBe(false);
    expect(container.querySelector<HTMLElement>("#app-nav-conteudo")?.hidden).toBe(true);
    expect(container.querySelectorAll('.appSidebar a[href="/central"]')).toHaveLength(2); // grupo + item Dashboard
    expect(container.querySelector('[data-group="visao-geral"] .appNavGroupLink')?.getAttribute("href")).toBe("/central");
    expect(link("Saúde da Marca")?.getAttribute("href")).toBe("/saude-da-marca");
    expect(link("IA da marca")).toBeUndefined();
    expect(link("Benchmarking")?.getAttribute("href")).toBe("/benchmark");
    expect(link("Relatório social")).toBeUndefined();
    expect(link("Relatório")?.getAttribute("href")).toBe("/relatorio-social");
  });

  it("CRM reúne Origem das vendas e Clientes num item só e fica ativo nas duas telas", async () => {
    await render({ route: "origins" });
    expect(link("CRM")?.getAttribute("href")).toBe("/crm");
    expect(link("CRM")?.getAttribute("aria-current")).toBe("page");
    expect(link("Clientes")).toBeUndefined();
    expect(link("Origem das vendas")).toBeUndefined();
    await render({ route: "customers" });
    expect(link("CRM")?.getAttribute("aria-current")).toBe("page");
  });

  it("quem só pode ver Clientes abre o CRM direto em Clientes", async () => {
    await render({ route: "customers", canView: (route) => route === "customers" });
    expect(link("CRM")?.getAttribute("href")).toBe("/crm/clientes");
    expect(link("CRM")?.getAttribute("aria-current")).toBe("page");
  });

  it("quem só pode ver Origem das vendas abre o CRM na origem", async () => {
    await render({ route: "origins", canView: (route) => route === "origins" });
    expect(link("CRM")?.getAttribute("href")).toBe("/crm");
  });

  it("cliente vê Tarefas, Clipping e Criadores; Social Media e Redação ficam com a agência", async () => {
    await render();
    expect(link("Tarefas")?.getAttribute("href")).toBe("/tarefas");
    expect(link("Clipping e Radar")?.getAttribute("href")).toBe("/clipping");
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

  it("aplica a permissão existente ao Dashboard sem afetar Saúde da Marca", async () => {
    await render({ agencyAdmin: true, canView: (route) => route !== "central" });
    expect(container.querySelectorAll('a[href="/central"]')).toHaveLength(0);
    expect(groupLinks("estrategia")).toContain("Saúde da Marca");
    expect(container.querySelector('[data-group="visao-geral"]')).toBeNull();
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
