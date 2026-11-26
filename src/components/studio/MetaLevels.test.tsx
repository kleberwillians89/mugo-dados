// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BuilderOptions, MetaCatalog, MetaStructure } from "../../app/metaAds";
import catalogJson from "./__fixtures__/metaCatalog.json";

vi.mock("../../app/metaAds", () => ({ readAdWhatsappNumbers: vi.fn().mockResolvedValue({ numbers: [] }) }));
import MetaCampaignLevel from "./MetaCampaignLevel";
import MetaAdsetLevel from "./MetaAdsetLevel";
import { ctasFor, locationsFor, normalizeMeta } from "./metaStructure";

/** Gerado de server/services/meta_structure.py (mesmo catálogo que a API devolve). Para regenerar:
 * python3 -c "import sys,json; sys.path.insert(0,'server'); from services import meta_structure as ms; json.dump(ms.catalog(), open('src/components/studio/__fixtures__/metaCatalog.json','w'), ensure_ascii=False, indent=1)" */
const catalog = catalogJson as unknown as MetaCatalog;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
afterEach(() => { host?.remove(); });
const meta = (patch: Partial<MetaStructure> = {}): MetaStructure => normalizeMeta(catalog, {
  objective: "OUTCOME_SALES", special_ad_categories: [], budget_level: "campaign", budget_type: "daily", budget: 50,
  bid_strategy: "LOWEST_COST_WITHOUT_CAP", bid_amount: null, roas_floor: null, conversion_location: "WEBSITE", messaging_apps: [],
  performance_goal: "OFFSITE_CONVERSIONS", conversion_event: null, app: null, lead_form: null, phone_number: null,
  has_end_date: true, use_existing_post: false, ...patch,
});
async function render(node: React.ReactNode) {
  host = document.createElement("div"); document.body.appendChild(host);
  await act(async () => createRoot(host).render(node));
}

describe("Criador igual ao Gerenciador", () => {
  it("Campanha: os 6 objetivos oficiais e o orçamento Advantage+", async () => {
    const onMeta = vi.fn();
    await render(<MetaCampaignLevel catalog={catalog} meta={meta()} name="Black" currency="BRL" onName={vi.fn()} onMeta={onMeta} />);
    const objectives = [...host.querySelectorAll(".metaObjective b")].map((b) => b.textContent);
    expect(objectives).toEqual(["Reconhecimento", "Tráfego", "Engajamento", "Cadastros", "Promoção do app", "Vendas"]);
    expect(host.textContent).toContain("Orçamento da campanha Advantage+");
    expect(host.textContent).toContain("Produtos e serviços financeiros");
    await act(async () => (host.querySelectorAll<HTMLInputElement>('input[name="meta-objective"]')[3]).click());
    expect(onMeta).toHaveBeenCalledWith({ objective: "OUTCOME_LEADS" });
  });

  it("Conjunto: locais da conversão vêm do objetivo e o evento do pixel da conta", async () => {
    const options = { pixels: [{ id: "555", name: "Ruah Pixel", active: true, events_seen: ["PURCHASE"] }], recommended_pixel: "555",
      apps: [], lead_forms: [], whatsapp_numbers: [], preview_formats: [] } as unknown as BuilderOptions;
    await render(<MetaAdsetLevel catalog={catalog} options={options} meta={meta()} startDate="2026-11-27" endDate="2026-12-05"
      pixelId={null} whatsappNumber={null} onMeta={vi.fn()} onDates={vi.fn()} onPixel={vi.fn()} onWhatsapp={vi.fn()} />);
    const locations = [...host.querySelectorAll(".metaLocation")].map((l) => l.textContent);
    expect(locations).toEqual(["Site", "Apps de mensagem", "Ligações"]);
    expect(host.textContent).toContain("Maximizar o número de conversões");
    expect(host.textContent).toContain("Adicionar ao carrinho · sem atividade recente");
    expect(host.textContent).not.toContain("Compra · sem atividade recente");
  });

  it("muda o objetivo e cai na primeira opção válida, como a Meta", () => {
    const m = normalizeMeta(catalog, { ...meta(), objective: "OUTCOME_AWARENESS" });
    expect([m.conversion_location, m.performance_goal, m.conversion_event]).toEqual(["NONE", "REACH", null]);
    expect(locationsFor(catalog, "OUTCOME_APP_PROMOTION", false)).toEqual(["APP"]);
    expect(ctasFor(catalog, meta({ conversion_location: "MESSAGING", messaging_apps: ["WHATSAPP"], performance_goal: "CONVERSATIONS" })))
      .toEqual(["WHATSAPP_MESSAGE"]);
  });
});
