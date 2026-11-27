// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

const m = vi.hoisted(() => ({ read: vi.fn(), change: vi.fn() }));
vi.mock("../../app/metaAds", () => ({ readAdPixels: m.read, changeAdPixel: m.change }));
import MetaPixelSwitch from "./MetaPixelSwitch";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
afterEach(() => { host?.remove(); vi.clearAllMocks(); });
const pixels = [{ id: "111", name: "https://roove.com.br", last_fired_time: null, active: false, unavailable: false },
  { id: "222", name: "Roove Web Official", last_fired_time: new Date().toISOString(), active: true, unavailable: false }];

describe("Trocar pixel da campanha", () => {
  it("avisa o pixel sem eventos, sugere o recomendado e troca", async () => {
    m.read.mockResolvedValue({ current: "111", recommended: "222", pixels });
    m.change.mockResolvedValue({ current: "222", recommended: "222", pixels, ads_not_updated: 0 });
    host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => createRoot(host).render(<MetaPixelSwitch draftId="d1" />));
    await act(async () => {});
    expect(host.textContent).toContain("não recebe eventos");
    expect((host.querySelector("select") as HTMLSelectElement).value).toBe("222");
    await act(async () => ([...host.querySelectorAll("button")].find((b) => b.textContent === "Trocar pixel") as HTMLButtonElement).click());
    expect(m.change).toHaveBeenCalledWith("d1", "222");
    expect(host.textContent).toContain("Pixel trocado para Roove Web Official");
  });
});
