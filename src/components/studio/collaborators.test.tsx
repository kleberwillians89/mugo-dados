// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Collaborators, { cleanHandle } from "./Collaborators";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); });

describe("Collaborators", () => {
  it("limpa o @ e aceita link do perfil", () => {
    expect(cleanHandle("@M2CommunityRun")).toBe("m2communityrun");
    expect(cleanHandle("https://www.instagram.com/roove.oficial/")).toBe("roove.oficial");
    expect(cleanHandle("nome com espaço")).toBeNull();
  });

  it("marca até 3 e avisa no Stories", async () => {
    const onChange = vi.fn();
    await act(async () => { root.render(<Collaborators value={["a", "b"]} onChange={onChange} />); });
    const input = host.querySelector("input")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "@c @d");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { [...host.querySelectorAll("button")].find((b) => b.textContent === "Marcar")!.click(); });
    expect(onChange).not.toHaveBeenCalled();
    expect(host.textContent).toContain("no máximo 3");
    await act(async () => { root.render(<Collaborators value={["m2communityrun"]} onChange={onChange} isStory />); });
    expect(host.textContent).toContain("Stories não aceitam colaborador");
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="Tirar @m2communityrun"]')!.click(); });
    expect(onChange).toHaveBeenCalledWith([]);
  });
});
