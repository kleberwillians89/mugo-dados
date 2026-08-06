import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import StatusBadge from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders the label and the tone class for each semantic state", () => {
    const cases: Array<[Parameters<typeof StatusBadge>[0]["tone"], string]> = [
      ["success", "Sincronizado"],
      ["info", "Atualizando…"],
      ["warning", "Configuração necessária"],
      ["error", "Token expirado"],
      ["neutral", "Desconectado"],
    ];
    for (const [tone, label] of cases) {
      const markup = renderToStaticMarkup(<StatusBadge tone={tone} label={label} />);
      expect(markup).toContain(label);
      expect(markup).toContain(`is-${tone}`);
    }
  });
});
