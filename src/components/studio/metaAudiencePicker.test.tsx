// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AdPayload } from "../../app/metaAds";
import { accountAudienceText } from "./metaCampaignWizard";

vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => "roove" }));
const list = vi.fn();
vi.mock("../../app/metaAds", () => ({ listAdAudiences: () => list() }));
import MetaAudiencePicker from "./MetaAudiencePicker";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); });

const AUD: AdPayload["audience"] = { age_min: 25, age_max: 45, gender: "todos", regions: [], interests: [], advantage: true };
const DATA = {
  account: "act_1",
  saved: [{ id: "9001", name: "Mulheres SP", kind: "SAVED", kind_label: "Público salvo", size: "800 mil pessoas", ready: true, status: "" }],
  custom: [
    { id: "1001", name: "Semelhante compradores 1%", kind: "LOOKALIKE", kind_label: "Semelhante", size: "1,5 mi a 1,8 mi pessoas", ready: true, status: "" },
    { id: "1002", name: "Lista pequena", kind: "CUSTOM", kind_label: "Lista de clientes", size: "menos de 1 mil pessoas", ready: false, status: "Público pequeno demais" },
  ],
};

describe("MetaAudiencePicker", () => {
  it("lista os públicos da conta e devolve a escolha", async () => {
    list.mockResolvedValue(DATA);
    const onChange = vi.fn();
    await act(async () => { root.render(<MetaAudiencePicker audience={AUD} onChange={onChange} />); });
    expect(host.textContent).toContain("Semelhante compradores 1%");
    expect(host.textContent).toContain("Público pequeno demais");

    const select = host.querySelector("select")!;
    await act(async () => { select.value = "9001"; select.dispatchEvent(new Event("change", { bubbles: true })); });
    expect(onChange).toHaveBeenLastCalledWith({ saved_audience: { id: "9001", name: "Mulheres SP" } });

    const boxes = [...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')];
    expect(boxes[2].disabled).toBe(true); // público que o Meta não entrega não pode ser incluído
    await act(async () => { boxes[0].click(); });
    expect(onChange).toHaveBeenLastCalledWith({ custom_audiences: [{ id: "1001", name: "Semelhante compradores 1%" }], excluded_audiences: [] });
  });

  it("incluir e excluir o mesmo público não convivem", async () => {
    list.mockResolvedValue(DATA);
    const onChange = vi.fn();
    const aud = { ...AUD, custom_audiences: [{ id: "1001", name: "Semelhante compradores 1%" }] };
    await act(async () => { root.render(<MetaAudiencePicker audience={aud} onChange={onChange} />); });
    const exclude = [...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')][1];
    await act(async () => { exclude.click(); });
    expect(onChange).toHaveBeenLastCalledWith({ custom_audiences: [], excluded_audiences: [{ id: "1001", name: "Semelhante compradores 1%" }] });
  });

  it("resume a escolha para a revisão", () => {
    expect(accountAudienceText({ ...AUD, saved_audience: { id: "9", name: "Mulheres SP" },
      custom_audiences: [{ id: "1", name: "Semelhante 1%" }], excluded_audiences: [{ id: "2", name: "Clientes" }] }))
      .toBe("Público salvo: Mulheres SP · Inclui: Semelhante 1% · Exclui: Clientes");
    expect(accountAudienceText(AUD)).toBe("");
  });
});
