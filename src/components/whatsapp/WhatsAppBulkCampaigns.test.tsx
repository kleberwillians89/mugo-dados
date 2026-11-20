// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  listWhatsAppTemplates: vi.fn(), listWhatsAppCampaignDrafts: vi.fn(), previewWhatsAppCampaignAudience: vi.fn(),
  getWhatsAppContactImportStatus: vi.fn(), sendWhatsAppCampaign: vi.fn(), createWhatsAppCampaignDraft: vi.fn(),
  preflightWhatsAppCampaignTemplate: vi.fn(), importExistingCommerceContacts: vi.fn(), importExistingWhatsAppConversations: vi.fn(),
  cancelWhatsAppCampaign: vi.fn(), getWhatsAppCampaignReport: vi.fn(),
}));
vi.mock("../../app/whatsapp", () => api);
vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => "roove" }));
vi.mock("../../app/artUpload", () => ({ uploadArt: vi.fn() }));

import WhatsAppBulkCampaigns from "./WhatsAppBulkCampaigns";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
const btn = (text: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.trim() === text) as HTMLButtonElement;
const DRAFT = { id: "11111111-1111-1111-1111-111111111111", name: "Black Friday", template_name: "bf", language: "pt_BR",
  status: "draft", simulated_count: 0, created_at: "2026-11-20T10:00:00Z", audience_provider: "all" };

beforeEach(() => {
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
  api.listWhatsAppTemplates.mockResolvedValue({ templates: [] });
  api.listWhatsAppCampaignDrafts.mockResolvedValue({ drafts: [DRAFT] });
  api.previewWhatsAppCampaignAudience.mockResolvedValue({ ok: true, total_contacts: 900, consent_claimed_count: 0,
    consent_verified_count: 10, sendable_count: 850, truncated: false, reason: "ok" });
  api.getWhatsAppContactImportStatus.mockResolvedValue({ total: 900, by_provider: {}, truncated: false });
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

describe("Disparos em massa", () => {
  it("mostra envio liberado, quantos recebem e envia depois de confirmar o risco", async () => {
    api.sendWhatsAppCampaign.mockResolvedValue({ ok: true, status: "queued", scheduled_at: null, recipients_count: 850 });
    await act(async () => { root.render(<WhatsAppBulkCampaigns />); });
    await act(async () => {});
    expect(host.textContent).toContain("Envio liberado");
    expect(host.textContent).toContain("850");
    await act(async () => { btn("Enviar ou agendar").click(); });
    expect(host.querySelector('[role="dialog"]')?.textContent).toContain("bloquear o WhatsApp da marca");
    expect(api.sendWhatsAppCampaign).not.toHaveBeenCalled();
    await act(async () => { btn("Enviar agora").click(); });
    expect(api.sendWhatsAppCampaign).toHaveBeenCalledWith(DRAFT.id, null);
    expect(host.textContent).toContain("Na fila para 850 contatos");
  });

  it("mostra o andamento de uma campanha enviada em parte e oferece retomar", async () => {
    api.listWhatsAppCampaignDrafts.mockResolvedValue({ drafts: [{ ...DRAFT, status: "partial", sent_count: 700, recipients_count: 850,
      failed_count: 140, skipped_count: 10, last_error: "Número sem WhatsApp" }] });
    await act(async () => { root.render(<WhatsAppBulkCampaigns />); });
    await act(async () => {});
    expect(host.textContent).toContain("700 enviadas de 850 · 140 falharam · 10 pediram para sair");
    expect(btn("Retomar envio")).toBeTruthy();
  });

  it("agenda e mostra o resultado de uma campanha enviada", async () => {
    api.listWhatsAppCampaignDrafts.mockResolvedValue({ drafts: [{ ...DRAFT, status: "sent", sent_count: 800 }] });
    api.getWhatsAppCampaignReport.mockResolvedValue({ ok: true, sent: 800, failed: 0, skipped: 0, replied: 40, reply_rate: 5,
      buyers: 12, orders: 13, revenue: 2400, sales_available: true, window: "2026-11-10 a 2026-11-17" });
    await act(async () => { root.render(<WhatsAppBulkCampaigns />); });
    await act(async () => {});
    await act(async () => { btn("Ver resultado").click(); });
    expect(host.textContent).toContain("40 responderam (5%)");
    expect(host.textContent).toContain("12 compraram em 7 dias");
  });
});
