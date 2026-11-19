// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

const m = vi.hoisted(() => ({ list: vi.fn(), bring: vi.fn() }));
vi.mock("../../app/metaAds", () => ({ readMetaCampaigns: m.list, importMetaCampaign: m.bring }));
import MetaImportCampaign from "./MetaImportCampaign";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
afterEach(() => { host?.remove(); vi.clearAllMocks(); });

describe("Puxar campanha da Meta", () => {
  it("lista as campanhas da conta e traz a escolhida", async () => {
    m.list.mockResolvedValue({ campaigns: [
      { id: "120234", name: "BlackFriday_Roove_Leads · Criada pelo Mugoverso", objective: "OUTCOME_LEADS", status: "PAUSED", daily_budget: 20, created_time: null, imported: false },
      { id: "999999", name: "ROOVE | META | ENGAGEMENT", objective: "OUTCOME_ENGAGEMENT", status: "ACTIVE", daily_budget: 6, created_time: null, imported: true }] });
    m.bring.mockResolvedValue({ draft: { id: "d1", payload: { name: "BlackFriday_Roove_Leads" } } });
    const onImported = vi.fn();
    host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => createRoot(host).render(<MetaImportCampaign onImported={onImported} onClose={() => undefined} />));
    await act(async () => {});
    expect(host.textContent).toContain("Já na Mídia On");
    await act(async () => ([...host.querySelectorAll("button")].find((b) => b.textContent === "Trazer") as HTMLButtonElement).click());
    expect(m.bring).toHaveBeenCalledWith("120234");
    expect(onImported).toHaveBeenCalled();
    expect(host.querySelectorAll(".metaImportDone").length).toBe(2);
  });
});
