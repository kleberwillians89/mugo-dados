// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
vi.mock("./supabase", () => ({ isLocalAuthEnabled: () => true, getSupabaseBootstrapError: () => null, supabase: null }));
vi.mock("./activeClient", () => ({ getActiveClientId: () => "tenant-a", getActiveClientName: () => "Empresa", getActiveClientConfigurationWarning: () => null }));
import { getIntelligenceConversations, getIntelligenceMessages } from "./api";
afterEach(() => vi.unstubAllGlobals());
it("leituras privadas simultâneas não compartilham promessa indexada apenas pelo tenant", async () => {
  const pending: Array<(response: Response) => void> = [];
  const fetcher = vi.fn(() => new Promise<Response>(resolve => { pending.push(resolve); }));
  vi.stubGlobal("fetch", fetcher);
  const listA = getIntelligenceConversations(), listB = getIntelligenceConversations();
  await Promise.resolve(); await Promise.resolve();
  expect(fetcher).toHaveBeenCalledTimes(2);
  pending[0](new Response(JSON.stringify({ ok: true, items: [{ user_id: "user-a" }], has_more: false })));
  pending[1](new Response(JSON.stringify({ ok: true, items: [{ user_id: "user-b" }], has_more: false })));
  expect((await listA).items[0].user_id).toBe("user-a"); expect((await listB).items[0].user_id).toBe("user-b");
  pending.length = 0;
  const messagesA = getIntelligenceMessages("thread"), messagesB = getIntelligenceMessages("thread");
  await Promise.resolve(); await Promise.resolve();
  expect(fetcher).toHaveBeenCalledTimes(4);
  for (const finish of pending) finish(new Response(JSON.stringify({ ok: true, conversation: { id: "thread" }, messages: [] })));
  await Promise.all([messagesA, messagesB]);
});
