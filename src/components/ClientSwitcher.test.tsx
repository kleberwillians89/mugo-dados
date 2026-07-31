import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SUPABASE_AUTH_OPTIONS } from "../app/supabase";
import ClientSwitcher from "./ClientSwitcher";

describe("session and tenant controls", () => {
  it("keeps the Supabase-managed session persistent and renewable", () => {
    expect(SUPABASE_AUTH_OPTIONS).toEqual({
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    });
  });

  it("renders the selected company with an accessible tenant selector", () => {
    const markup = renderToStaticMarkup(
      <ClientSwitcher
        activeClientId="roove"
        clients={[{ client_id: "roove", name: "Roove", role: "platform_admin" }]}
        onChange={() => {}}
      />
    );
    expect(markup).toContain('aria-label="Selecionar empresa"');
    expect(markup).toContain("Roove");
    expect(markup).toContain("Empresa ativa");
  });

  it("keeps the selector in document flow and gives mobile layout its own row", () => {
    const css = readFileSync(new URL("../styles/App.css", import.meta.url), "utf8");
    expect(css).toMatch(/\.clientSwitcher\{[\s\S]*?position:static/);
    expect(css).toMatch(/@media\(max-width:980px\)[\s\S]*?\.clientSwitcher\{width:100%/);
  });
});
