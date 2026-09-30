// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const api = vi.hoisted(() => ({
  connectFbits: vi.fn(),
  syncFbitsConnection: vi.fn(),
  disconnectFbitsConnection: vi.fn(),
}));

vi.mock("../app/api", () => api);

import FbitsIntegrationPanel from "./FbitsIntegrationPanel";
import { INTEGRATION_REGISTRY } from "../app/integrationRegistry";
import type { ClientIntegrationConnection } from "../app/types";

const TOKEN = "fbits-secret-token-value";
let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

const connectedEntry: ClientIntegrationConnection = {
  provider: "fbits",
  connection_id: "fbits-curavino",
  status: "connected",
  authorization_status: "valid",
  sync_status: null,
  account: { name: "FBITS / Wake Commerce" },
  assets: {},
  last_sync_at: null,
  last_successful_sync_at: null,
  last_error: null,
  updated_at: null,
};

async function render(entry: ClientIntegrationConnection | undefined, canManage = true, onChanged = vi.fn()) {
  await act(async () => {
    root.render(<FbitsIntegrationPanel entry={entry} canManage={canManage} onChanged={onChanged} />);
  });
  return onChanged;
}

function button(text: string): HTMLButtonElement | undefined {
  return [...document.querySelectorAll("button")].find((item) => item.textContent === text);
}

async function click(target: HTMLElement | undefined) {
  await act(async () => {
    target?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

async function typeToken(value: string) {
  const input = document.querySelector('input[type="password"]') as HTMLInputElement;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function submitForm() {
  await act(async () => {
    (document.getElementById("fbits-connect-form") as HTMLFormElement).requestSubmit();
    await Promise.resolve();
  });
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  Object.values(api).forEach((fn) => fn.mockReset());
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("FbitsIntegrationPanel", () => {
  it("FBITS deixa de estar em 'Em breve'", () => {
    const fbits = INTEGRATION_REGISTRY.find((item) => item.id === "fbits");
    expect(fbits?.availability).toBe("available");
  });

  it("conecta com token em campo de senha e nunca volta a exibi-lo", async () => {
    api.connectFbits.mockResolvedValue({ ok: true, connection: { id: "fbits-curavino" } });
    const onChanged = await render(undefined);

    await click(button("Conectar FBITS"));
    const input = document.querySelector('input[type="password"]') as HTMLInputElement;
    expect(input).toBeTruthy();
    expect(input.autocomplete).toBe("off");

    await typeToken(TOKEN);
    await submitForm();

    expect(api.connectFbits).toHaveBeenCalledWith(TOKEN);
    expect(onChanged).toHaveBeenCalled();
    expect(document.body.innerHTML).not.toContain(TOKEN);
    expect(document.querySelector('input[type="password"]')).toBeNull();
    expect(container.textContent).toContain("últimos 90 dias");
  });

  it("token inválido mostra erro sanitizado e limpa o campo", async () => {
    api.connectFbits.mockRejectedValue(new Error("Token FBITS inválido ou sem permissão para consultar pedidos."));
    const onChanged = await render(undefined);
    await click(button("Conectar FBITS"));
    await typeToken(TOKEN);
    await submitForm();

    expect(document.body.textContent).toContain("Token FBITS inválido");
    expect((document.querySelector('input[type="password"]') as HTMLInputElement).value).toBe("");
    expect(document.body.innerHTML).not.toContain(TOKEN);
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("conectada: sincronizar agora e desconectar", async () => {
    api.syncFbitsConnection.mockResolvedValue({ ok: true, scheduled: true });
    api.disconnectFbitsConnection.mockResolvedValue({ ok: true });
    const onChanged = await render(connectedEntry);

    expect(button("Conectar FBITS")).toBeUndefined();
    await click(button("Sincronizar agora"));
    expect(api.syncFbitsConnection).toHaveBeenCalledTimes(1);

    await click(button("Desconectar"));
    expect(api.disconnectFbitsConnection).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("dados já importados foram preservados");
    expect(onChanged).toHaveBeenCalledTimes(2);
  });

  it("perfil sem gestão não consegue acionar a integração", async () => {
    await render(undefined, false);
    expect(button("Conectar FBITS")?.disabled).toBe(true);
    await render(connectedEntry, false);
    expect(button("Sincronizar agora")?.disabled).toBe(true);
    expect(button("Desconectar")?.disabled).toBe(true);
  });
});
