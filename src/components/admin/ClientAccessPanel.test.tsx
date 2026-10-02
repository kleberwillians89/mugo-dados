// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const api = vi.hoisted(() => ({
  listClientAccess: vi.fn(),
  createClientAccess: vi.fn(),
  resetClientAccessPassword: vi.fn(),
  removeClientAccess: vi.fn(),
}));

vi.mock("../../app/api", () => api);
vi.mock("../../app/activeClient", () => ({
  getActiveClientId: () => "empresa-a",
  getActiveClientName: () => "Empresa A",
}));

import ClientAccessPanel from "./ClientAccessPanel";

const VIEWER = {
  membership_id: "m-1", user_id: "user-1", email: "pessoa@empresa.com.br", name: "Pessoa Teste",
  role: "viewer", role_label: "Visualizador", is_global_role: false,
  email_confirmed: true, last_sign_in_at: "2026-10-02T13:00:00Z", created_at: "2026-10-01T10:00:00Z",
};
const TEAM = {
  membership_id: "m-2", user_id: "user-2", email: "equipe@mugoagencia.com.br", name: "Equipe",
  role: "agency_admin", role_label: "agency_admin", is_global_role: true,
  email_confirmed: true, last_sign_in_at: null, created_at: "2026-09-01T10:00:00Z",
};

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

const nativeInput = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
const nativeSelect = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, "value")?.set;

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.listClientAccess.mockResolvedValue({ ok: true, client_id: "empresa-a", items: [VIEWER] });
  api.createClientAccess.mockResolvedValue({ ok: true });
  api.resetClientAccessPassword.mockResolvedValue({ ok: true });
  api.removeClientAccess.mockResolvedValue({ ok: true, account_preserved: true, remaining_memberships: 1 });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function render(canManage = true) {
  await act(async () => root.render(<ClientAccessPanel canManage={canManage} />));
  await act(async () => Promise.resolve());
  await act(async () => Promise.resolve());
}

function button(text: string) {
  return [...container.querySelectorAll("button")].find((el) => el.textContent === text) as HTMLButtonElement | undefined;
}

function field(scope: string, label: string) {
  const form = container.querySelector(`[data-testid="${scope}"]`);
  const match = [...(form?.querySelectorAll("label") || [])].find((el) => el.textContent?.startsWith(label));
  return match?.querySelector("input, select") as HTMLInputElement | HTMLSelectElement | undefined;
}

async function type(scope: string, label: string, value: string) {
  const input = field(scope, label);
  if (!input) throw new Error(`Campo não encontrado: ${label}`);
  await act(async () => {
    const setter = input.tagName === "SELECT" ? nativeSelect : nativeInput;
    setter?.call(input, value);
    input.dispatchEvent(new Event(input.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
  });
}

async function click(target: HTMLElement | undefined) {
  await act(async () => target?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
  await act(async () => Promise.resolve());
}

describe("Acessos — listagem", () => {
  it("lista as pessoas da empresa ativa sem enviar client_id", async () => {
    await render();
    expect(api.listClientAccess).toHaveBeenCalledTimes(1);
    const [firstArg] = api.listClientAccess.mock.calls[0];
    expect(JSON.stringify(firstArg ?? {})).not.toContain("empresa-a");
    expect(container.textContent).toContain("Pessoa Teste");
    expect(container.textContent).toContain("Visualizador");
    expect(container.textContent).toContain("Empresa A");
  });

  it("conta da equipe Mugô aparece marcada e sem ações de cliente", async () => {
    api.listClientAccess.mockResolvedValue({ ok: true, client_id: "empresa-a", items: [TEAM] });
    await render();
    expect(container.textContent).toContain("Equipe Mugô");
    expect(button("Redefinir senha")).toBeUndefined();
    expect(button("Remover acesso")).toBeUndefined();
  });

  it("empresa sem acessos mostra estado vazio", async () => {
    api.listClientAccess.mockResolvedValue({ ok: true, client_id: "empresa-a", items: [] });
    await render();
    expect(container.textContent).toContain("Nenhum acesso nesta empresa ainda");
  });

  it("erro de leitura é informado sem derrubar o painel", async () => {
    api.listClientAccess.mockRejectedValue(new Error("Falha na leitura"));
    await render();
    expect(container.querySelector(".companiesError")?.textContent).toContain("Falha na leitura");
    expect(container.querySelector('[data-testid="client-access-panel"]')).not.toBeNull();
  });
});

describe("Acessos — criar", () => {
  it("cria com nome, e-mail, senha e perfil", async () => {
    await render();
    await click(button("Criar acesso"));
    await type("client-access-form", "Nome", "Nova Pessoa");
    await type("client-access-form", "E-mail", "nova@empresa.com.br");
    await type("client-access-form", "Senha inicial", "fixture-senha-nao-real-1");
    await type("client-access-form", "Confirmar senha", "fixture-senha-nao-real-1");
    await type("client-access-form", "Perfil", "client_admin");
    await click([...container.querySelectorAll('[data-testid="client-access-form"] button')].find((el) => el.textContent === "Criar acesso") as HTMLElement);
    expect(api.createClientAccess).toHaveBeenCalledWith({
      name: "Nova Pessoa", email: "nova@empresa.com.br",
      password: "fixture-senha-nao-real-1", password_confirmation: "fixture-senha-nao-real-1",
      role: "client_admin",
    });
    expect(container.textContent).toContain("Acesso criado");
    // Recarrega a lista depois de criar.
    expect(api.listClientAccess).toHaveBeenCalledTimes(2);
  });

  it("só oferece perfis de cliente, nunca da equipe Mugô", async () => {
    await render();
    await click(button("Criar acesso"));
    const options = [...(field("client-access-form", "Perfil") as HTMLSelectElement).options].map((el) => el.value);
    expect(options).toEqual(["viewer", "client_admin"]);
    expect(options).not.toContain("agency_admin");
    expect(options).not.toContain("platform_admin");
  });

  it("a senha sai do formulário depois de criar", async () => {
    await render();
    await click(button("Criar acesso"));
    await type("client-access-form", "E-mail", "nova@empresa.com.br");
    await type("client-access-form", "Senha inicial", "fixture-senha-nao-real-1");
    await type("client-access-form", "Confirmar senha", "fixture-senha-nao-real-1");
    await click([...container.querySelectorAll('[data-testid="client-access-form"] button')].find((el) => el.textContent === "Criar acesso") as HTMLElement);
    // Formulário fechado e sem resquício da senha no DOM.
    expect(container.querySelector('[data-testid="client-access-form"]')).toBeNull();
    expect(container.innerHTML).not.toContain("fixture-senha-nao-real-1");
  });

  it("senha nunca aparece como campo de texto nem vai para a URL", async () => {
    await render();
    await click(button("Criar acesso"));
    for (const label of ["Senha inicial", "Confirmar senha"]) {
      const input = field("client-access-form", label) as HTMLInputElement;
      expect(input.type).toBe("password");
      expect(input.getAttribute("autocomplete")).toBe("new-password");
      expect(input.getAttribute("name")).toBeNull();
    }
    expect(window.location.search).not.toContain("password");
  });

  it("erro do servidor mantém o formulário e a mensagem", async () => {
    api.createClientAccess.mockRejectedValue(new Error("Este e-mail já tem acesso a esta empresa."));
    await render();
    await click(button("Criar acesso"));
    await type("client-access-form", "E-mail", "pessoa@empresa.com.br");
    await type("client-access-form", "Senha inicial", "fixture-senha-nao-real-1");
    await type("client-access-form", "Confirmar senha", "fixture-senha-nao-real-1");
    await click([...container.querySelectorAll('[data-testid="client-access-form"] button')].find((el) => el.textContent === "Criar acesso") as HTMLElement);
    expect(container.querySelector(".companiesError")?.textContent).toContain("já tem acesso");
    expect(container.querySelector('[data-testid="client-access-form"]')).not.toBeNull();
  });
});

describe("Acessos — redefinir senha e remover", () => {
  it("redefine a senha sem mostrar a antiga", async () => {
    await render();
    await click(button("Redefinir senha"));
    expect(container.textContent).toContain("A senha atual não é exibida nem recuperada");
    await type("client-access-reset", "Nova senha", "fixture-senha-nova-nao-real");
    await type("client-access-reset", "Confirmar nova senha", "fixture-senha-nova-nao-real");
    await click(button("Definir nova senha"));
    expect(api.resetClientAccessPassword).toHaveBeenCalledWith("user-1", {
      password: "fixture-senha-nova-nao-real", password_confirmation: "fixture-senha-nova-nao-real",
    });
    expect(container.textContent).toContain("Senha redefinida");
    expect(container.innerHTML).not.toContain("fixture-senha-nova-nao-real");
  });

  it("remover pede confirmação e explica que a conta continua", async () => {
    await render();
    await click(button("Remover acesso"));
    const confirm = container.querySelector('[data-testid="client-access-remove"]');
    expect(confirm?.textContent).toContain("A conta continua");
    expect(api.removeClientAccess).not.toHaveBeenCalled();
    await click([...(confirm?.querySelectorAll("button") || [])].find((el) => el.textContent === "Remover acesso") as HTMLElement);
    expect(api.removeClientAccess).toHaveBeenCalledWith("user-1");
    expect(container.textContent).toContain("acessos a outras empresas continuam");
  });

  it("cancelar remoção não chama o servidor", async () => {
    await render();
    await click(button("Remover acesso"));
    await click([...container.querySelectorAll('[data-testid="client-access-remove"] button')].find((el) => el.textContent === "Cancelar") as HTMLElement);
    expect(api.removeClientAccess).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="client-access-remove"]')).toBeNull();
  });
});

describe("Acessos — autorização na interface", () => {
  it("viewer consulta mas não administra", async () => {
    await render(false);
    expect(container.textContent).toContain("Pessoa Teste");
    expect(button("Criar acesso")).toBeUndefined();
    expect(button("Redefinir senha")).toBeUndefined();
    expect(button("Remover acesso")).toBeUndefined();
    expect(container.textContent).toContain("Criar e alterar é de administradores da empresa");
    expect(api.createClientAccess).not.toHaveBeenCalled();
  });

  it("perfil de gestão vê as ações", async () => {
    await render(true);
    expect(button("Criar acesso")).toBeTruthy();
    expect(button("Redefinir senha")).toBeTruthy();
    expect(button("Remover acesso")).toBeTruthy();
  });
});
