// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AppRoute } from "../app/routes";
import Home from "./Home";
import ProcessEntry, { type ProcessKind } from "./ProcessEntry";

vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("../components/data/PageHeader", () => ({ default: ({ title }: { title: string }) => <h1>{title}</h1> }));
vi.mock("../app/activeClient", () => ({ getActiveClientName: () => "Empresa de teste" }));
vi.mock("../components/shell/MyTasksButton", () => ({ default: () => <a className="myTasksButton">Minhas Tarefas</a> }));
vi.mock("../components/shell/MugoNoticed", () => ({ default: () => null }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe("nova entrada e processos", () => {
  let host: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
  afterEach(async () => { await act(async () => root.unmount()); host.remove(); });

  it("Home abre os seis processos e não inventa contadores de atenção", async () => {
    const open = vi.fn();
    await act(async () => root.render(<Home canView={() => true} onOpen={open} />));
    expect(host.textContent).toContain("O que vamos fazer hoje?");
    for (const label of ["Planejar", "Criar conteúdo", "Lançar campanha", "Relacionamento", "CRM", "Redes sociais"]) expect(host.textContent).toContain(label);
    expect(host.querySelectorAll(".processHomeCard")).toHaveLength(6);
    expect(host.textContent).not.toContain("Analisar resultados");
    expect(host.textContent).not.toContain("Precisa da sua atenção");
    expect(host.textContent).toContain("Aprovação Interna");
    expect(host.textContent).toContain("Aprovação Final");
    expect(host.textContent).not.toContain("Ferramentas complementares");
    expect(host.textContent).not.toContain("Tira-dúvidas");  // fica no menu lateral
    for (const moved of ["E-mail Marketing", "Disparos em massa", "Comentários"]) expect(host.textContent).not.toContain(moved);
    expect(host.textContent).not.toMatch(/\d+ pendência/);
    const planning = [...host.querySelectorAll("a")].find((item) => item.textContent?.includes("Planejar"))!;
    await act(async () => planning.click());
    expect(open).toHaveBeenCalledWith("process_planning");
    const internalApproval = [...host.querySelectorAll("a")].find((item) => item.textContent?.includes("Aprovação Interna"))!;
    await act(async () => internalApproval.click());
    expect(open).toHaveBeenCalledWith("internal_approval");
  });

  it("Home mostra cada aprovação somente quando a etapa está autorizada", async () => {
    await act(async () => root.render(<Home canView={(route) => route === "home" || route === "process_analysis"} onOpen={vi.fn()} />));
    expect(host.textContent).not.toContain("Precisa da sua atenção");
    expect(host.textContent).toContain("CRM");
    expect(host.textContent).not.toContain("Criar conteúdo");
    expect(host.textContent).not.toContain("Ferramentas complementares");
    await act(async () => root.render(<Home canView={(route) => route === "final_approval"} onOpen={vi.fn()} />));
    expect(host.textContent).toContain("Aprovação Final");
    expect(host.textContent).not.toContain("Aprovação Interna");
  });

  it("filtra ferramentas de cada processo pela autorização existente", async () => {
    const open = vi.fn();
    await act(async () => root.render(<ProcessEntry kind="planning" canView={(route) => route === "radar" || route === "calendar"} canUse={() => false} onOpen={open} />));
    expect(host.textContent).toContain("Radar");
    expect(host.textContent).toContain("Calendário");
    expect(host.textContent).not.toContain("Benchmarking");
    expect(host.textContent).not.toContain("Matriz Tática de Conteúdo");
    const calendar = [...host.querySelectorAll("a")].find((item) => item.textContent?.includes("Calendário"))!;
    await act(async () => calendar.click());
    expect(open).toHaveBeenCalledWith("calendar");
  });

  it("Planejar (sem o bloco antigo Meu planejamento): ações de início e seis ferramentas existentes", async () => {
    const open = vi.fn();
    await act(async () => root.render(<ProcessEntry kind="planning" canView={() => true} canUse={() => true} onOpen={open} />));
    expect(host.textContent).not.toContain("Meu planejamento");
    expect(host.textContent).not.toContain("Continuar planejamento");
    expect(host.textContent).toContain("Começar um trabalho");
    for (const action of ["Criar planejamento", "Criar Matriz Tática", "Definir metas"]) expect(host.textContent).toContain(action);
    expect(host.querySelectorAll(".planningToolCard")).toHaveLength(6);
    for (const tool of ["Radar", "Benchmarking", "Planejamento", "Metas", "Matriz Tática de Conteúdo", "Calendário"]) expect(host.textContent).toContain(tool);
    expect(host.textContent).not.toMatch(/\d+ (planejamentos?|projetos?|pendências?)/i);

    // Criar planejamento leva direto ao formulário (link com ?novo=1 e pedido de sessão no clique).
    const create = [...host.querySelectorAll("a")].find((item) => item.textContent?.includes("Criar planejamento"))!;
    expect(create.getAttribute("href")).toBe("/planejamento?novo=1");
    await act(async () => create.click());
    expect(open).toHaveBeenCalledWith("planning");
    expect(window.sessionStorage.getItem("mugo:projects:new")).toBe("planejamento");
    window.sessionStorage.clear();

    // Definir metas abre o Planejamento na seção Metas (mesmos registros de /metas).
    const goalsStart = [...host.querySelectorAll("a.planningStartCard")].find((item) => item.textContent?.includes("Definir metas"))!;
    expect(goalsStart.getAttribute("href")).toBe("/planejamento#metas");
    await act(async () => (goalsStart as HTMLAnchorElement).click());
    expect(open).toHaveBeenLastCalledWith("planning");
    expect(window.sessionStorage.getItem("mugo:planning:goals")).toBe("1");
    window.sessionStorage.clear();
  });

  it("mantém as ações de Planejar condicionadas às permissões atuais", async () => {
    await act(async () => root.render(<ProcessEntry kind="planning" canView={(route) => route === "goals" || route === "calendar"} canUse={() => false} onOpen={vi.fn()} />));
    expect(host.textContent).not.toContain("Meu planejamento");
    expect(host.textContent).not.toContain("Criar planejamento");
    expect(host.textContent).toContain("Definir metas");
    // Sem acesso ao Planejamento, Definir metas continua indo para a página Metas.
    expect([...host.querySelectorAll("a.planningStartCard")].find((item) => item.textContent?.includes("Definir metas"))!.getAttribute("href")).toBe("/metas");
    expect(host.textContent).toContain("Metas");
    expect(host.textContent).toContain("Calendário");
    expect(host.textContent).not.toContain("Matriz Tática de Conteúdo");
  });

  it("preserva o markup existente dos outros processos", async () => {
    await act(async () => root.render(<ProcessEntry kind="content" canView={() => true} canUse={() => true} onOpen={vi.fn()} />));
    expect(host.querySelector(".planningEntryPage")).toBeNull();
    expect(host.querySelector(".processToolGrid")).not.toBeNull();
    expect(host.textContent).toContain("Social Media");
  });

  it("não confunde acesso somente ao Calendário com acesso à Matriz ou Social Media", async () => {
    const calendarOnlyCanView = (route: AppRoute) => route === "campaigns" || route === "calendar";
    const calendarOnlyCanUse = (permission: string) => permission === "calendar.view";
    await act(async () => root.render(<ProcessEntry kind="planning" canView={calendarOnlyCanView} canUse={calendarOnlyCanUse} onOpen={vi.fn()} />));
    expect(host.textContent).toContain("Calendário");
    expect(host.textContent).not.toContain("Matriz Tática de Conteúdo");
    await act(async () => root.render(<ProcessEntry kind="content" canView={calendarOnlyCanView} canUse={calendarOnlyCanUse} onOpen={vi.fn()} />));
    expect(host.textContent).not.toContain("Social Media");
  });

  it("as seis páginas usam somente links para ferramentas reais", async () => {
    const expected: Record<ProcessKind, AppRoute[]> = {
      planning: ["radar", "benchmark", "planning", "goals", "campaigns", "calendar"],
      content: ["briefing", "campaigns", "redacao", "creators", "production", "clipping"],
      campaign: ["media", "meta", "google"],
      relationship: ["email_marketing", "capture", "engagement", "whatsapp", "whatsapp", "whatsapp"],
      analysis: ["origins", "ecommerce", "customers", "social_report", "brand_health", "ai_actions"],
      social: ["meta", "tiktok", "pinterest", "linkedin"],
    };
    for (const kind of Object.keys(expected) as ProcessKind[]) {
      await act(async () => root.render(<ProcessEntry kind={kind} canView={() => true} canUse={() => true} onOpen={vi.fn()} />));
      const hrefs = [...host.querySelectorAll<HTMLAnchorElement>(".processToolCard, .planningToolCard")].map((item) => item.getAttribute("href"));
      expect(hrefs.length).toBeGreaterThanOrEqual(expected[kind].length);
      expect(hrefs.every((href) => Boolean(href) && href !== "/404")).toBe(true);
      if (kind === "social") expect(hrefs).toContain("/meta");
    }
  });

  it("Lançar campanha: Mídia On, Meta e Google", async () => {
    await act(async () => root.render(<ProcessEntry kind="campaign" canView={() => true} canUse={() => true} onOpen={vi.fn()} />));
    expect([...host.querySelectorAll(".processToolCard strong")].map((c) => c.textContent)).toEqual(["Mídia On", "Meta", "Google"]);
    for (const gone of ["Aprovação Interna", "Aprovação Final", "E-mail Marketing", "Disparos em massa"]) expect(host.textContent).not.toContain(gone);
  });

  it("Criar conteúdo: Briefing, Social Media, Redação, Criadores, Eventos e Clipping, nesta ordem", async () => {
    const open = vi.fn();
    await act(async () => root.render(<ProcessEntry kind="content" canView={() => true} canUse={() => true} onOpen={open} />));
    expect([...host.querySelectorAll(".processToolCard strong")].map((c) => c.textContent)).toEqual(["Briefing", "Social Media", "Redação", "Criadores", "Eventos", "Clipping"]);
    expect(host.textContent).not.toContain("E-mail Marketing");
    const creators = [...host.querySelectorAll("a")].find((item) => item.textContent?.includes("Criadores"))!;
    await act(async () => creators.click());
    expect(open).toHaveBeenCalledWith("creators");
  });

  it("Relacionamento: e-mail, captação, comentários e atalhos do WhatsApp, respeitando permissões", async () => {
    const open = vi.fn();
    await act(async () => root.render(<ProcessEntry kind="relationship" canView={() => true} canUse={() => true} onOpen={open} />));
    expect([...host.querySelectorAll(".processToolCard strong")].map((c) => c.textContent)).toEqual(
      ["E-mail Marketing", "Captação", "Comentários", "Disparos em massa", "Modelos de campanha", "WhatsApp"]);
    const bulk = [...host.querySelectorAll<HTMLAnchorElement>("a")].find((a) => a.textContent?.includes("Disparos em massa"))!;
    expect(bulk.getAttribute("href")).toBe("/whatsapp?area=bulk");
    await act(async () => bulk.click());
    expect(open).toHaveBeenCalledWith("whatsapp");
    expect(window.sessionStorage.getItem("mugo:whatsapp:area")).toBe("bulk");
    window.sessionStorage.clear();
    await act(async () => root.render(<ProcessEntry kind="relationship" canView={(route) => route === "engagement"} canUse={() => true} onOpen={open} />));
    expect(host.textContent).toContain("Comentários");
    expect(host.textContent).not.toContain("Disparos em massa");  // sem WhatsApp, sem atalho
  });

  it("CRM e Redes sociais: cada ferramenta em um lugar só", async () => {
    await act(async () => root.render(<ProcessEntry kind="analysis" canView={() => true} canUse={() => true} onOpen={vi.fn()} />));
    expect([...host.querySelectorAll(".processToolCard strong")].map((c) => c.textContent)).toEqual(
      ["Vendas", "E-commerce", "Clientes", "Relatórios", "Saúde da Marca", "O que a IA fez"]);
    for (const gone of ["Comentários", "Clipping", "Tira-dúvidas", "Meta", "Dashboard"]) expect(host.textContent).not.toContain(gone);
    await act(async () => root.render(<ProcessEntry kind="social" canView={(route) => route !== "tiktok"} canUse={() => true} onOpen={vi.fn()} />));
    expect([...host.querySelectorAll(".processToolCard strong")].map((c) => c.textContent)).toEqual(["Instagram e Facebook", "Pinterest", "LinkedIn"]);
  });
});
