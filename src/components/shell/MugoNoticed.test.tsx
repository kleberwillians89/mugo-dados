// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

const m = vi.hoisted(() => ({ list: vi.fn(), dismiss: vi.fn(), remind: vi.fn() }));
vi.mock("../../app/notices", () => ({ listNotices: m.list, dismissNotice: m.dismiss, remindClient: m.remind }));
import MugoNoticed from "./MugoNoticed";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
afterEach(() => { host?.remove(); vi.clearAllMocks(); vi.restoreAllMocks(); });
const NOTICES = [
  { id: "roove|custo_subindo:c1", client_id: "roove", client_name: "Roove", kind: "custo_subindo", icon: "⚠️", level: 1, urgency: 80, since: null,
    message: "Campanha \"Black Roove – Vendas\" está com o custo por compra subindo há 3 dias (R$ 42 → R$ 61).",
    actions: [{ label: "Ver campanha", route: "media" }] },
  { id: "ruah|aprovacao_parada:cliente", client_id: "ruah", client_name: "Ruah", kind: "aprovacao_parada", icon: "⏰", level: 4, urgency: 70, since: null,
    message: "4 posts esperam aprovação do cliente há mais de 48h.",
    actions: [{ label: "Ir para Aprovação Final", route: "final_approval" }, { label: "Cobrar o cliente no WhatsApp", kind: "remind", request_id: "r1", contact_id: "k1" }] },
];
async function render(onOpen = vi.fn()) {
  host = document.createElement("div"); document.body.appendChild(host);
  await act(async () => createRoot(host).render(<MugoNoticed onOpen={onOpen} />));
  await act(async () => {});
  return onOpen;
}
const button = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === label) as HTMLButtonElement;

describe("A Mugô IA notou", () => {
  it("mostra os alertas com a empresa e abre a tela certa na empresa do alerta", async () => {
    m.list.mockResolvedValue({ notices: NOTICES, total: 2 });
    const onOpen = await render();
    expect(host.textContent).toContain("A Mugô IA notou");
    expect(host.textContent).toContain("Roove");
    await act(async () => button("Ir para Aprovação Final").click());
    expect(onOpen).toHaveBeenCalledWith("ruah", "final_approval");
  });

  it("inicia recolhido e reabre os avisos sem dispensá-los", async () => {
    m.list.mockResolvedValue({ notices: NOTICES, total: 2 });
    await render();
    const toggle = host.querySelector<HTMLButtonElement>(".mugoNoticedToggle")!;
    const list = host.querySelector("ul")!;
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.textContent).toContain("2 avisos");
    expect(list.hidden).toBe(true);
    expect(m.dismiss).not.toHaveBeenCalled();
    await act(async () => toggle.click());
    expect(list.hidden).toBe(false);
    expect(list.children).toHaveLength(2);
  });

  it("sinaliza um alerta crítico sem abrir o painel", async () => {
    m.list.mockResolvedValue({ notices: [{ ...NOTICES[0], critical: true }], total: 1 });
    await render();
    expect(host.querySelector(".mugoNoticedCritical")?.textContent).toBe("Alerta crítico");
    expect(host.querySelector("ul")?.hidden).toBe(true);
  });

  it("registra conclusão explicitamente e retira o aviso da lista", async () => {
    m.list.mockResolvedValue({ notices: [NOTICES[0]], total: 1 });
    m.dismiss.mockResolvedValue({ ok: true });
    await render();
    await act(async () => button("Marcar como feito").click());
    expect(m.dismiss).toHaveBeenCalledWith(NOTICES[0].id, true);
    expect(host.querySelector("li")).toBeNull();
    expect(host.textContent).toContain("Aviso marcado como feito.");
  });

  it("cobra o cliente só depois de confirmar e dispensa tirando da lista", async () => {
    m.list.mockResolvedValue({ notices: NOTICES, total: 2 });
    m.remind.mockResolvedValue({ ok: true }); m.dismiss.mockResolvedValue({ ok: true });
    await render();
    vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    await act(async () => button("Cobrar o cliente no WhatsApp").click());
    expect(m.remind).not.toHaveBeenCalled();
    await act(async () => button("Cobrar o cliente no WhatsApp").click());
    expect(m.remind).toHaveBeenCalledWith("ruah", "r1", "k1");
    expect(host.textContent).toContain("Lembrete enviado");
    await act(async () => button("Dispensar").click());
    expect(m.dismiss).toHaveBeenCalledWith("roove|custo_subindo:c1");
    expect(host.textContent).not.toContain("Black Roove");
  });

  it("sem nada relevante (ou sem a tabela ainda), o quadro não aparece", async () => {
    m.list.mockResolvedValue({ notices: [], total: 0, unavailable: true });
    await render();
    expect(host.innerHTML).toBe("");
  });
});
