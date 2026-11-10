// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ArtFiles from "./ArtFiles";
import { moveArt } from "./artFiles.helpers";
import { getPathForRoute, getAppRouteFromPath } from "../../app/routes";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); });
const A = "https://x.supabase.co/storage/v1/object/public/ig-media/studio-art/m2/nova/a.jpg";
const B = "https://x.supabase.co/storage/v1/object/public/ig-media/studio-art/m2/nova/b.jpg";
const V = "https://x.supabase.co/storage/v1/object/public/ig-media/studio-art/m2/nova/c.mp4";

describe("ArtFiles", () => {
  it("move dentro dos limites", () => {
    expect(moveArt([A, B, V], 0, 1)).toEqual([B, A, V]);
    expect(moveArt([A, B, V], 0, -1)).toEqual([A, B, V]);
    expect(moveArt([A, B, V], 2, 1)).toEqual([A, B, V]);
  });

  it("mostra cada arte em ordem e tira a escolhida", async () => {
    const onChange = vi.fn();
    await act(async () => { root.render(<ArtFiles value={[A, B, V].join("\n")} onChange={onChange} />); });
    expect(host.querySelectorAll(".artFile")).toHaveLength(3);
    expect(host.textContent).toContain("Vídeo");
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="Tirar arte 2"]')!.click(); });
    expect(onChange).toHaveBeenCalledWith([A, V].join("\n"));
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="Mover arte 3 para a esquerda"]')!.click(); });
    expect(onChange).toHaveBeenLastCalledWith([A, V, B].join("\n"));
  });

  it("IA da marca tem endereço próprio", () => {
    expect(getAppRouteFromPath("/ia-da-marca")).toBe("brand_ai");
    expect(getPathForRoute("brand_ai")).toBe("/ia-da-marca");
  });
});
