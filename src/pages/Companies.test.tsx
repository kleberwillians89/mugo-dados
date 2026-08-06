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
    return { ok: true };
  }),
  updatePlatformCompany: vi.fn(async () => ({ ok: true })),
  createClientInvitation: vi.fn(async () => ({ ok: true })),
}));

import Companies from "./Companies";
import { createClientInvitation, createPlatformCompany } from "../app/api";

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
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("Companies — modal de empresa", () => {
  it("formulário não aparece no fim da página por padrão (modal fechado)", async () => {
    await renderCompanies();
    expect(container.querySelector(".modalBackdrop")).toBeNull();
    expect(findButton("Nova empresa")).toBeTruthy();
  });

  it("abre em modal ao clicar em 'Nova empresa' e fecha somente em sucesso", async () => {
    await renderCompanies();
    await act(async () => {
      findButton("Nova empresa")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.querySelector(".modalBackdrop")).toBeTruthy();

    fillInput("Razão social", "Ruah Comércio Ltda");
    fillInput("E-mail do responsável", "contato@ruah.com");

    await act(async () => {
      findButton("Criar empresa")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });

    expect(createPlatformCompany).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Ruah Comércio Ltda", responsible_email: "contato@ruah.com" })
    );
    expect(container.querySelector(".modalBackdrop")).toBeNull();
  });

  it("mantém o modal aberto e o formulário preenchido quando o backend retorna erro", async () => {
    mocks.shouldRejectCreate = true;
    await renderCompanies();
    await act(async () => {
      findButton("Nova empresa")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    fillInput("Razão social", "Ruah Comércio Ltda");
    fillInput("E-mail do responsável", "contato@ruah.com");

    await act(async () => {
      container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });

    expect(container.querySelector(".modalBackdrop")).toBeTruthy();
    expect(container.textContent).toContain("Empresa duplicada.");
    const nameInput = [...container.querySelectorAll("input")].find((i) => (i as HTMLInputElement).value === "Ruah Comércio Ltda");
    expect(nameInput).toBeTruthy();
  });

  it("Cancelar fecha o modal sem enviar", async () => {
    await renderCompanies();
    await act(async () => {
      findButton("Nova empresa")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => {
      findButton("Cancelar")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.querySelector(".modalBackdrop")).toBeNull();
    expect(createPlatformCompany).not.toHaveBeenCalled();
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

describe("Companies — busca e resumo", () => {
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
});
