// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

const { resolveCreator, searchPeople } = vi.hoisted(() => ({ resolveCreator: vi.fn(async () => ({
  saved: [{ id: "1", network: "instagram", handle: "ana.treino", display_name: "Ana Treino", avatar_url: "https://x/a.jpg", followers: 84200 }],
  exact: null,
})), searchPeople: vi.fn(async () => ({ query: "ana", people: [{ network: "instagram", handle: "ana.fit", display_name: "Ana Fit", avatar_url: null, followers: 1200, verified: true }] })) }));
vi.mock("../../app/creators", async (orig) => ({ ...(await orig<typeof import("../../app/creators")>()), resolveCreator, searchPeople }));
import CreatorFinder from "./CreatorFinder";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
afterEach(() => { host?.remove(); vi.clearAllMocks(); vi.useRealTimers(); });

async function type(input: HTMLInputElement, value: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  await act(async () => { set.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  await act(async () => { vi.advanceTimersByTime(400); });
  await act(async () => {});
}

describe("Analisar perfil com sugestões", () => {
  it("mostra quem já está salvo com foto, procura pelo nome e analisa o @ escolhido", async () => {
    vi.useFakeTimers();
    const onPick = vi.fn();
    host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { createRoot(host).render(<CreatorFinder network="instagram" isAgency busy={false} onPick={onPick} />); });
    const input = host.querySelector("input") as HTMLInputElement;
    await act(async () => { input.focus(); });
    await type(input, "ana");
    expect(resolveCreator).toHaveBeenCalledWith("instagram", "ana");
    expect(host.textContent).toContain("@ana.treino");
    expect(host.querySelector(".creatorFinderPop img")?.getAttribute("src")).toBe("https://x/a.jpg");
    const opts = () => [...host.querySelectorAll('[role="option"]')] as HTMLElement[];
    await act(async () => { opts().find((o) => o.textContent?.includes("pelo nome"))!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true })); });
    await act(async () => {});
    expect(searchPeople).toHaveBeenCalledWith("ana");
    expect(host.textContent).toContain("@ana.fit");
    await act(async () => { opts().find((o) => o.textContent?.includes("@ana.fit"))!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true })); });
    expect(onPick).toHaveBeenCalledWith("ana.fit");
  });

  it("cliente (não agência) não vê a busca paga por nome", async () => {
    vi.useFakeTimers();
    host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { createRoot(host).render(<CreatorFinder network="instagram" isAgency={false} busy={false} onPick={() => undefined} />); });
    const input = host.querySelector("input") as HTMLInputElement;
    await act(async () => { input.focus(); });
    await type(input, "ana");
    expect(host.textContent).not.toContain("pelo nome");
  });
});
