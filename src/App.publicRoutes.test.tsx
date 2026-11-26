// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const privateCalls = vi.hoisted(() => ({
  getSession: vi.fn(),
  onAuthStateChange: vi.fn(),
  from: vi.fn(),
  listClients: vi.fn(),
  getMyPendingInvitations: vi.fn(),
  openPlatformCompany: vi.fn(),
}));

vi.mock("./app/supabase", () => ({
  disableLocalAuth: vi.fn(),
  getSupabaseBootstrapError: vi.fn(() => null),
  isLocalAuthEnabled: vi.fn(() => false),
  supabase: {
    auth: {
      getSession: privateCalls.getSession,
      onAuthStateChange: privateCalls.onAuthStateChange,
      signOut: vi.fn(),
    },
    from: privateCalls.from,
  },
}));

vi.mock("./app/api", () => ({
  setApiAccessToken: vi.fn(),
  listClients: privateCalls.listClients,
  getMyPendingInvitations: privateCalls.getMyPendingInvitations,
  openPlatformCompany: privateCalls.openPlatformCompany,
}));

import App from "./App";
import { LEGAL_CONTACT } from "./app/legalContact";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  vi.clearAllMocks();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  window.history.replaceState({}, "", "/");
});

async function renderPublicPath(path: string) {
  window.history.replaceState({}, "", path);
  await act(async () => root.render(React.createElement(App)));
  // Páginas legais carregam sob demanda (lazy): espera a página aparecer.
  for (let i = 0; i < 50 && !container.querySelector("[data-public-route]"); i += 1) {
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  }
}

function expectNoPrivateBootstrap() {
  expect(privateCalls.getSession).not.toHaveBeenCalled();
  expect(privateCalls.onAuthStateChange).not.toHaveBeenCalled();
  expect(privateCalls.from).not.toHaveBeenCalled();
  expect(privateCalls.listClients).not.toHaveBeenCalled();
  expect(privateCalls.getMyPendingInvitations).not.toHaveBeenCalled();
  expect(privateCalls.openPlatformCompany).not.toHaveBeenCalled();
  expect(window.location.pathname).not.toBe("/meta");
  expect(container.textContent).not.toContain("Entrar");
}

describe("public legal routes", () => {
  it("renders /privacidade without Supabase auth or tenant bootstrap", async () => {
    await renderPublicPath("/privacidade");
    expect(container.querySelector('[data-public-route="privacy"]')).toBeTruthy();
    expect(container.textContent).toContain("Política de Privacidade");
    const publicLinks = [...container.querySelectorAll("a")].map((link) => link.getAttribute("href"));
    expect(publicLinks).toContain("/privacidade");
    expect(publicLinks).toContain("/protecao-de-dados");
    expect(publicLinks).toContain("/exclusao-de-dados");
    expect(container.querySelector('[data-legal-contact="privacy"]')?.textContent).toContain(LEGAL_CONTACT);
    expectNoPrivateBootstrap();
  });

  it("renders /exclusao-de-dados without Supabase auth or tenant bootstrap", async () => {
    await renderPublicPath("/exclusao-de-dados");
    expect(container.querySelector('[data-public-route="data-deletion"]')).toBeTruthy();
    expect(container.textContent).toContain("Exclusão de dados");
    expect(container.querySelector('[data-legal-contact="data-deletion"]')?.textContent).toContain(LEGAL_CONTACT);
    expectNoPrivateBootstrap();
  });

  it("renders /protecao-de-dados without Supabase auth or tenant bootstrap", async () => {
    await renderPublicPath("/protecao-de-dados");
    expect(container.querySelector('[data-public-route="data-protection"]')).toBeTruthy();
    expect(container.textContent).toContain("Proteção de dados");
    expectNoPrivateBootstrap();
  });

  it.each([
    ["/privacidade", "privacy"],
    ["/exclusao-de-dados", "data-deletion"],
    ["/protecao-de-dados", "data-protection"],
  ])("%s fica marcado para revisão jurídica e não promete conformidade", async (path, route) => {
    await renderPublicPath(path);
    const page = container.querySelector(`[data-public-route="${route}"]`);
    expect(page?.getAttribute("data-legal-status")).toBe(route === "data-protection" ? "review-pending" : "draft-legal-review");
    expect(container.textContent).not.toMatch(/LGPD compliant|100%|em conformidade com a LGPD|totalmente seguro|garantimos/i);
    expectNoPrivateBootstrap();
  });

  it("renders bilingual legal drafts without private auth", async () => {
    await renderPublicPath("/termos-de-uso");
    const page = container.querySelector('[data-public-route="terms"]');
    expect(page?.getAttribute("data-legal-status")).toBe("draft-legal-review");
    expect(container.textContent).toContain("Termos de Uso");
    expect(container.querySelector('[data-legal-contact="terms"]')?.textContent).toContain(LEGAL_CONTACT);
    expectNoPrivateBootstrap();
    await renderPublicPath("/en/privacy");
    expect(container.textContent).toContain("Privacy Policy");
    expectNoPrivateBootstrap();
    await renderPublicPath("/en/terms");
    expect(container.textContent).toContain("Terms of Service");
    expectNoPrivateBootstrap();
    await renderPublicPath("/en/data-deletion");
    expect(container.textContent).toContain("Data Deletion");
    expectNoPrivateBootstrap();
  });
});
