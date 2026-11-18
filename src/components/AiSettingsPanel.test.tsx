// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AiSettingsPanel from "./AiSettingsPanel";

const api = vi.hoisted(() => ({ getAiSettings: vi.fn(), saveAiSettings: vi.fn(), revokeAiCredential: vi.fn() }));
let tenant = "tenant-a";
vi.mock("../app/api", async () => ({ ...api, ApiError: class ApiError extends Error {} }));
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => tenant }));

const settings = (client_id = tenant) => ({ client_id, mode: "platform_managed", provider: "openai", model: "gpt-4.1-mini",
  credential_status: "platform", has_credential: false, credential_updated_at: null, validated_at: null });

describe("AiSettingsPanel", () => {
  beforeEach(() => { tenant = "tenant-a"; api.getAiSettings.mockReset(); api.saveAiSettings.mockReset(); api.revokeAiCredential.mockReset(); });

  it("does not render or return a full credential", async () => {
    api.getAiSettings.mockResolvedValue({ settings: settings(), models: [{ provider: "openai", model: "gpt-4.1-mini", max_output_tokens: 32768 }] });
    const host = document.createElement("div"); const root = createRoot(host);
    await act(async () => { root.render(<AiSettingsPanel />); });
    expect(host.textContent).toContain("Gerenciada pela Mugô");
    expect(host.textContent).not.toContain("sk-");
    root.unmount();
  });

  it("discards a response from the previous tenant", async () => {
    let release!: (value: unknown) => void;
    api.getAiSettings.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    const host = document.createElement("div"); const root = createRoot(host);
    await act(async () => { root.render(<AiSettingsPanel />); });
    tenant = "tenant-b";
    await act(async () => { release({ settings: settings("tenant-a"), models: [] }); });
    expect(host.textContent).toContain("Carregando configuração");
    root.unmount();
  });
});
