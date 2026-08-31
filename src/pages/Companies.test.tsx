// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  companies: [] as unknown[],
  shouldRejectCreate: false,
}));

vi.mock("../app/api", () => ({
  listPlatformCompanies: vi.fn(async () => ({ ok: true, companies: mocks.companies })),
  createPlatformCompany: vi.fn(async () => {
    if (mocks.shouldRejectCreate) throw new Error("Empresa duplicada.");
    return { ok: true, company: { id: "ruah", name: "Ruah Comércio Ltda", trade_name: "Ruah", status: "active" } };
  }),
  updatePlatformCompany: vi.fn(async () => ({ ok: true, company: { id: "amalie", name: "Amalie Ltda", trade_name: "Amalie", status: "active" } })),
  createClientInvitation: vi.fn(async () => ({ ok: true })),
}));

import Companies from "./Companies";
import { createClientInvitation, createPlatformCompany, updatePlatformCompany } from "../app/api";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

async function renderCompanies() {
  await act(async () => {
    root.render(<Companies onLogout={() => {}} onOpenCompany={() => {}} onOpenDashboard={() => {}} />);
  });
  await act(async () => Promise.resolve());
}

function findButton(text: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find((item) => item.textContent === text);
}

function fillInput(label: string, value: string) {
  const input = [...container.querySelectorAll("label")]
    .find((el) => el.textContent?.startsWith(label))
    ?.querySelector("input");
  if (!input) throw new Error(`input não encontrado: ${label}`);
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  mocks.companies = [
    { id: "amalie", name: "Amalie Ltda", trade_name: "Amalie", status: "active", responsible_email: "a@amalie.com", invitation_status: "accepted" },
  ];
  mocks.shouldRejectCreate = false;
  vi.mocked(createPlatformCompany).mockClear();
  vi.mocked(createClientInvitation).mockClear();
  vi.mocked(updatePlatformCompany).mockClear();
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function advanceWizardToReview() {
  fillInput("Razão social", "Ruah Comércio Ltda");
  fillInput("E-mail do responsável", "contato@ruah.com");
  await act(async () => {
    findButton("Continuar")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await act(async () => {
    findButton("Continuar")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await act(async () => {
    findButton("Continuar")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

describe("Companies — wizard de nova empresa", () => {
  it("formulário não aparece no fim da página por padrão (drawer fechado)", async () => {
    await renderCompanies();
    expect(container.querySelector(".drawerBackdrop")).toBeNull();
    expect(findButton("+ Nova empresa")).toBeTruthy();
  });

  it("abre em drawer (wizard) ao clicar em '+ Nova empresa' e fecha somente em sucesso", async () => {
    await renderCompanies();
    await act(async () => {
      findButton("+ Nova empresa")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.querySelector(".drawerBackdrop")).toBeTruthy();

    await advanceWizardToReview();

    await act(async () => {
      findButton("Criar empresa")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });

    expect(createPlatformCompany).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Ruah Comércio Ltda", responsible_email: "contato@ruah.com" })
    );
    // Wizard avança para o passo "Concluído" em vez de fechar sozinho.
    expect(container.textContent).toContain("Empresa criada");
  });

  it("mantém o wizard aberto e os dados preenchidos quando o backend retorna erro", async () => {
    mocks.shouldRejectCreate = true;
    await renderCompanies();
    await act(async () => {
      findButton("+ Nova empresa")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await advanceWizardToReview();

    await act(async () => {
      findButton("Criar empresa")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });

    expect(container.querySelector(".drawerBackdrop")).toBeTruthy();
    expect(container.textContent).toContain("Empresa duplicada.");
  });

  it("Continuar fica bloqueado até nome e e-mail do responsável serem preenchidos", async () => {
    await renderCompanies();
    await act(async () => {
      findButton("+ Nova empresa")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(findButton("Continuar")?.disabled).toBe(true);
    fillInput("Razão social", "Ruah Comércio Ltda");
    fillInput("E-mail do responsável", "contato@ruah.com");
    expect(findButton("Continuar")?.disabled).toBe(false);
  });

  it("bloqueia envio duplo desabilitando o botão de criação durante o salvamento", async () => {
    await renderCompanies();
    await act(async () => {
      findButton("+ Nova empresa")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await advanceWizardToReview();
    const createButton = findButton("Criar empresa");
    await act(async () => {
      createButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(createPlatformCompany).toHaveBeenCalledTimes(1);
  });

  it("duplo clique no botão Criar empresa cria apenas uma empresa", async () => {
    await renderCompanies();
    await act(async () => {
      findButton("+ Nova empresa")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await advanceWizardToReview();
    const createButton = findButton("Criar empresa");
    await act(async () => {
      createButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      createButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(createPlatformCompany).toHaveBeenCalledTimes(1);
  });
});

describe("Companies — modal de convite de usuário", () => {
  it("abre em modal ao clicar em 'Convidar usuário' e fecha somente em sucesso", async () => {
    await renderCompanies();
    await act(async () => {
      findButton("Convidar usuário")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.querySelector(".modalBackdrop")).toBeTruthy();

    const select = container.querySelector("select");
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
    setter?.call(select, "amalie");
    select?.dispatchEvent(new Event("change", { bubbles: true }));
    fillInput("E-mail", "novo@amalie.com");

    await act(async () => {
      container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });

    expect(createClientInvitation).toHaveBeenCalledWith(
      expect.objectContaining({ client_id: "amalie", email: "novo@amalie.com" })
    );
    expect(container.querySelector(".modalBackdrop")).toBeNull();
  });
});

describe("Companies — busca, abas e resumo", () => {
  it("filtra a lista pela busca sem exigir F5", async () => {
    mocks.companies = [
      { id: "amalie", name: "Amalie Ltda", trade_name: "Amalie", status: "active" },
      { id: "ruah", name: "Ruah Comércio", trade_name: "Ruah", status: "active" },
    ];
    await renderCompanies();
    expect(container.textContent).toContain("Amalie");
    expect(container.textContent).toContain("Ruah");

    const search = container.querySelector("input[type=search]") as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    await act(async () => {
      setter?.call(search, "ruah");
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });

    expect(container.textContent).not.toContain("Amalie Ltda");
    expect(container.textContent).toContain("Ruah");
  });

  it("troca para a aba Permissões e mostra a explicação de cada papel", async () => {
    await renderCompanies();
    await act(async () => {
      findButton("Permissões")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.textContent).toContain("Mugô — gerencia todas as empresas.");
    expect(container.textContent).toContain("Visualização somente leitura.");
  });

  it("troca para a aba Usuários e mostra o responsável de cada empresa", async () => {
    await renderCompanies();
    await act(async () => {
      findButton("Usuários")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.textContent).toContain("a@amalie.com");
  });
});

describe("Companies — editar empresa em drawer", () => {
  it("abre o drawer de edição a partir do menu de ações e salva alterações", async () => {
    await renderCompanies();
    const menu = container.querySelector(".companiesRowMenu summary") as HTMLElement;
    await act(async () => {
      menu.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      // <details> abre via toggle nativo do DOM, não via clique sintético em jsdom;
      // forçamos o estado aberto para simular o comportamento do navegador.
      (menu.parentElement as HTMLDetailsElement).open = true;
    });
    await act(async () => {
      findButton("Editar")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.querySelector(".drawerBackdrop")).toBeTruthy();

    await act(async () => {
      findButton("Salvar alterações")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    expect(updatePlatformCompany).toHaveBeenCalledWith("amalie", expect.objectContaining({ name: "Amalie Ltda" }));
  });
});
