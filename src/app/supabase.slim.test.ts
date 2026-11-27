// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { authStorageKey, createSlimClient } from "./supabase";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

describe("cliente Supabase enxuto (só login e consultas)", () => {
  it("guarda a sessão na mesma chave que o supabase-js usava: ninguém é deslogado", () => {
    expect(authStorageKey("https://abcdefgh.supabase.co")).toBe("sb-abcdefgh-auth-token");
    expect(authStorageKey("https://abcdefgh.supabase.co/")).toBe("sb-abcdefgh-auth-token");
  });

  it("consulta com o token da sessão salva e a chave pública", async () => {
    const session = { access_token: "token-da-sessao", refresh_token: "r", token_type: "bearer", expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600, user: { id: "u1", aud: "authenticated", app_metadata: {}, user_metadata: {}, created_at: "" } };
    localStorage.setItem("sb-abcdefgh-auth-token", JSON.stringify(session));
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } }));
    const client = createSlimClient("https://abcdefgh.supabase.co", "chave-anon");
    const { data: auth } = await client.auth.getSession();
    expect(auth.session?.access_token).toBe("token-da-sessao");
    await client.from("client_memberships").select("client_id,role").eq("user_id", "u1");
    const [url, init] = fetchMock.mock.calls.find(([u]) => String(u).includes("/rest/v1/"))!;
    expect(String(url)).toContain("https://abcdefgh.supabase.co/rest/v1/client_memberships?select=client_id%2Crole&user_id=eq.u1");
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.get("Authorization")).toBe("Bearer token-da-sessao");
    expect(headers.get("apikey")).toBe("chave-anon");
  });
});
