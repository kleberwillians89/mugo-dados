// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PendingInvitation } from "../app/api";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Mesmo contrato da rota real: erro HTTP com status e mensagem amigável do backend.
const api = vi.hoisted(() => {
  class ApiError extends Error {
    status: number;
    code: string;
    constructor(message: string, options: { status: number; code?: string }) {
      super(message);
      this.status = options.status;
      this.code = options.code || `HTTP_${options.status}`;
    }
  }
  return { ApiError, acceptInvitation: vi.fn() };
});
vi.mock("../app/api", () => api);

import AcceptInvitation from "./AcceptInvitation";

const origami: PendingInvitation = {
  id: "inv-origami", client_id: "origami", role: "client_admin", company_name: "Origami", expires_at: "2026-10-12T15:00:00Z",
};
const roove: PendingInvitation = {
  id: "inv-roove", client_id: "roove", role: "viewer", company_name: "Roove", expires_at: "2026-10-20T15:00:00Z",
};

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const onAccepted = vi.fn();
const onSkip = vi.fn();
const onLogout = vi.fn();

async function render(invitations: PendingInvitation[]) {
  await act(async () => {
    root.render(<AcceptInvitation invitations={invitations} onAccepted={onAccepted} onSkip={onSkip} onLogout={onLogout} />);
  });
}

function button(text: string) {
  return [...container.querySelectorAll("button")].find((item) => item.textContent === text);
}

async function click(target: HTMLElement | undefined) {
  await act(async () => {
    target?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

function title() {
  return container.querySelector("#invite-title")?.textContent || "";
}

beforeEach(() => {
  vi.clearAllMocks();
  onAccepted.mockResolvedValue(undefined);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("AcceptInvitation — convite válido", () => {
  it("mostra para qual empresa é o convite, com a marca dela, o perfil e o prazo", async () => {
    await render([origami]);
    expect(title()).toContain("Você foi convidado para");
    expect(title()).toContain("Origami");
    expect(container.querySelector('#invite-title img[src="/clients/origami.png"]')).toBeTruthy();
    expect(container.textContent).toContain("Administrador da empresa");
    expect(container.textContent).toContain("Válido até");
    expect(container.textContent).toContain("12/10/2026");
    expect(button("Aceitar convite")).toBeTruthy();
    // Mesma moldura do acesso: produto, sem outras empresas, links legais.
    expect(container.textContent).toContain("Mugô Dados");
    expect(container.textContent).not.toMatch(/Curavino|Roove|Ruah|Latina/);
    expect(container.querySelector('a[href="/privacidade"]')).toBeTruthy();
    expect(container.querySelector('a[href="/termos-de-uso"]')).toBeTruthy();
  });

  it("sem nome real da empresa (fallback do backend), não inventa empresa nem logo", async () => {
    await render([{ ...origami, client_id: "c-123", company_name: "Empresa" }]);
    expect(title()).toBe("Você foi convidado para uma empresa");
    expect(container.querySelector('img[src^="/clients/"]')).toBeNull();
    expect(button("Aceitar convite")).toBeTruthy();
  });
});

describe("AcceptInvitation — aceite preservado", () => {
  it("aceita pelo id do convite e entrega ao App o tenant/papel devolvidos pelo backend", async () => {
    api.acceptInvitation.mockResolvedValue({ ok: true, client_id: "origami", role: "viewer" });
    // App ainda abrindo a empresa: a tela mostra o redirecionamento em andamento.
    onAccepted.mockImplementation(() => new Promise(() => undefined));
    await render([origami]);
    await click(button("Aceitar convite"));
    expect(api.acceptInvitation).toHaveBeenCalledTimes(1);
    expect(api.acceptInvitation).toHaveBeenCalledWith("inv-origami");
    expect(onAccepted).toHaveBeenCalledWith({ clientId: "origami", role: "viewer" });
    expect(title()).toBe("Convite aceito");
    expect(container.querySelector('[role="status"]')?.textContent).toBe("Abrindo Origami…");
    expect(button("Continuar")).toBeUndefined();
  });

  it("carregando: o botão fica ocupado enquanto o backend responde", async () => {
    api.acceptInvitation.mockImplementation(() => new Promise(() => undefined));
    await render([origami]);
    await click(button("Aceitar convite"));
    const busy = button("Aceitando...");
    expect(busy?.disabled).toBe(true);
    expect(busy?.getAttribute("aria-busy")).toBe("true");
    expect(onAccepted).not.toHaveBeenCalled();
  });

  it("vários convites: aceita um por vez e só avisa o App depois do último", async () => {
    api.acceptInvitation
      .mockResolvedValueOnce({ ok: true, client_id: "origami", role: "client_admin" })
      .mockResolvedValueOnce({ ok: true, client_id: "roove", role: "viewer" });
    await render([origami, roove]);
    expect(title()).toBe("Você foi convidado para 2 empresas");
    expect(container.querySelectorAll(".inviteItem")).toHaveLength(2);

    await click(container.querySelector<HTMLButtonElement>('[aria-label="Aceitar convite para Origami"]') || undefined);
    expect(api.acceptInvitation).toHaveBeenLastCalledWith("inv-origami");
    expect(onAccepted).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Convite para Origami aceito.");
    // Restou um convite: volta ao layout de convite único, para a Roove.
    expect(title()).toContain("Roove");

    await click(button("Aceitar convite"));
    expect(api.acceptInvitation).toHaveBeenLastCalledWith("inv-roove");
    expect(onAccepted).toHaveBeenCalledWith({ clientId: "roove", role: "viewer" });
  });

  it("Pular por agora e Sair continuam usando os mesmos callbacks", async () => {
    await render([origami]);
    await click(button("Pular por agora"));
    expect(onSkip).toHaveBeenCalledTimes(1);
    await click(button("Sair"));
    expect(onLogout).toHaveBeenCalledTimes(1);
  });
});

describe("AcceptInvitation — estados de erro devolvidos pelo backend", () => {
  it.each([
    [404, "Convite não encontrado.", "Convite inválido"],
    [409, "Este convite expirou. Peça um novo link à Mugô.", "Convite expirado"],
    [409, "Este convite já foi utilizado.", "Convite indisponível"],
    [403, "Este convite pertence a outro e-mail. Entre com a conta que foi convidada.", "Convite de outra conta"],
    [500, "Não foi possível carregar os dados agora.", "Não foi possível aceitar o convite"],
  ])("HTTP %i: título do estado + mensagem do backend, sem avançar", async (status, message, expectedTitle) => {
    api.acceptInvitation.mockRejectedValue(new api.ApiError(message, { status }));
    await render([origami]);
    await click(button("Aceitar convite"));
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.querySelector("strong")?.textContent).toBe(expectedTitle);
    expect(alert?.textContent).toContain(message);
    expect(alert?.textContent).toContain(`Código para o suporte: HTTP_${status}`);
    expect(onAccepted).not.toHaveBeenCalled();
    // O convite continua disponível para nova tentativa.
    expect(button("Aceitar convite")?.disabled).toBe(false);
  });
});
