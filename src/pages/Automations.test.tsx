// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getOverview: vi.fn(), updateAutomation: vi.fn(), syncCatalog: vi.fn(), getOutbox: vi.fn(), getResponses: vi.fn(), getUsage: vi.fn(),
  processQueue: vi.fn(), simulateAutomation: vi.fn(), listTeam: vi.fn(), saveTeamMember: vi.fn(), deleteTeamMember: vi.fn(),
  calendarStart: vi.fn(), listGoogleCalendars: vi.fn(), selectGoogleCalendar: vi.fn(), syncGoogleCalendar: vi.fn(), listAllMeetings: vi.fn(),
}));
vi.mock("../app/automations", async (original) => ({ ...(await original<typeof import("../app/automations")>()), ...api }));
import Automations from "./Automations";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

const state = (over = {}) => ({ automation_enabled: true, template_approved: true, integration_configured: true, operational: false, simulated_only: true, problems: [], ...over });
const base = { language: "pt_BR", expected_category: "UTILITY", schedule: {}, recipients: {}, crm_reference: null, notes: null };
const overview = {
  flags: { send_enabled: false, mugozap_configured: true, catalog_configured: true, catalog_synced_at: "2026-10-30T12:00:00Z",
           calendar: { status: "desconectado", account_email: null, calendar_id: null, calendar_summary: null, last_sync_at: null, last_error: null, channel_expires_at: null, webhook: false } },
  automations: [
    { ...base, key: "reuniao_interna", template_name: "mugo_reuniao_interna", owner: "dados", audience: "equipe", trigger_label: "Reunião interna agendada",
      automation_enabled: true, lead_minutes: 1440, variable_map: ["nome", "titulo", "data", "hora"],
      template: { category: "UTILITY", language: "pt_BR", status: "APPROVED", rejected_reason: null, body_param_count: 4, button_url_dynamic: false, quick_replies: [], synced_at: "" },
      state: state() },
    { ...base, key: "pagamento_confirmado", template_name: "mugo_pagamento_confirmado", owner: "crm", audience: "cliente", trigger_label: "Pagamento confirmado",
      automation_enabled: true, lead_minutes: null, variable_map: [], crm_reference: "asaas-webhook", template: null,
      state: state({ template_approved: false, integration_configured: false, simulated_only: false, problems: ["Disparada pelo CRM; o Dados não envia para não duplicar."] }) },
  ],
  other_templates: [],
};

describe("Central de Automações", () => {
  it("mostra modo simulado, os quatro estados separados e as automações do CRM sem ações", async () => {
    api.getOverview.mockResolvedValue(overview);
    await act(async () => { root.render(<Automations />); });
    await act(async () => {});
    const text = host.textContent || "";
    expect(text).toContain("Modo simulado (nenhuma mensagem sai)");
    for (const label of ["Habilitada", "Aprovado na Meta", "Integração", "Só simulação"]) expect(text).toContain(label);
    expect(text).toContain("Disparada pelo CRM");
    expect(text).toContain("Disparadas pelo CRM Mugô");
    const crmRow = [...host.querySelectorAll("tr")].find((tr) => tr.textContent?.includes("Pagamento confirmado"))!;
    expect(crmRow.textContent).not.toContain("Desativar");
    expect(crmRow.textContent).not.toContain("Simular");
  });

  it("simulação nunca envia e mostra o texto", async () => {
    api.getOverview.mockResolvedValue(overview);
    api.simulateAutomation.mockResolvedValue({ automation: "reuniao_interna", template_name: "mugo_reuniao_interna", would_send: true, blocked_reason: null, text: "Olá, Ana!", real_send: false });
    await act(async () => { root.render(<Automations />); });
    await act(async () => {});
    const simulate = [...host.querySelectorAll("button")].find((b) => b.textContent === "Simular")!;
    await act(async () => { simulate.click(); });
    const form = document.querySelector(".autoForm") as HTMLFormElement;
    await act(async () => { form.requestSubmit(); });
    expect(api.simulateAutomation).toHaveBeenCalledWith("reuniao_interna", { nome: "", titulo: "", data: "", hora: "" });
    expect(document.body.textContent).toContain("nada foi enviado");
  });
});
