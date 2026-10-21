import {describe, expect, it, vi} from "vitest";
import {diagnosticResponse} from "./diagnosticMocks";
const options = {clientId: "tenant-a", name: "Empresa fictícia", start: "2026-10-01", end: "2026-10-20", scenario: "padrao", viewer: false, refresh: ""};
const url = (path: string) => new URL(`http://localhost${path}`);
const status = "/api/clients/tenant-a/data-refresh/meta/status";
describe("diagnóstico local sem provider", () => {
  it("GA4 e conexão FBITS usam fixtures coerentes com a empresa e o período", async () => {
    const response = await diagnosticResponse(url("/api/google/ga4/report"), "GET", options);
    const report = await response!.json();
    expect(response!.status).toBe(200);
    expect(report.client_id).toBe(options.clientId);
    expect(report.period.start).toBe(options.start);
    expect(report.summary.sessions).toBeGreaterThan(0);
    expect(report.channels.length).toBeGreaterThan(0);
    expect((await diagnosticResponse(url("/api/google/ga4/report"), "GET", {...options, scenario: "erro"}))!.status).toBe(502);
    const stories = await diagnosticResponse(url("/api/ig/stories"), "GET", options);
    expect(stories!.status).toBe(200);
    expect((await stories!.json()).stories).toEqual([]);
    const {reviewGenericConnections} = await import("./fixtures");
    expect(reviewGenericConnections("vinhos", "Empresa fictícia").connections.some(row => row.provider === "fbits")).toBe(true);
    expect(reviewGenericConnections("roove", "Empresa fictícia").connections.some(row => row.provider === "fbits")).toBe(false);
  });
  it("retorna leituras de Inteligência consistentes com tenant e período", async () => {
    const context = await (await diagnosticResponse(url("/api/intelligence/context"), "GET", options))!.json();
    const latest = await (await diagnosticResponse(url("/api/intelligence/latest"), "GET", options))!.json();
    expect(context.snapshot.client.id).toBe(options.clientId);
    expect(context.snapshot.period.end).toBe(options.end);
    expect(latest.analysis.client_id).toBe(options.clientId);
    expect(latest.analysis.metrics_snapshot).toEqual(context.snapshot.metrics);
    const other = await (await diagnosticResponse(url("/api/intelligence/context"), "GET", {...options, clientId: "tenant-b"}))!.json();
    expect(other.snapshot.client.id).toBe("tenant-b");
    expect(context.snapshot.client.id).toBe("tenant-a");
  });
  it("erro, vazio e tentativa de gerar são locais e explícitos", async () => {
    expect((await diagnosticResponse(url("/api/intelligence/context"), "GET", {...options, scenario: "erro"}))!.status).toBe(502);
    const empty = await (await diagnosticResponse(url("/api/intelligence/latest"), "GET", {...options, scenario: "sem-dados"}))!.json();
    expect(empty.analysis).toBeNull();
    expect((await diagnosticResponse(url("/api/intelligence/analyses"), "POST", options))!.status).toBe(502);
  });
  it("carregamento simulado termina sem deixar promise eterna", async () => {
    vi.useFakeTimers();
    try {
      const pending = diagnosticResponse(url("/api/intelligence/context"), "GET", {...options, scenario: "carregando"});
      await vi.advanceTimersByTimeAsync(3000);
      expect((await pending)!.status).toBe(200);
    } finally { vi.useRealTimers(); }
  });
  it("viewer não ganha refresh nem status de mutação", async () => {
    expect((await diagnosticResponse(url(status), "GET", {...options, viewer: true}))!.status).toBe(403);
    expect((await diagnosticResponse(url(status.replace("/status", "")), "POST", {...options, viewer: true}))!.status).toBe(403);
  });
  it("estado em andamento e cooldown não inventam horário de sucesso", async () => {
    const healthUrl = url("/api/clients/tenant-a/data-health");
    const initial = await (await diagnosticResponse(healthUrl, "GET", options))!.json();
    const running = await (await diagnosticResponse(healthUrl, "GET", {...options, refresh: "running"}))!.json();
    expect(running.sources[0].last_successful_sync_at).toBe(initial.sources[0].last_successful_sync_at);
    expect(running.sources[0].state).toBe("updating");
    const lease = await (await diagnosticResponse(url(status), "GET", {...options, refresh: "running"}))!.json();
    expect(lease.running).toBe(true);
    expect(lease.client_id).toBe(options.clientId);
    const cooldown = await (await diagnosticResponse(url(status), "GET", {...options, refresh: "cooldown"}))!.json();
    expect(cooldown.cooldown_seconds).toBeGreaterThan(0);
    const noSuccess = await (await diagnosticResponse(healthUrl, "GET", {...options, scenario: "sem-dados"}))!.json();
    expect(noSuccess.sources[0].last_successful_sync_at).toBeNull();
  });
  it("refresh administrador falha de forma simulada; endpoint alheio não é implementado", async () => {
    expect((await diagnosticResponse(url(status.replace("/status", "")), "POST", options))!.status).toBe(503);
    expect(await diagnosticResponse(url("/api/anything"), "GET", options)).toBeNull();
  });
});
