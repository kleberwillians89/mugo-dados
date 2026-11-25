// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ listSheetContacts: vi.fn() }));
vi.mock("../../app/whatsapp", () => api);
import SheetRecipientsPicker from "./SheetRecipientsPicker";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const wait = () => act(async () => { await new Promise((r) => setTimeout(r, 300)); });

describe("quem recebe o disparo da planilha", () => {
  it("todos por padrão; escolher à mão lista os contatos com telefone mascarado", async () => {
    api.listSheetContacts.mockResolvedValue({ ok: true, total: 120, matches: 2, truncated: false,
      contacts: [{ id: "a".repeat(64), name: "Ana", phone: "+55 21 9••••-7777" }, { id: "b".repeat(64), name: "Kleber", phone: "+55 11 9••••-8888" }] });
    const onChange = vi.fn();
    await act(async () => root.render(<SheetRecipientsPicker picked={null} onChange={onChange} />));
    expect(host.textContent).toContain("Todos da planilha");
    expect(api.listSheetContacts).not.toHaveBeenCalled();
    await act(async () => root.render(<SheetRecipientsPicker picked={[]} onChange={onChange} />));
    await wait();
    expect(host.textContent).toContain("+55 11 9••••-8888");
    expect(host.textContent).toContain("0 escolhido(s) de 120");
    const kleber = [...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')].find((c) => c.parentElement?.textContent?.includes("Kleber"))!;
    await act(async () => kleber.click());
    expect(onChange).toHaveBeenLastCalledWith(["b".repeat(64)]);
  });
});
