import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { messageText, validSignature } from "../../supabase/functions/_shared/whatsapp-cloud";
import { extractOriginTouch, phoneKey } from "../../supabase/functions/_shared/whatsapp-origin";

const webhook = readFileSync(new URL("../../supabase/functions/whatsapp-webhook/index.ts", import.meta.url), "utf8");
const migration = readFileSync(new URL("../../supabase/migrations/20261208_000087_whatsapp_native.sql", import.meta.url), "utf8");

describe("webhook do WhatsApp nativo", () => {
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
    expect(webhook).toMatch(/if \(!number\) \{ foreign = true; continue \}/);
    expect(webhook).toMatch(/'x-hub-signature-256': signature/);
    expect(webhook).toMatch(/if \(foreign && signature\) inBackground\(forward\(raw, signature\)\)/);
    expect(webhook).toMatch(/return text\('unauthorized', 401\)/);
    // Banco falhou → 500 para a Meta reenviar; número desligado não vai para o CRM.
    expect(webhook).toMatch(/return failed \? text\('retry', 500\) : text\('ok'\)/);
    expect(webhook).toMatch(/if \(number\.status !== 'active'\) continue/);
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
