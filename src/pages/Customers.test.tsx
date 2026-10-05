// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const tenant = vi.hoisted(() => ({ id: "roove-test", name: "Roove" }));

vi.mock("../app/activeClient", () => ({
  getActiveClientId: () => tenant.id,
  getActiveClientName: () => tenant.name,
}));

const api = vi.hoisted(() => ({
  getCustomers: vi.fn(),
  getCustomerDetail: vi.fn(),
}));

vi.mock("../app/api", () => api);

const Customers = (await import("./Customers")).default;
const { clearDashboardCacheByPrefix } = await import("../hooks/dashboard/cache");

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
    root.render(React.createElement(Customers, { key: tenant.id }));
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
  tenant.id = "roove-test";
  tenant.name = "Roove";
  clearDashboardCacheByPrefix("customers-base|");
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
  it("mostra loading antes da primeira resposta, sem depender de connected", async () => {
    api.getCustomers.mockImplementation(() => new Promise(() => {}));
    await render();
    expect(api.getCustomers).toHaveBeenCalledOnce();
    expect(text()).toContain("Carregando clientes...");
    expect(text()).not.toContain("Nenhum cliente encontrado");
  });

  it("não renderiza o botão Sair solto nem a barra utilitária", async () => {
    await render();
    expect([...container.querySelectorAll("button")].some((button) => button.textContent?.trim() === "Sair")).toBe(false);
    expect(container.querySelector(".ds-utilityBar")).toBeNull();
  });
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
    expect(text()).not.toContain("Cliente c-100");
    expect(container.querySelector(".customerNameButton")?.textContent).toBe("—");
    expect(text()).toContain("—");
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
    expect(text()).not.toContain("Nenhum cliente encontrado");
    expect(text()).not.toContain("Nenhuma loja conectada");
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
    expect(text()).toContain("Receita");
    expect([...container.querySelectorAll("dt")].map((item) => item.textContent)).toEqual(["Nome", "Email", "Telefone", "Origem", "Receita", "Pedidos", "Ticket médio", "Primeira compra", "Última compra"]);
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

it("mostra vazio somente após resposta válida sem clientes", async () => {
  api.getCustomers.mockResolvedValue(listing({ customers: [], total: 0 }));
  await render();
  expect(text()).toContain("Nenhum cliente encontrado para esta empresa.");
  expect(container.querySelector('[role="alert"]')).toBeNull();
});

it("contatos ausentes têm placeholders discretos", async () => {
  api.getCustomers.mockResolvedValue(listing({ customers: [summary({ email: null, phone: null })] }));
  await render();
  const cell = container.querySelector(".customerNameButton")!.closest("td")!;
  expect(cell.querySelector('[aria-label="E-mail"]')?.textContent).toBe("—");
  expect(cell.querySelector('[aria-label="Telefone"]')?.textContent).toBe("—");
});

it("troca de empresa recarrega a base e descarta resposta antiga", async () => {
  let oldResponse!: (value: unknown) => void;
  api.getCustomers.mockImplementationOnce(() => new Promise((resolve) => { oldResponse = resolve; }));
  await render();
  tenant.id = "vinhos"; tenant.name = "Curavino";
  api.getCustomers.mockResolvedValue(listing({ client_id: "vinhos", customers: [summary({ client_id: "vinhos", name: "Cliente Curavino" })] }));
  await render();
  expect(api.getCustomers).toHaveBeenCalledTimes(2);
  await act(async () => { oldResponse(listing()); });
  expect(text()).toContain("Cliente Curavino");
  expect(text()).not.toContain("Ana Recorrente");
});

it("rejeita lista de outro tenant como erro, sem exibir seus contatos", async () => {
  api.getCustomers.mockResolvedValue(listing({ client_id: "vinhos", customers: [summary({ client_id: "vinhos" })] }));
  await render();
  expect(text()).toContain("Não foi possível carregar os clientes.");
  expect(text()).not.toContain("ana@exemplo-roove.com");
  expect(text()).not.toContain("Nenhum cliente encontrado");
});

it("resposta incompatível não vira base vazia", async () => {
  api.getCustomers.mockResolvedValue({ client_id: "roove-test", customers: null });
  await render();
  expect(text()).toContain("Não foi possível carregar os clientes.");
  expect(text()).not.toContain("Nenhum cliente encontrado");
});

it("resposta tardia de detalhe não abre drawer em outro tenant", async () => {
  let detail!: (value: unknown) => void;
  api.getCustomerDetail.mockImplementation(() => new Promise((resolve) => { detail = resolve; }));
  await render();
  await act(async () => { container.querySelector<HTMLButtonElement>(".customerNameButton")!.click(); });
  tenant.id = "vinhos"; tenant.name = "Curavino";
  api.getCustomers.mockResolvedValue(listing({ client_id: "vinhos", customers: [], total: 0 }));
  await render();
  await act(async () => { detail({ client_id: "roove-test", customer: summary(), orders: [] }); });
  expect(container.querySelector('[role="dialog"]')).toBeNull();
  expect(text()).not.toContain("Ana Recorrente");
});

it("listagem permanece somente leitura e não renderiza campos sensíveis extras", async () => {
  api.getCustomers.mockResolvedValue(listing({ customers: [{ ...summary(), cpf: "CPF-TESTE", address: "ENDERECO-TESTE", payment: "PAGAMENTO-TESTE", raw_payload: "RAW-TESTE" }] }));
  await render();
  for (const field of ["CPF-TESTE", "ENDERECO-TESTE", "PAGAMENTO-TESTE", "RAW-TESTE"]) expect(text()).not.toContain(field);
  for (const label of ["Criar", "Editar", "Excluir", "Sincronizar"]) {
    expect([...container.querySelectorAll("button")].some((button) => button.textContent?.includes(label))).toBe(false);
  }
  expect(api.getCustomerDetail).not.toHaveBeenCalled();
});


it("Clientes não oferece CTA manual e mostra contato abaixo do nome", async () => {
  api.getCustomers.mockResolvedValue(listing());
  await render();
  expect(container.querySelector('[data-testid="customers-refresh"]')).toBeNull();
  expect([...container.querySelectorAll("button")].some((item) => item.textContent === "Atualizar dados")).toBe(false);
  const cell = container.querySelector(".customerNameButton")?.closest("td");
  expect(cell?.textContent).toContain("Ana Recorrente");
  expect(cell?.textContent).toContain("ana@exemplo-roove.com");
  expect(cell?.textContent).toContain("(11) 98888-7777");
});

it("nome ausente usa email ou telefone sem fabricar identidade", async () => {
  api.getCustomers.mockResolvedValue(listing({ customers: [summary({ name: null })] }));
  await render();
  expect(container.querySelector(".customerNameButton")?.textContent).toBe("ana@exemplo-roove.com");
});

it("revalidação silenciosa preserva tabela durante espera e falha", async () => {
  await render();
  let fail!: (reason: Error) => void;
  api.getCustomers.mockImplementation(() => new Promise((_resolve, reject) => { fail = reject; }));
  await act(async () => { typeSearch("Ana"); await vi.advanceTimersByTimeAsync(400); });
  expect(container.querySelector(".customerNameButton")?.textContent).toBe("Ana Recorrente");
  expect(text()).not.toContain("Carregando clientes");
  await act(async () => { fail(new Error("temporariamente indisponível")); });
  expect(container.querySelector(".customerNameButton")?.textContent).toBe("Ana Recorrente");
  expect(text()).toContain("temporariamente indisponível");
});
