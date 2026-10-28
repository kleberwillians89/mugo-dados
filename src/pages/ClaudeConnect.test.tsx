// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ClaudeConnect, { ClaudeConnectContent } from "./ClaudeConnect";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const api = vi.hoisted(() => ({ http: vi.fn() }));
vi.mock("../app/api", () => ({ http: api.http, setApiAccessToken: vi.fn() }));
vi.mock("../app/supabase", () => ({ supabase: null }));
vi.mock("./Login", () => ({ default: () => <p>Entrar</p> }));

const overview = { url: "https://api.example.test/mcp", application: "Aplicativo de teste", companies: [{ id: "company-a", name: "Empresa A" }],
  connections: [{ id: "connection-a", name: "Claude", created_at: "2026-10-01T12:00:00Z", last_used_at: null }] };
let container: HTMLDivElement;
let root: Root;
async function render(consent = false) { await act(async () => root.render(<ClaudeConnectContent consent={consent} />)); }
async function click(label: string) {
  const button = Array.from(container.querySelectorAll("button")).find((element) => element.textContent === label);
  expect(button).toBeTruthy();
  await act(async () => button!.click());
}
beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/conectar-claude");
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  api.http.mockResolvedValue(overview);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

describe("Conexão MCP com o Claude", () => {
  it("exige login real antes de ler conexões", async () => {
    await act(async () => root.render(<ClaudeConnect />));
    expect(container.textContent).toContain("Entrar");
    expect(api.http).not.toHaveBeenCalled();
  });
  it("mostra URL, privacidade e conexões e revoga apenas a conexão escolhida", async () => {
    await render();
    expect(container.textContent).toContain("Nenhum dado pessoal de comprador é compartilhado");
    expect(container.textContent).toContain(overview.url);
    await click("Revogar");
    expect(api.http).toHaveBeenLastCalledWith("/api/mcp/connections/revoke", { method: "POST", body: JSON.stringify({ id: "connection-a" }) });
    expect(container.textContent).toContain("Nenhuma conexão ativa");
  });
  it("exibe estado de carregamento e erro compreensível", async () => {
    api.http.mockImplementationOnce(() => new Promise(() => {}));
    await render(); expect(container.querySelector('[role="status"]')).toBeTruthy();
    await act(async () => root.unmount()); root = createRoot(container);
    api.http.mockRejectedValueOnce(new Error("erro interno"));
    await render();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Não foi possível carregar");
    expect(container.textContent).not.toContain("erro interno");
  });
  it("mostra empresas antes da autorização e nunca autoriza automaticamente", async () => {
    window.history.replaceState({}, "", "/conectar-claude/autorizar?client_id=oauth-a&state=opaque-state");
    await render(true);
    expect(api.http).toHaveBeenCalledTimes(1);
    expect(api.http.mock.calls[0][0]).toBe("/api/mcp/authorization?client_id=oauth-a&state=opaque-state");
    expect(container.textContent).toContain("Empresa A");
    api.http.mockRejectedValueOnce(new Error("falha"));
    await click("Autorizar");
    expect(api.http.mock.calls[1]).toEqual(["/api/mcp/consent", { method: "POST", body: JSON.stringify({ client_id: "oauth-a", state: "opaque-state", approve: true, company_ids: ["company-a"] }) }]);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Não foi possível concluir");
    expect(container.textContent).toContain("Empresa A");
  });
  it("com várias empresas, autoriza somente as marcadas", async () => {
    api.http.mockResolvedValueOnce({ ...overview, companies: [{ id: "company-a", name: "Empresa A" }, { id: "company-b", name: "Empresa B" }] });
    await render(true);
    const authorize = Array.from(container.querySelectorAll("button")).find((element) => element.textContent === "Autorizar");
    expect(authorize?.disabled).toBe(true);
    const boxes = Array.from(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'));
    expect(boxes.map((box) => box.checked)).toEqual([false, false]);
    await act(async () => boxes[1].click());
    api.http.mockRejectedValueOnce(new Error("falha"));
    await click("Autorizar");
    expect(JSON.parse(api.http.mock.calls[1][1].body).company_ids).toEqual(["company-b"]);
  });
  it("mostra as empresas de cada conexão ativa", async () => {
    api.http.mockResolvedValueOnce({ ...overview, connections: [{ ...overview.connections[0], companies: ["Empresa A"] }] });
    await render();
    expect(container.textContent).toContain("Empresas: Empresa A");
  });
  it("cancela explicitamente sem aprovar", async () => {
    await render(true);
    api.http.mockRejectedValueOnce(new Error("falha"));
    await click("Cancelar");
    expect(JSON.parse(api.http.mock.calls[1][1].body).approve).toBe(false);
  });
  it("cancela a leitura ao desmontar", async () => {
    api.http.mockImplementationOnce(() => new Promise(() => {}));
    await render();
    const signal = api.http.mock.calls[0][1].signal as AbortSignal;
    await act(async () => root.unmount());
    expect(signal.aborted).toBe(true);
    root = createRoot(container);
  });
});
