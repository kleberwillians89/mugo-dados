// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const team = vi.hoisted(() => ({
  getTeamCatalog: vi.fn(async () => ({ modules: [], permissions: [], presets: [{ code: "visualizacao", label: "Visualização", view_all: true, access_total: false, codes: [] }] })),
  listTeamMembers: vi.fn(async () => ({ items: [] as unknown[] })),
  getTeamDepartments: vi.fn(async () => ({ catalog: [], by_user: {} })),
  searchLinkableAccounts: vi.fn(), linkExistingMember: vi.fn(), createTeamMember: vi.fn(), removeTeamMember: vi.fn(),
}));
vi.mock("../app/team", async (original) => ({ ...(await original<typeof import("../app/team")>()), ...team }));
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "m2", getActiveClientName: () => "M2" }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("../components/data/PageHeader", () => ({ default: ({ title }: { title: string }) => <h1>{title}</h1> }));
vi.mock("../components/Drawer", () => ({ default: ({ open, children, title }: { open: boolean; children: React.ReactNode; title: string }) =>
  (open ? <div data-drawer={title}>{children}</div> : null) }));

import Users from "./Users";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); vi.useRealTimers(); });
const show = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); await act(async () => {}); };
const button = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === label) as HTMLButtonElement | undefined;
const type = async (input: HTMLInputElement, value: string) => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
  await act(async () => { input.dispatchEvent(new Event("input", { bubbles: true })); });
};

describe("Usuários: vincular conta existente (briefing integrado, PR 1)", () => {
  it("só a equipe Mugô vê o botão", async () => {
    await show(<Users canManage isTeam={false} />);
    expect(button("Adicionar usuário existente")).toBeUndefined();
    expect(button("+ Novo usuário")).toBeTruthy();
  });

  it("busca a Liliu e vincula sem pedir senha", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    team.searchLinkableAccounts.mockResolvedValue({ items: [{ user_id: "u-liliu", name: "Liliu", login: "liliu@mugo.ag", team: true }] });
    team.linkExistingMember.mockResolvedValue({ user_id: "u-liliu", team_member: true, role: "account_manager" });
    await show(<Users canManage isTeam />);
    await act(async () => { button("Adicionar usuário existente")!.click(); });
    const drawer = host.querySelector('[data-drawer="Adicionar usuário existente"]')!;
    expect(drawer.querySelector('input[type="password"]')).toBeNull();
    await type(drawer.querySelector("input")!, "liliu");
    await act(async () => { vi.advanceTimersByTime(400); }); await act(async () => {});
    expect(team.searchLinkableAccounts).toHaveBeenCalledWith("liliu");
    expect(drawer.textContent).toContain("Equipe Mugô");
    await act(async () => { button("Vincular")!.click(); }); await act(async () => {});
    expect(team.linkExistingMember).toHaveBeenCalledWith({ user_id: "u-liliu" });
    expect(host.textContent).toContain("Liliu agora tem acesso a M2 e já aparece entre os responsáveis");
  });

  it("conta que já existia: não mostra a senha digitada como nova", async () => {
    team.createTeamMember.mockResolvedValue({ user_id: "u1", login: "ana@ruah.com", account_created: false, password_applied: false });
    await show(<Users canManage isTeam />);
    await act(async () => { button("+ Novo usuário")!.click(); });
    const form = host.querySelector("form")!;
    const [, login] = form.querySelectorAll("input");
    await type(login as HTMLInputElement, "ana@ruah.com");
    await act(async () => { form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); }); await act(async () => {});
    expect(host.textContent).toContain("já tinha conta: foi vinculada a M2 sem alterar a senha");
    expect(host.textContent).not.toContain("esta senha não aparece de novo");
  });
});
