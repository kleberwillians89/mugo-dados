import type { BuilderOptions, MetaCatalog, MetaLocation, MetaMessagingApp, MetaStructure } from "../../app/metaAds";
import MetaWhatsappNumber from "./MetaWhatsappNumber";
import { goalsFor, locationsFor, needsEvent } from "./metaStructure";

type Props = {
  catalog: MetaCatalog; options: BuilderOptions | null; meta: MetaStructure; disabled?: boolean;
  startDate: string; endDate: string; pixelId: string | null | undefined; whatsappNumber: string | null | undefined;
  onMeta: (patch: Partial<MetaStructure>) => void; onDates: (patch: { start_date?: string; end_date?: string }) => void;
  onPixel: (id: string) => void; onWhatsapp: (n: string | null) => void;
};

/** Nível 2 · Conjunto de anúncios (parte de cima): local da conversão, meta de desempenho, pixel/evento e datas. */
export default function MetaAdsetLevel({ catalog, options, meta, disabled, startDate, endDate, pixelId, whatsappNumber,
  onMeta, onDates, onPixel, onWhatsapp }: Props) {
  const locations = locationsFor(catalog, meta.objective, Boolean(options?.apps.length));
  const goals = goalsFor(catalog, meta.objective, meta.conversion_location);
  const toggleApp = (app: MetaMessagingApp, on: boolean) => {
    const next = on ? [...meta.messaging_apps, app] : meta.messaging_apps.filter((a) => a !== app);
    if (next.length) onMeta({ messaging_apps: next });
  };
  const pixel = options?.pixels.find((p) => p.id === (pixelId || options?.recommended_pixel));
  const app = options?.apps.find((a) => a.id === meta.app?.id);
  return <fieldset disabled={disabled} className="metaLevel">
    <legend>Conjunto de anúncios</legend>

    {meta.objective !== "OUTCOME_AWARENESS" ? <div className="metaLevelBlock" role="radiogroup" aria-label="Local da conversão">
      <h3>{meta.objective === "OUTCOME_APP_PROMOTION" ? "App" : "Local da conversão"}</h3>
      <div className="metaLocations">
        {locations.map((loc) => <label key={loc} className={`metaLocation${meta.conversion_location === loc ? " is-selected" : ""}`}>
          <input type="radio" name="meta-location" checked={meta.conversion_location === loc}
            onChange={() => onMeta({ conversion_location: loc as MetaLocation })} />
          {loc === "ON_POST" ? "No seu anúncio" : catalog.locations[loc]}
        </label>)}
      </div>
      {meta.conversion_location === "MESSAGING" ? <div className="metaChecks" aria-label="Apps de mensagem">
        {catalog.messaging_apps.map((a) => <label key={a.key} className="metaAdsCheck">
          <input type="checkbox" checked={meta.messaging_apps.includes(a.key)} onChange={(e) => toggleApp(a.key, e.target.checked)} />{a.label}</label>)}
      </div> : null}
      {meta.conversion_location === "MESSAGING" && meta.messaging_apps.includes("WHATSAPP") ?
        <MetaWhatsappNumber value={whatsappNumber} disabled={disabled} onChange={onWhatsapp} /> : null}
      {meta.conversion_location === "APP" ? (options?.apps.length ? <div className="metaAdsRow">
        <label className="ds-field">App<select value={meta.app?.id || ""} onChange={(e) => {
          const picked = options.apps.find((a) => a.id === e.target.value);
          onMeta({ app: picked ? { id: picked.id, name: picked.name, store_url: picked.stores[0]?.url || "" } : null });
        }}><option value="">Escolha o app</option>{options.apps.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
        {app ? <label className="ds-field">Loja de apps<select value={meta.app?.store_url || ""}
          onChange={(e) => onMeta({ app: meta.app ? { ...meta.app, store_url: e.target.value } : null })}>
          {app.stores.map((s) => <option key={s.url} value={s.url}>{s.store === "google_play" ? "Google Play" : s.store === "itunes" ? "App Store" : s.store}</option>)}
        </select></label> : null}
      </div> : <p className="metaPixelWarn">Esta conta de anúncios não tem nenhum app registrado. Registre o app na Meta para usar este objetivo.</p>) : null}
      {meta.conversion_location === "ON_AD" ? (options?.lead_forms.length ? <label className="ds-field">Formulário instantâneo
        <select value={meta.lead_form?.id || ""} onChange={(e) => {
          const form = options.lead_forms.find((f) => f.id === e.target.value);
          onMeta({ lead_form: form ? { id: form.id, name: form.name } : null });
        }}><option value="">Escolha o formulário</option>{options.lead_forms.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select></label>
        : <p className="metaPixelWarn">A Página não tem formulário instantâneo ativo. Crie o formulário na Central de Formulários da Página e volte aqui.</p>) : null}
      {meta.conversion_location === "PHONE_CALL" ? <label className="ds-field">Número de telefone (com DDI e DDD)
        <input inputMode="tel" placeholder="55 11 99999-0000" value={meta.phone_number || ""} onChange={(e) => onMeta({ phone_number: e.target.value })} /></label> : null}
    </div> : null}

    <div className="metaLevelBlock">
      <h3>Meta de desempenho</h3>
      <label className="ds-field"><span className="ds-srOnly">Meta de desempenho</span><select value={meta.performance_goal}
        onChange={(e) => onMeta({ performance_goal: e.target.value })}>
        {goals.map((g) => <option key={g} value={g}>{catalog.goals[g] || g}</option>)}</select></label>
    </div>

    {needsEvent(meta) ? <div className="metaLevelBlock">
      <h3>Conjunto de dados e evento de conversão</h3>
      {options && !options.pixels.length ? <p className="metaPixelWarn">A conta não tem pixel (conjunto de dados). Crie um no Gerenciador de Eventos para otimizar por conversão.</p> : null}
      <div className="metaAdsRow">
        <label className="ds-field">Conjunto de dados (pixel)<select value={pixelId || options?.recommended_pixel || ""} disabled={!options?.pixels.length}
          onChange={(e) => onPixel(e.target.value)}>
          {(options?.pixels || []).map((p) => <option key={p.id} value={p.id}>{p.name}{p.active ? "" : " · sem eventos"}</option>)}
        </select></label>
        <label className="ds-field">Evento de conversão<select value={meta.conversion_event || ""} disabled={meta.performance_goal === "VALUE"}
          onChange={(e) => onMeta({ conversion_event: e.target.value })}>
          {catalog.events.map((ev) => <option key={ev.key} value={ev.key}>{ev.label}{pixel && !pixel.events_seen.includes(ev.key) ? " · sem atividade recente" : ""}</option>)}
        </select></label>
      </div>
    </div> : null}

    <div className="metaLevelBlock">
      <h3>Programação</h3>
      <div className="metaAdsRow">
        <label className="ds-field">Data de início<input type="date" value={startDate} onChange={(e) => onDates({ start_date: e.target.value })} /></label>
        {meta.has_end_date ? <label className="ds-field">Data de término<input type="date" value={endDate} onChange={(e) => onDates({ end_date: e.target.value })} /></label> : null}
      </div>
      {meta.budget_type === "daily" ? <label className="metaAdsCheck"><input type="checkbox" checked={meta.has_end_date}
        onChange={(e) => onMeta({ has_end_date: e.target.checked })} /> Definir uma data de término</label>
        : <small className="ds-caption">Com orçamento total, a data de término é obrigatória.</small>}
    </div>
  </fieldset>;
}
