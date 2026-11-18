import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { messageText, validSignature } from "../../supabase/functions/_shared/whatsapp-cloud";
import { resolveMetaWebhookApp, webhookMatchesNumber } from "../../supabase/functions/_shared/whatsapp-meta-app";
import { extractOriginTouch, phoneKey } from "../../supabase/functions/_shared/whatsapp-origin";

const webhook = readFileSync(new URL("../../supabase/functions/whatsapp-webhook/index.ts", import.meta.url), "utf8");
const migration = readFileSync(new URL("../../supabase/migrations/20261208_000087_whatsapp_native.sql", import.meta.url), "utf8");

describe("webhook do WhatsApp nativo", () => {
  it("separa GET e assinatura POST por Meta App, sem fallback para Mugô", () => {
    const secrets = new Map([
      ["WHATSAPP_VERIFY_TOKEN", "legacy-verify"],
      ["WHATSAPP_APP_SECRET", "legacy-secret"],
      ["META_APP_1161210926623351_WEBHOOK_VERIFY_TOKEN", "roove-verify"],
      ["META_APP_1161210926623351_APP_SECRET", "roove-secret"],
    ]);
    const env = (key: string) => secrets.get(key);
    const legacy = resolveMetaWebhookApp(new URL("https://example.test/webhook"), env)!;
    const roove = resolveMetaWebhookApp(new URL("https://example.test/webhook?meta_app_id=1161210926623351"), env)!;
    expect(legacy).toMatchObject({ legacy: true, verifyToken: "legacy-verify", appSecret: "legacy-secret" });
    expect(roove).toMatchObject({ legacy: false, appId: "1161210926623351", verifyToken: "roove-verify", appSecret: "roove-secret" });
    expect(resolveMetaWebhookApp(new URL("https://example.test/webhook?meta_app_id="), env)).toBeNull();
    expect(resolveMetaWebhookApp(new URL("https://example.test/webhook?meta_app_id=99999"), env)).toBeNull();
    const onlyVerify = resolveMetaWebhookApp(new URL("https://example.test/webhook?meta_app_id=1161210926623351"),
      (key: string) => key.endsWith("WEBHOOK_VERIFY_TOKEN") ? "roove-verify" : undefined);
    expect(onlyVerify?.verifyToken).toBe("roove-verify");
    expect(onlyVerify?.appSecret).toBe("");
  });

  it("aceita apenas WABA e Meta App do numero, com legado separado", () => {
    const env = (key: string) => ({
      WHATSAPP_VERIFY_TOKEN: "legacy", WHATSAPP_APP_SECRET: "legacy-secret",
      META_APP_1161210926623351_WEBHOOK_VERIFY_TOKEN: "roove",
    } as Record<string, string>)[key];
    const legacy = resolveMetaWebhookApp(new URL("https://test.local/"), env)!;
    const roove = resolveMetaWebhookApp(new URL("https://test.local/?meta_app_id=1161210926623351"), env)!;
    const legacyNumber = { waba_id: "111111", meta_app_id: null };
    const rooveNumber = { waba_id: "1491824329400600", meta_app_id: "1161210926623351" };
    expect(webhookMatchesNumber(roove, rooveNumber, rooveNumber.waba_id)).toBe(true);
    expect(webhookMatchesNumber(roove, rooveNumber, "111111")).toBe(false);
    expect(webhookMatchesNumber(roove, legacyNumber, legacyNumber.waba_id)).toBe(false);
    expect(webhookMatchesNumber(legacy, rooveNumber, rooveNumber.waba_id)).toBe(false);
    expect(webhookMatchesNumber(legacy, legacyNumber, legacyNumber.waba_id)).toBe(true);
    expect(webhook).toContain("if (foreign && signature && app.legacy) inBackground(forward(raw, signature))");
  });

  it("aceita só a assinatura da Meta com o segredo do app", async () => {
    const raw = '{"entry":[]}';
    const sig = `sha256=${createHmac("sha256", "segredo").update(raw).digest("hex")}`;
    expect(await validSignature(raw, sig, "segredo")).toBe(true);
    expect(await validSignature(raw, sig, "outro")).toBe(false);
    expect(await validSignature(`${raw} `, sig, "segredo")).toBe(false);
    expect(await validSignature(raw, null, "segredo")).toBe(false);
    expect(await validSignature(raw, sig, "")).toBe(false);
  });

  it("lê texto, botões, mídia com legenda e ignora reação", () => {
    expect(messageText({ type: "text", text: { body: "Oi" } })).toBe("Oi");
    expect(messageText({ type: "button", button: { text: "Quero" } })).toBe("Quero");
    expect(messageText({ type: "interactive", interactive: { list_reply: { title: "50 ml" } } })).toBe("50 ml");
    expect(messageText({ type: "image", image: { caption: "esse" } })).toBe("[imagem] esse");
    expect(messageText({ type: "reaction" })).toBe("");
  });

  it("mesma origem e mesma chave de telefone dos CRMs", async () => {
    expect(extractOriginTouch({ source_type: "ad", source_id: "120", ctwa_clid: "c" }, "oi")).toMatchObject({ ad_id: "120", ctwa_clid: "c" });
    expect(await phoneKey("5511993161161", { international: true })).toBe("8da0ce4f7795d49d1331629bcee13398");
  });

  it("repassa ao CRM só o que não é número do MUGOVERSO, com a assinatura original", () => {
    expect(webhook).toMatch(/if \(!number\) \{ if \(app\.legacy\) foreign = true; continue \}/);
    expect(webhook).toMatch(/'x-hub-signature-256': signature/);
    expect(webhook).toMatch(/if \(foreign && signature && app\.legacy\) inBackground\(forward\(raw, signature\)\)/);
    expect(webhook).toMatch(/return text\('unauthorized', 401\)/);
    // Banco falhou → 500 para a Meta reenviar; número desligado não vai para o CRM.
    expect(webhook).toMatch(/return failed \? text\('retry', 500\) : text\('ok'\)/);
    expect(webhook).toMatch(/if \(number\.status !== 'active'\) \{ inactive \+= 1; continue \}/);
    expect(webhook).toContain('inbound_events: inboundEvents, status_events: statusEvents, unmatched, inactive');
  });

  it("banco: só service role, token nunca exposto e recebimento idempotente", () => {
    expect(migration).toMatch(/revoke all on public\.whatsapp_numbers, public\.whatsapp_threads, public\.whatsapp_messages, public\.whatsapp_origin_touches from anon, authenticated/);
    expect(migration).toMatch(/unique \(number_id, provider_message_id\)/);
    // A mensagem entra antes da conversa ser atualizada: reenvio não conta "não lida" em dobro.
    const fn = migration.slice(migration.indexOf("create or replace function public.whatsapp_receive_v1"));
    expect(fn.indexOf("insert into public.whatsapp_messages")).toBeLessThan(fn.indexOf("unread_count = t.unread_count + 1"));
    expect(fn).toMatch(/if v_message is null then return jsonb_build_object\('status', 'duplicate'/);
    expect(fn).toMatch(/if v_thread_client is distinct from v_client then/);
  });
});
