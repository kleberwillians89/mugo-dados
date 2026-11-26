import type { MetaCatalog, MetaObjective, MetaStructure } from "../../app/metaAds";
import { bidOptions } from "./metaStructure";

/** Ícones simples por conceito (não são os desenhos da Meta; os nomes são os do Gerenciador). */
const ICONS: Record<string, string> = {
  megaphone: "M4 10v4h3l6 4V6L7 10H4zm12-1.5a4 4 0 0 1 0 7",
  cursor: "M6 3l12 7-5 1.5L11 17z",
  chat: "M4 5h16v10H9l-5 4z",
  filter: "M4 5h16l-6 7v6l-4 2v-8z",
  phone: "M8 3h8v18H8zM11 18h2",
  bag: "M5 8h14l-1 12H6zM9 8a3 3 0 0 1 6 0",
};

type Props = {
  catalog: MetaCatalog; meta: MetaStructure; name: string; currency: string; disabled?: boolean;
  onName: (name: string) => void; onMeta: (patch: Partial<MetaStructure>) => void;
};

/** Nível 1 · Campanha: objetivo, categoria especial, orçamento (Advantage+ ou por conjunto) e lance. */
export default function MetaCampaignLevel({ catalog, meta, name, currency, disabled, onName, onMeta }: Props) {
  const toggleSpecial = (key: string, on: boolean) =>
    onMeta({ special_ad_categories: on ? [...meta.special_ad_categories, key] : meta.special_ad_categories.filter((k) => k !== key) });
  const bids = catalog.bid_strategies.filter((b) => bidOptions(meta.performance_goal).includes(b.key));
  const cbo = meta.budget_level === "campaign";
  return <fieldset disabled={disabled} className="metaLevel">
    <legend>Campanha</legend>
    <label className="ds-field">Nome da campanha<input required maxLength={120} value={name} onChange={(e) => onName(e.target.value)} /></label>

    <div className="metaLevelBlock" role="radiogroup" aria-label="Escolha um objetivo da campanha">
      <h3>Escolha um objetivo da campanha</h3>
      <div className="metaObjectives">
        {catalog.objectives.map((o) => <label key={o.key} className={`metaObjective${meta.objective === o.key ? " is-selected" : ""}`}>
          <input type="radio" name="meta-objective" value={o.key} checked={meta.objective === o.key}
            onChange={() => onMeta({ objective: o.key as MetaObjective })} />
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d={ICONS[o.icon] || ICONS.cursor} /></svg>
          <span><b>{o.label}</b><small>{o.hint}</small></span>
        </label>)}
      </div>
    </div>

    <details className="metaLevelBlock" open={meta.special_ad_categories.length > 0}>
      <summary><h3>Categorias especiais de anúncio</h3>
        <small>{meta.special_ad_categories.length ? meta.special_ad_categories.map((k) => catalog.special_categories.find((c) => c.key === k)?.label || k).join(", ") : "Nenhuma categoria declarada"}</small></summary>
      <p className="ds-caption">Declare se os anúncios são sobre produtos e serviços financeiros, emprego, moradia ou questões sociais, eleições ou política. A Meta limita algumas opções de público nessas categorias.</p>
      <div className="metaChecks">
        {catalog.special_categories.map((c) => <label key={c.key} className="metaAdsCheck">
          <input type="checkbox" checked={meta.special_ad_categories.includes(c.key)} onChange={(e) => toggleSpecial(c.key, e.target.checked)} />{c.label}</label>)}
      </div>
    </details>

    <div className="metaLevelBlock">
      <h3>Orçamento</h3>
      <label className="metaSwitch">
        <input type="checkbox" checked={cbo} onChange={(e) => onMeta({ budget_level: e.target.checked ? "campaign" : "adset" })} />
        <span><b>Orçamento da campanha Advantage+</b><small>{cbo
          ? "A Meta distribui o orçamento entre os conjuntos de anúncios para ter mais resultados."
          : "Desligado: o orçamento e a estratégia de lance ficam no conjunto de anúncios."}</small></span>
      </label>
      <div className="metaAdsRow">
        <label className="ds-field">Tipo de orçamento<select value={meta.budget_type}
          onChange={(e) => onMeta({ budget_type: e.target.value as MetaStructure["budget_type"] })}>
          <option value="daily">Orçamento diário</option><option value="lifetime">Orçamento total</option></select></label>
        <label className="ds-field">Valor ({currency})<input type="number" min={1} step={1} value={meta.budget || ""}
          onChange={(e) => onMeta({ budget: Number(e.target.value) })} /></label>
      </div>
      {!cbo ? <p className="ds-caption">O valor acima vai para o conjunto de anúncios.</p> : null}
      <label className="ds-field">Estratégia de lance{!cbo ? " (no conjunto)" : ""}<select value={meta.bid_strategy}
        onChange={(e) => onMeta({ bid_strategy: e.target.value as MetaStructure["bid_strategy"] })}>
        {bids.map((b) => <option key={b.key} value={b.key}>{meta.performance_goal === "VALUE" && b.key === "LOWEST_COST_WITHOUT_CAP" ? "Valor mais alto" : b.label}</option>)}
      </select></label>
      <small className="ds-caption">{bids.find((b) => b.key === meta.bid_strategy)?.hint}</small>
      {meta.bid_strategy === "COST_CAP" || meta.bid_strategy === "LOWEST_COST_WITH_BID_CAP" ?
        <label className="ds-field">{meta.bid_strategy === "COST_CAP" ? "Meta de custo por resultado" : "Limite de lance"} ({currency})
          <input type="number" min={0.01} step={0.01} value={meta.bid_amount ?? ""} onChange={(e) => onMeta({ bid_amount: e.target.value ? Number(e.target.value) : null })} /></label> : null}
      {meta.bid_strategy === "LOWEST_COST_WITH_MIN_ROAS" ?
        <label className="ds-field">Meta de ROAS (ex.: 2,5 = R$ 2,50 de retorno para cada R$ 1)
          <input type="number" min={0.01} step={0.01} value={meta.roas_floor ?? ""} onChange={(e) => onMeta({ roas_floor: e.target.value ? Number(e.target.value) : null })} /></label> : null}
    </div>
  </fieldset>;
}
