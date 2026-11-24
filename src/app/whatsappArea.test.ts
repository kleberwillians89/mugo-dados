// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { requestWhatsAppArea, takeWhatsAppArea } from "./newProjectRequest";

afterEach(() => { window.sessionStorage.clear(); window.history.replaceState(null, "", "/"); });

describe("atalho de Lançar campanha para uma área do WhatsApp", () => {
  it("lê o pedido uma vez só e aceita só as áreas conhecidas", () => {
    requestWhatsAppArea("bulk");
    expect(takeWhatsAppArea()).toBe("bulk");
    expect(takeWhatsAppArea()).toBeNull();
    window.history.replaceState(null, "", "/whatsapp?area=models");
    expect(takeWhatsAppArea()).toBe("models");
    window.history.replaceState(null, "", "/whatsapp?area=hack");
    expect(takeWhatsAppArea()).toBeNull();
  });
});
