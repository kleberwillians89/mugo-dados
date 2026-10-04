// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../app/activeClient", () => ({
  getActiveClientId: () => "roove-test",
  getActiveClientName: () => "Roove",
}));

const api = vi.hoisted(() => ({
  getCustomers: vi.fn(),
  getCustomerDetail: vi.fn(),
}));

vi.mock("../app/api", () => api);

const Customers = (await import("./Customers")).default;

type Summary = {
  id: string;
  external_id: string | null;
  client_id: string;
  provider: "fbits" | "shopify";
  provider_label: string;
  identity_kind: "external_id" | "email" | "phone";
  name: string | null;
  email: string | null;
  phone: string | null;
  orders_count: number;
  total_revenue: number;
  average_ticket: number | null;
  first_order_at: string | null;
  last_order_at: string | null;
  status: "recurring" | "single" | "no_purchase";
};

function summary(overrides: Partial<Summary> = {}): Summary {
  return {
    id: "key-ana",
    external_id: "s-1",
    client_id: "roove-test",
    provider: "shopify",
    provider_label: "Shopify",
    identity_kind: "external_id",
    name: "Ana Recorrente",
    email: "ana@exemplo-roove.com",
    phone: "5511988887777",
    orders_count: 2,
    total_revenue: 1000,
    average_ticket: 500,
    first_order_at: "2026-09-02T10:00:00+00:00",
    last_order_at: "2026-10-01T10:00:00+00:00",
    status: "recurring",
    ...overrides,
  };
}

function listing(overrides: Record<string, unknown> = {}) {
  return {
    ok: true as const,
    client_id: "roove-test",
    provider: "shopify" as const,
    provider_label: "Shopify",
    connected: true,
    totals: {
      customers: 3,
      recurring_customers: 1,
      buyers: 3,
      total_revenue: 1200,
      total_orders: 4,
      average_ticket: 300,
    },
    customers: [summary()],
    page: 1,
    page_size: 25,
    total: 1,
    truncated: false,
    contact_details_available: true,
    orders_unattributed: 0,
    ...overrides,
  };
}

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

async function render() {
  await act(async () => {
    root.render(React.createElement(Customers, { onLogout: () => {} }));
  });
}

function text(): string {
  return container.textContent || "";
}

/** React só vê o valor digitado através do setter nativo do input. */
function typeSearch(value: string) {
  const input = container.querySelector<HTMLInputElement>("#customer-search");
  if (!input) throw new Error("campo de busca não encontrado");
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  api.getCustomers.mockReset();
  api.getCustomerDetail.mockReset();
  api.getCustomers.mockResolvedValue(listing());
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

describe("página Clientes", () => {
  it("abre com o título e a frase de apresentação", async () => {
    await render();
    expect(text()).toContain("Clientes");
    expect(text()).toContain("Conheça e acompanhe a base de clientes desta empresa.");
  });

  it("mostra os quatro cartões de resumo", async () => {
    await render();
    expect(text()).toContain("Total de clientes");
    expect(text()).toContain("Clientes recorrentes");
    expect(text()).toContain("Receita da base");
    expect(text()).toContain("Ticket médio");
  });

  it("mostra as colunas pedidas na tabela", async () => {
    await render();
    const headers = [...container.querySelectorAll("th")].map((cell) => cell.textContent);
    expect(headers).toEqual([
      "Cliente",
      "Contato",
      "Pedidos",
      "Receita",
      "Ticket médio",
      "Última compra",
      "Origem",
    ]);
  });

  it("mostra o cliente com contato e valores formatados em real", async () => {
    await render();
    expect(text()).toContain("Ana Recorrente");
    expect(text()).toContain("ana@exemplo-roove.com");
    expect(text()).toContain("(11) 98888-7777");
    expect(text()).toContain("R$");
  });

  it("mostra a origem como Shopify", async () => {
    await render();
    const origin = container.querySelector(".customerOrigin");
    expect(origin?.textContent).toBe("Shopify");
  });

  it("mostra a origem como FBITS quando a loja é FBITS", async () => {
    api.getCustomers.mockResolvedValue(
      listing({
        provider: "fbits",
        provider_label: "FBITS",
        customers: [summary({ provider: "fbits", provider_label: "FBITS" })],
      }),
    );
    await render();
    expect(container.querySelector(".customerOrigin")?.textContent).toBe("FBITS");
  });

  it("não usa linguagem técnica na tela", async () => {
    await render();
    for (const jargon of ["provider", "payload", "external_id", "sync job", "client_id"]) {
      expect(text().toLowerCase()).not.toContain(jargon.toLowerCase());
    }
  });

  it("identifica o cliente sem nome sem inventar um", async () => {
    api.getCustomers.mockResolvedValue(
      listing({
        contact_details_available: false,
        customers: [summary({ name: null, email: null, phone: null, external_id: "c-100" })],
      }),
    );
    await render();
    expect(text()).toContain("Cliente c-100");
    expect(text()).toContain("Não informado");
  });

  it("avisa quando a loja não compartilha contatos", async () => {
    api.getCustomers.mockResolvedValue(
      listing({
        contact_details_available: false,
        customers: [summary({ name: null, email: null, phone: null })],
      }),
    );
    await render();
    expect(text()).toContain("Contatos não disponíveis nesta loja");
  });

  it("mostra estado vazio claro quando não há loja conectada", async () => {
    api.getCustomers.mockResolvedValue(
      listing({ provider: null, provider_label: null, connected: false, customers: [], total: 0 }),
    );
    await render();
    expect(text()).toContain("Nenhuma loja conectada");
    expect(container.querySelector(".customerTable")).toBeNull();
  });

  it("busca pelo termo digitado, uma requisição por termo", async () => {
    await render();
    expect(container.querySelector("#customer-search")).not.toBeNull();
    api.getCustomers.mockClear();
    await act(async () => {
      typeSearch("Ana");
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    expect(api.getCustomers).toHaveBeenCalledTimes(1);
    expect(api.getCustomers.mock.calls[0][0]).toMatchObject({ search: "Ana", page: 1 });
  });

  it("diz que a busca não encontrou ninguém", async () => {
    api.getCustomers.mockResolvedValue(listing({ customers: [], total: 0 }));
    await render();
    await act(async () => {
      typeSearch("ninguem");
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    expect(text()).toContain("Nenhum cliente encontrado para esta busca.");
  });

  it("pagina quando há mais de uma página", async () => {
    api.getCustomers.mockResolvedValue(listing({ total: 60 }));
    await render();
    expect(text()).toContain("Página 1 de 3");
    const next = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Próxima",
    );
    api.getCustomers.mockClear();
    await act(async () => {
      next!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(api.getCustomers.mock.calls[0][0]).toMatchObject({ page: 2 });
  });

  it("não mostra paginação com uma página só", async () => {
    await render();
    expect(text()).not.toContain("Página 1 de");
  });

  it("avisa quando a base foi truncada", async () => {
    api.getCustomers.mockResolvedValue(listing({ truncated: true }));
    await render();
    expect(text()).toContain("Base muito grande");
  });

  it("mostra o erro de carregamento sem quebrar a página", async () => {
    api.getCustomers.mockRejectedValue(new Error("A base de clientes não pôde ser carregada agora."));
    await render();
    expect(text()).toContain("Não foi possível carregar");
  });

  it("abre o detalhe do cliente com histórico de pedidos", async () => {
    api.getCustomerDetail.mockResolvedValue({
      ok: true,
      client_id: "roove-test",
      customer: summary(),
      orders: [
        {
          order_id: "1003",
          reference: "#1003",
          happened_at: "2026-10-02T10:00:00+00:00",
          value: 900,
          status: "Cancelado",
          counts_as_revenue: false,
        },
        {
          order_id: "1002",
          reference: "#1002",
          happened_at: "2026-10-01T10:00:00+00:00",
          value: 600,
          status: "paid",
          counts_as_revenue: true,
        },
      ],
    });
    await render();
    const name = container.querySelector<HTMLButtonElement>(".customerNameButton");
    await act(async () => {
      name!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(api.getCustomerDetail).toHaveBeenCalledWith("key-ana");
    expect(text()).toContain("Histórico de pedidos");
    expect(text()).toContain("Total comprado");
    expect(text()).toContain("Primeira compra");
    expect(text()).toContain("#1003");
    expect(text()).toContain("Cancelado");
  });

  it("mostra o erro do detalhe sem derrubar a listagem", async () => {
    api.getCustomerDetail.mockRejectedValue(new Error("Este cliente não pôde ser aberto agora."));
    await render();
    const name = container.querySelector<HTMLButtonElement>(".customerNameButton");
    await act(async () => {
      name!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(text()).toContain("Não foi possível abrir");
    expect(text()).toContain("Ana Recorrente");
  });
});
