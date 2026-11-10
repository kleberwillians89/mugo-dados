import { describe, expect, it } from "vitest";
import { dmEvents } from "../../supabase/functions/_shared/instagram-dm";

const entry = (messaging: unknown[]) => ({ object: "instagram", entry: [{ id: "1784", time: 1, messaging }] });

describe("webhook do Direct do Instagram", () => {
  it("mensagem recebida vira 'in' com o IGSID da pessoa", () => {
    const [event] = dmEvents(entry([{ sender: { id: "555" }, recipient: { id: "1784" }, timestamp: 1762800000000, message: { mid: "m1", text: " oi! " } }]));
    expect(event).toMatchObject({ igUserId: "1784", senderId: "555", mid: "m1", direction: "in", text: "oi!" });
    expect(event.at).toBe(new Date(1762800000000).toISOString());
  });

  it("eco do que a marca mandou vira 'out' e a pessoa é o destinatário", () => {
    const [event] = dmEvents(entry([{ sender: { id: "1784" }, recipient: { id: "555" }, timestamp: 1, message: { mid: "m2", text: "Olá", is_echo: true } }]));
    expect(event).toMatchObject({ senderId: "555", direction: "out" });
  });

  it("anexo sem texto ganha rótulo; leitura, reação e apagada ficam de fora", () => {
    const events = dmEvents(entry([
      { sender: { id: "555" }, recipient: { id: "1784" }, timestamp: 1, message: { mid: "m3", attachments: [{ type: "story_mention" }] } },
      { sender: { id: "555" }, recipient: { id: "1784" }, timestamp: 1, read: { mid: "m3" } },
      { sender: { id: "555" }, recipient: { id: "1784" }, timestamp: 1, message: { mid: "m4", is_deleted: true } },
    ]));
    expect(events.map((e) => e.text)).toEqual(["[menção no story]"]);
  });

  it("ignora outro objeto (WhatsApp, página)", () => {
    expect(dmEvents({ object: "whatsapp_business_account", entry: [] })).toEqual([]);
  });
});
