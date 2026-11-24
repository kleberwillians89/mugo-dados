// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { requestNewProject, takeNewProjectRequest } from "./newProjectRequest";

afterEach(() => { window.sessionStorage.clear(); window.history.replaceState(null, "", "/"); });

describe("Criar planejamento abre o formulário direto", () => {
  it("o clique em Criar planejamento pede o formulário uma vez só", () => {
    requestNewProject("planejamento");
    expect(takeNewProjectRequest("evento")).toBe(false);       // outro tipo não abre
    expect(takeNewProjectRequest("planejamento")).toBe(true);
    expect(takeNewProjectRequest("planejamento")).toBe(false); // recarregar não reabre
  });

  it("o link com ?novo=1 (nova aba) também abre, e o parâmetro sai da URL", () => {
    window.history.replaceState(null, "", "/planejamento?novo=1&x=2#a");
    expect(takeNewProjectRequest("planejamento")).toBe(true);
    expect(window.location.pathname + window.location.search + window.location.hash).toBe("/planejamento?x=2#a");
  });

  it("sem pedido, abre a lista normal", () => {
    window.history.replaceState(null, "", "/planejamento");
    expect(takeNewProjectRequest("planejamento")).toBe(false);
  });
});
