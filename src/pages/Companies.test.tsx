// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  companies: [] as unknown[],
  shouldRejectCreate: false,
  responsibleAccountExists: false,
  inviteAccountExists: false,
  activeClientId: "",
}));

vi.mock("../app/activeClient", () => ({
  getActiveClient: () => mocks.activeClientId
    ? { id: mocks.activeClientId, name: "Empresa ativa", role: "platform_admin" }
    : null,
}));

vi.mock("../app/api", () => ({
  listPlatformCompanies: vi.fn(async () => ({ ok: true, companies: mocks.companies })),
  createPlatformCompany: vi.fn(async () => {
    if (mocks.shouldRejectCreate) throw new Error("Empresa duplicada.");
    return {
      ok: true,
      company: { id: "ruah", name: "Ruah Comércio Ltda", trade_name: "Ruah", status: "active" },
      responsible_account_exists: mocks.responsibleAccountExists,
    };
  }),
  updatePlatformCompany: vi.fn(async () => ({ ok: true, company: { id: "amalie", name: "Amalie Ltda", trade_name: "Amalie", status: "active" } })),
  createClientInvitation: vi.fn(async () => ({
    ok: true,
    invitation: { id: "inv-x", email: "novo@amalie.com", role: "viewer", account_exists: mocks.inviteAccountExists },
  })),
  createCompanyActivationLink: vi.fn(async () => ({
    ok: true,
    invitation: { id: "inv-1", email: "a@amalie.com", client_id: "amalie", role: "owner", expires_at: null },
    activation_url: "https://dados.mugoagencia.com.br/verify?token=abc",
    account_exists: false,
  })),
  deletePlatformCompany: vi.fn(async (clientId: string, confirmationName: string) => ({
    ok: true,
    deleted_client_id: clientId,
    deleted_company_name: confirmationName,
  })),
}));

import Companies from "./Companies";
import {
  createClientInvitation,
  createCompanyActivationLink,
  createPlatformCompany,
  deletePlatformCompany,
  updatePlatformCompany,
} from "../app/api";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

async function renderCompanies(
  overrides: Partial<React.ComponentProps<typeof Companies>> = {}
) {
  await act(async () => {
    root.render(
      <Companies
        onLogout={() => {}}
        onOpenCompany={() => {}}
        onOpenDashboard={() => {}}
        {...overrides}
      />
    );
  });
  await act(async () => Promise.resolve());
}

async function openRowMenu() {
  const menu = container.querySelector(".companiesRowMenu summary") as HTMLElement;
  await act(async () => {
    menu.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    // <details> não abre via clique sintético no jsdom — forçamos o estado.
    (menu.parentElement as HTMLDetailsElement).open = true;
  });
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
  mocks.responsibleAccountExists = false;
  mocks.inviteAccountExists = false;
  mocks.activeClientId = "";
  vi.mocked(createPlatformCompany).mockClear();
  vi.mocked(createClientInvitation).mockClear();
  vi.mocked(updatePlatformCompany).mockClear();
  vi.mocked(createCompanyActivationLink).mockClear();
  vi.mocked(deletePlatformCompany).mockClear();
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

  it("responsável com conta Supabase existente: empresa é criada e o wizard orienta o link de onboarding", async () => {
    mocks.responsibleAccountExists = true;
    await renderCompanies();
    await act(async () => {
      findButton("+ Nova empresa")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await advanceWizardToReview();
    await act(async () => {
      findButton("Criar empresa")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });

    // Não é erro: a empresa foi criada e o passo "Concluído" aparece.
    expect(container.textContent).toContain("Empresa criada");
    expect(container.querySelector(".wizardError")).toBeNull();
    expect(container.querySelector('.wizardDone [role="status"]')?.textContent).toContain(
      "já tem conta na Mugô"
    );
  });

  it("envia idempotency_key estável entre tentativas (retry seguro, sem duplicar empresa)", async () => {
    vi.mocked(createPlatformCompany)
      .mockRejectedValueOnce(new Error("tempo esgotado"))
      .mockResolvedValueOnce({
        ok: true,
        company: { id: "ruah", name: "Ruah Comércio Ltda", trade_name: "Ruah", status: "active" },
      });
    await renderCompanies();
    await act(async () => {
      findButton("+ Nova empresa")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await advanceWizardToReview();
    await act(async () => {
      findButton("Criar empresa")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    await act(async () => {
      findButton("Criar empresa")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });

    const calls = vi.mocked(createPlatformCompany).mock.calls;
    expect(calls.length).toBe(2);
    expect(String((calls[0][0] as { idempotency_key?: string }).idempotency_key || "")).not.toBe("");
    expect((calls[1][0] as { idempotency_key?: string }).idempotency_key).toBe(
      (calls[0][0] as { idempotency_key?: string }).idempotency_key
    );
  });

  it("'+ Nova empresa' não aparece quando o usuário não pode criar empresa (agency_admin sem platform_admin)", async () => {
    await renderCompanies({ canCreateCompany: false });
    expect(findButton("+ Nova empresa")).toBeUndefined();
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

  it("convidado com conta existente: mensagem orienta o link de onboarding em vez de 'convite enviado'", async () => {
    mocks.inviteAccountExists = true;
    await renderCompanies();
    await act(async () => {
      findButton("Convidar usuário")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const select = container.querySelector("select");
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
    setter?.call(select, "amalie");
    select?.dispatchEvent(new Event("change", { bubbles: true }));
    fillInput("E-mail", "novo@amalie.com");

    await act(async () => {
      container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });

    expect(container.textContent).toContain("já tem conta Mugô");
    expect(container.textContent).not.toContain("Convite enviado com segurança");
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

  it("inativa a empresa sem confundir a ação com exclusão permanente", async () => {
    await renderCompanies({ canDeleteCompany: true });
    await openRowMenu();
    await act(async () => {
      findButton("Inativar")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });

    expect(updatePlatformCompany).toHaveBeenCalledWith("amalie", { status: "inactive" });
    expect(deletePlatformCompany).not.toHaveBeenCalled();
  });
});

describe("Companies — exclusão permanente", () => {
  it("não exibe a ação para quem não é platform_admin", async () => {
    await renderCompanies({ canDeleteCompany: false });
    await openRowMenu();
    expect(findButton("Excluir permanentemente")).toBeUndefined();
  });

  it("exige o nome exato antes de excluir somente a empresa selecionada", async () => {
    mocks.companies = [
      { id: "amalie", name: "Amalie Ltda", trade_name: "Amalie", status: "active" },
      { id: "roove", name: "Roove Ltda", trade_name: "Roove", status: "active" },
    ];
    await renderCompanies({ canDeleteCompany: true });
    await openRowMenu();
    await act(async () => {
      findButton("Excluir permanentemente")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.textContent).toContain("Esta ação é irreversível");
    const deleteSubmit = container.querySelector(
      ".companiesDangerForm button[type=submit]"
    ) as HTMLButtonElement;
    expect(deleteSubmit.disabled).toBe(true);
    fillInput("Nome da empresa", "Amalie");
    expect(deleteSubmit.disabled).toBe(false);

    await act(async () => {
      deleteSubmit.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });

    expect(deletePlatformCompany).toHaveBeenCalledWith("amalie", "Amalie");
    expect(container.textContent).not.toContain("Amalie Ltda");
    expect(container.textContent).toContain("Roove Ltda");
  });

  it("impede excluir a empresa atualmente aberta", async () => {
    mocks.activeClientId = "amalie";
    await renderCompanies({ canDeleteCompany: true });
    await openRowMenu();
    await act(async () => {
      findButton("Excluir permanentemente")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.textContent).toContain("Troque para outra empresa");
    expect(container.querySelector(".modalBackdrop")).toBeNull();
    expect(deletePlatformCompany).not.toHaveBeenCalled();
  });
});

describe("Companies — onboarding converge para o mesmo Onboarding.tsx", () => {
  it("'Fazer onboarding' seleciona a empresa e navega para integrations", async () => {
    const onOpenCompany = vi.fn();
    await renderCompanies({ onOpenCompany });
    await openRowMenu();

    await act(async () => {
      findButton("Fazer onboarding")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onOpenCompany).toHaveBeenCalledTimes(1);
    expect(onOpenCompany).toHaveBeenCalledWith(
      expect.objectContaining({ id: "amalie" }),
      "integrations"
    );
  });

  it("'Abrir para suporte' continua abrindo o dashboard (sem rota de destino)", async () => {
    const onOpenCompany = vi.fn();
    await renderCompanies({ onOpenCompany });
    await openRowMenu();

    await act(async () => {
      findButton("Abrir para suporte")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onOpenCompany).toHaveBeenCalledTimes(1);
    const [company, targetRoute] = onOpenCompany.mock.calls[0];
    expect(company).toEqual(expect.objectContaining({ id: "amalie" }));
    expect(targetRoute).toBeUndefined();
  });

  it("'Gerar link de onboarding' continua gerando o activation link existente", async () => {
    await renderCompanies();
    await openRowMenu();

    await act(async () => {
      findButton("Gerar link de onboarding")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });

    expect(createCompanyActivationLink).toHaveBeenCalledWith("amalie");
    const linkInput = [...container.querySelectorAll("input")].find(
      (input) => input.value.includes("dados.mugoagencia.com.br/verify?token=abc")
    );
    expect(linkInput).toBeTruthy();
  });
});
