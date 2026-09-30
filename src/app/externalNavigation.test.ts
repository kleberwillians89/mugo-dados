import { afterEach, describe, expect, it, vi } from "vitest";
import { navigateToExternalAuthorization } from "./externalNavigation";

describe("navigateToExternalAuthorization", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("navega para a authorization_url devolvida pelo OAuth", () => {
    const assign = vi.fn();
    vi.stubGlobal("window", { location: { assign } });

    navigateToExternalAuthorization("https://0vi1gx-ja.myshopify.com/admin/oauth/authorize?state=signed");

    expect(assign).toHaveBeenCalledWith(
      "https://0vi1gx-ja.myshopify.com/admin/oauth/authorize?state=signed"
    );
  });
});
