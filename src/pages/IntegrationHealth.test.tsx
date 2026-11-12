// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CENTER_FIXTURE } from "./integrationHealth.fixture";

const api = vi.hoisted(() => ({ getIntegrationCenter: vi.fn() }));
vi.mock("../app/integrationCenter", async (orig) => ({ ...(await orig<typeof import("../app/integrationCenter")>()), ...api }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: unknown }) => children }));
import IntegrationHealth from "./IntegrationHealth";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
afterEach(() => { host?.remove(); vi.clearAllMocks(); });
const btn = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.includes(label)) as HTMLButtonElement;

describe("Saúde das integrações", () => {
  it("mostra só o que pede ação, com o que fazer, e abre a empresa certa", async () => {
    api.getIntegrationCenter.mockResolvedValue(CENTER_FIXTURE);
    const onOpen = vi.fn();
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => { root.render(<IntegrationHealth onOpen={onOpen} />); });
    const cards = [...host.querySelectorAll(".ihCard h2")].map((h) => h.textContent);
    expect(cards).toEqual(["Roove", "Ruah"]); // Curavino em dia fica fora do filtro
    expect(host.textContent).toContain("Reconectar em Integrações");
    expect(host.querySelector(".ihKpis")?.textContent).toContain("1com erro ou reconexão");
    await act(async () => { btn("Todas").click(); });
    expect(host.querySelectorAll(".ihCard").length).toBe(3);
    await act(async () => { (host.querySelector(".ihCard header button") as HTMLButtonElement).click(); });
    expect(onOpen).toHaveBeenCalledWith("roove", "integrations");
    act(() => root.unmount());
  });
});
