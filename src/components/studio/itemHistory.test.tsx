// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const studio = vi.hoisted(() => ({ getItemHistory: vi.fn() }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...studio }));
import ItemHistory from "./ItemHistory";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

describe("ItemHistory", () => {
  it("mostra quem fez o quê, com o cliente e o sistema diferenciados", async () => {
    studio.getItemHistory.mockResolvedValue({ events: [
      { id: "3", action: "publicou no Instagram", actor_name: "Publicação automática", actor_side: "sistema", detail: null, created_at: new Date().toISOString() },
      { id: "2", action: "pediu ajuste", actor_name: "Elis", actor_side: "cliente", detail: "Trocar a foto", created_at: new Date().toISOString() },
      { id: "1", action: "criou a pauta", actor_name: "Duda", actor_side: "mugo", detail: null, created_at: new Date().toISOString() }] });
    await act(async () => { root.render(<ItemHistory itemId="i1" />); });
    await act(async () => {});
    expect(host.textContent).toContain("Histórico 3");
    expect(host.textContent).toContain("Duda criou a pauta");
    expect(host.textContent).toContain("Elis pediu ajuste");
    expect(host.textContent).toContain("Trocar a foto");
    expect(host.querySelector("li.is-sistema")).not.toBeNull();
  });
});
