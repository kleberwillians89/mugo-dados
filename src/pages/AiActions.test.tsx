// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AI_ACTIONS_FIXTURE } from "./aiActions.fixture";

const api = vi.hoisted(() => ({ listAiActions: vi.fn(), generateAiActions: vi.fn(), decideAiAction: vi.fn() }));
const client = vi.hoisted(() => ({ role: "client_admin" }));
vi.mock("../app/aiActions", async (orig) => ({ ...(await orig<object>()), ...api }));
vi.mock("../app/activeClient", async (orig) => ({ ...(await orig<object>()), getActiveClient: () => ({ id: "roove", role: client.role }), getActiveClientName: () => "Roove" }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
const AiActions = (await import("./AiActions")).default;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
const button = (text: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.includes(text))!;
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

describe("Ações da IA", () => {
  beforeEach(() => {
    host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
    Object.values(api).forEach((fn) => fn.mockReset()); client.role = "client_admin";
    api.listAiActions.mockResolvedValue({ actions: AI_ACTIONS_FIXTURE });
  });
  afterEach(() => { act(() => root.unmount()); host.remove(); });

  it("lista propostas com evidência e o histórico com resultado", async () => {
    await act(async () => { root.render(<AiActions />); });
    await flush();
    expect(host.querySelectorAll(".aiCard.is-open")).toHaveLength(3);
    expect(host.textContent).toContain("Clientes sem comprar (com consentimento)");
    expect(host.textContent).toContain("a coleção de verão chegou");
    expect(host.textContent).toContain("31 compraram");
  });

  it("aprovar executa e atualiza o cartão", async () => {
    api.decideAiAction.mockResolvedValue({ action: { ...AI_ACTIONS_FIXTURE[1], status: "executada", measurement: null } });
    await act(async () => { root.render(<AiActions />); });
    await flush();
    const approve = [...host.querySelectorAll(".aiCard.is-open")][1].querySelector<HTMLButtonElement>(".is-primary")!;
    await act(async () => { approve.click(); });
    expect(api.decideAiAction).toHaveBeenCalledWith("a2", "aprovar");
    expect(host.textContent).toContain("Aprovada e executada.");
    expect(host.querySelectorAll(".aiCard.is-open")).toHaveLength(2);
  });

  it("viewer não vê botões de decisão nem de analisar", async () => {
    client.role = "client_viewer";
    await act(async () => { root.render(<AiActions />); });
    await flush();
    expect(button("Analisar agora")).toBeUndefined();
    expect(button("Aprovar")).toBeUndefined();
    expect(host.textContent).toContain("Só a equipe Mugô ou o admin da marca aprova.");
  });
});
