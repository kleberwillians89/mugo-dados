// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { getClientBrand, getIntegrationPlatformBrand, PLATFORM_LOGOS } from "../app/brandRegistry";
import { BrandLogo, ClientLogo, PlatformLogo } from "./BrandLogo";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe("brand registry", () => {
  it("maps known clients without hardcoding Amalie in the component", () => {
    expect(getClientBrand("amalie").logo).toBe("/clients/amalie.png");
    expect(getClientBrand("santo-circuito").logo).toBe("/clients/santocircuito.png");
    expect(renderToStaticMarkup(<ClientLogo clientId="roove" />)).toContain("/clients/roove.png");
  });

  it("maps platform assets through PlatformLogo", () => {
    expect(renderToStaticMarkup(<PlatformLogo platform="instagram" />)).toContain("/platforms/instagram.png");
  });

  it("centralizes the exact integration logo mapping", () => {
    expect(PLATFORM_LOGOS[getIntegrationPlatformBrand("meta")!]).toBe("/platforms/meta.png");
    expect(PLATFORM_LOGOS[getIntegrationPlatformBrand("ga4")!]).toBe("/platforms/googleads.png");
    expect(PLATFORM_LOGOS[getIntegrationPlatformBrand("google_ads")!]).toBe("/platforms/googleads.png");
    expect(PLATFORM_LOGOS[getIntegrationPlatformBrand("shopify")!]).toBe("/platforms/ecommerce.png");
    expect(PLATFORM_LOGOS[getIntegrationPlatformBrand("fbits")!]).toBe("/platforms/ecommerce.png");
    expect(PLATFORM_LOGOS[getIntegrationPlatformBrand("merchant_center")!]).toBe("/platforms/googlemerchant.png");
    expect(PLATFORM_LOGOS[getIntegrationPlatformBrand("tiktok")!]).toBe("/platforms/tiktok.png");
    expect(PLATFORM_LOGOS[getIntegrationPlatformBrand("pinterest")!]).toBe("/platforms/pinterest.png");
  });
});

describe("BrandLogo fallback", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("keeps an accessible textual fallback after an image error", async () => {
    await act(async () => root.render(<BrandLogo src="/missing.png" alt="Logo Cliente" fallback="LC" />));
    const image = container.querySelector("img") as HTMLImageElement;
    await act(async () => image.dispatchEvent(new Event("error")));
    expect(container.textContent).toBe("LC");
    expect(container.querySelector('[aria-label="Logo Cliente"]')).toBeTruthy();
  });
});
