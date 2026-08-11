// @vitest-environment jsdom

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import Login from "./Login";

describe("Login platform branding", () => {
  it("renders every integration with the centralized real logo mapping", () => {
    const markup = renderToStaticMarkup(<Login />);
    expect(markup).toContain("/platforms/meta.png");
    expect(markup.match(/\/platforms\/googleads\.png/g)).toHaveLength(2);
    expect(markup.match(/\/platforms\/ecommerce\.png/g)).toHaveLength(2);
    expect(markup).toContain("/platforms/googlemerchant.png");
    expect(markup).toContain("/platforms/tiktok.png");
    expect(markup).toContain("/platforms/pinterest.png");
  });
});
