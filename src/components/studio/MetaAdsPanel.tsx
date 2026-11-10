import { useCallback, useEffect, useState, type FormEvent } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { deleteAdDraft, generateAdDraft, listAdDrafts, publishAdDraft, saveAdDraft, type AdDraft, type AdPayload } from "../../app/metaAds";
import { getCalendar, type CalendarItem } from "../../app/studio";
import Drawer from "../Drawer";
import StatusBadge from "../StatusBadge";

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const STATUS: Record<AdDraft["status"], { label: string; tone: "neutral" | "info" | "success" | "error" }> = {
  rascunho: { label: "Rascunho", tone: "neutral" }, publicando: { label: "Criando no Meta…", tone: "info" },
  publicada: { label: "Criada no Meta (pausada)", tone: "success" }, erro: { label: "Erro no Meta", tone: "error" },
};
const brl = (v: number) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const firstArt = (item: CalendarItem) => String(item.art_url || "").split("\n")[0].trim();
const isImage = (url: string) => /\.(jpe?g|png|webp)(\?|$)/i.test(url) || url.includes("/storage/v1/object/public/");

export type PrepareRequest = { nonce: number; campaign: Record<string, unknown> } | null;

/**
 * Campanhas do Mídia On prontas para o Meta Ads: a IA monta tudo (objetivo, verba, período, público, texto),
 * a equipe revisa, escolhe a arte do Calendário e cria no Meta — sempre PAUSADA, para conferir e ativar lá.
 */
export default function MetaAdsPanel({ month, objective, daysLeft, request }: { month: string; objective: string; daysLeft: number; request: PrepareRequest }) {
  const clientId = getActiveClientId();
  const [drafts, setDrafts] = useState<AdDraft[] | null>(null);
  const [objectives, setObjectives] = useState<Record<string, string>>({});
  const [ctas, setCtas] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<{ draft: AdDraft; payload: AdPayload } | null>(null);
  const [arts, setArts] = useState<CalendarItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await listAdDrafts();
      if (getActiveClientId() !== clientId) return;
      setDrafts(data.drafts); setObjectives(data.objectives); setCtas(data.ctas);
    } catch (cause) { setError(message(cause, "Não foi possível carregar as campanhas do Meta Ads.")); setDrafts([]); }
  }, [clientId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    getCalendar(month).then((r) => setArts(r.items.filter((i) => firstArt(i) && isImage(firstArt(i))))).catch(() => setArts([]));
  }, [month, clientId]);

  async function run<T>(key: string, fn: () => Promise<T>, fallback: string): Promise<T | null> {
    setBusy(key); setError(null); setNotice(null);
    try { return await fn(); } catch (cause) { setError(message(cause, fallback)); return null; } finally { setBusy(null); }
  }

  const open = (draft: AdDraft) => setEditing({ draft, payload: JSON.parse(JSON.stringify(draft.payload)) as AdPayload });
  const upsert = (d: AdDraft) => setDrafts((list) => [d, ...(list || []).filter((x) => x.id !== d.id)]);

  const generate = useCallback(async (campaign: Record<string, unknown>) => {
    const r = await run("generate", () => generateAdDraft({ month, objective, days_left: daysLeft, campaign }), "Não foi possível montar a campanha.");
    if (r) { upsert(r.draft); open(r.draft); }
  }, [month, objective, daysLeft]);
  useEffect(() => { if (request) void generate(request.campaign); }, [request, generate]);

  async function save(event?: FormEvent) {
    event?.preventDefault();
    if (!editing) return null;
    const r = await run("save", () => saveAdDraft(editing.draft.id, editing.payload), "Não foi possível salvar.");
    if (r) { upsert(r.draft); setEditing({ draft: r.draft, payload: r.draft.payload }); }
    return r;
  }

  async function publish() {
    if (!editing) return;
    const p = editing.payload;
    if (!window.confirm(`Criar "${p.name}" no Meta Ads?\n\nVai PAUSADA, com orçamento de ${brl(p.daily_budget)}/dia de ${p.start_date.split("-").reverse().join("/")} a ${p.end_date.split("-").reverse().join("/")}. Nada é gasto até alguém ativar no Gerenciador de Anúncios.`)) return;
    const saved = await save();
    if (!saved) return;
    const r = await run("publish", () => publishAdDraft(editing.draft.id), "Não foi possível criar no Meta Ads.");
    await load();
    if (r) { setEditing(null); setNotice(`"${r.draft.payload.name}" foi criada no Meta Ads, pausada. Confira e ative no Gerenciador de Anúncios.`); }
  }

  async function remove(d: AdDraft) {
    if (!window.confirm(d.status === "publicada" ? `Tirar "${d.payload.name}" desta lista? A campanha continua no Meta Ads.` : `Excluir o rascunho "${d.payload.name}"?`)) return;
    const r = await run(`d:${d.id}`, () => deleteAdDraft(d.id), "Não foi possível excluir.");
    if (r) setDrafts((list) => (list || []).filter((x) => x.id !== d.id));
  }

  const set = (patch: Partial<AdPayload>) => setEditing((e) => (e ? { ...e, payload: { ...e.payload, ...patch } } : e));
  const setAud = (patch: Partial<AdPayload["audience"]>) => setEditing((e) => (e ? { ...e, payload: { ...e.payload, audience: { ...e.payload.audience, ...patch } } } : e));
  const setAd = (patch: Partial<AdPayload["ad"]>) => setEditing((e) => (e ? { ...e, payload: { ...e.payload, ad: { ...e.payload.ad, ...patch } } } : e));
  const locked = editing ? editing.draft.status === "publicada" || editing.draft.status === "publicando" : false;

  return <section className="ds-section metaAds" aria-labelledby="media-meta-ads">
    <div className="ds-sectionHead"><div className="ds-sectionHeadText"><h2 id="media-meta-ads" className="ds-sectionTitle">Campanhas no Meta Ads</h2>
      <p className="ds-caption">A IA monta a campanha completa a partir do plano. Você revisa, escolhe a arte do Calendário e cria no Meta, sempre pausada.</p></div>
      <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void generate({ campaign: "Nova campanha", action: "testar" })}>
        {busy === "generate" ? "Montando…" : "+ Nova campanha"}</button></div>
    {error ? <div className="ds-notice is-negative" role="alert"><p className="ds-noticeTitle">{error}</p></div> : null}
    {notice ? <div className="ds-notice is-positive" role="status"><p className="ds-noticeTitle">{notice}</p></div> : null}
    {busy === "generate" ? <p className="ds-caption">A IA está montando público, texto e verba… até 1 minuto.</p> : null}
    {!drafts ? <p className="ds-caption">Carregando…</p> : !drafts.length ? <p className="ds-emptyLine">Nenhuma campanha preparada. Use “Preparar no Meta Ads” numa campanha do Meta acima ou “+ Nova campanha”.</p> :
      <div className="ds-tableWrap"><table className="ds-table metaAdsTable">
        <thead><tr><th>Campanha</th><th>Objetivo</th><th>Verba/dia</th><th>Período</th><th>Status</th><th aria-label="Ações" /></tr></thead>
        <tbody>{drafts.map((d) => <tr key={d.id}>
          <td><b>{d.payload.name}</b>{d.source_campaign && d.source_campaign !== d.payload.name ? <span className="ds-tableSub">do plano: {d.source_campaign}</span> : null}
            {d.status === "erro" && d.error ? <span className="ds-tableSub metaAdsErr">{d.error}</span> : null}
            {d.status === "rascunho" && d.missing.length ? <span className="ds-tableSub">Falta: {d.missing.join(" · ")}</span> : null}</td>
          <td>{objectives[d.payload.objective] || d.payload.objective}</td>
          <td>{brl(d.payload.daily_budget)}</td>
          <td>{d.payload.start_date.slice(8, 10)}/{d.payload.start_date.slice(5, 7)} a {d.payload.end_date.slice(8, 10)}/{d.payload.end_date.slice(5, 7)}</td>
          <td><StatusBadge label={STATUS[d.status].label} tone={STATUS[d.status].tone} /></td>
          <td><div className="metaAdsActions">
            {d.ads_manager_url ? <a className="ds-link" href={d.ads_manager_url} target="_blank" rel="noreferrer">Abrir no Gerenciador</a> : null}
            <button type="button" className="ds-button" onClick={() => open(d)}>{d.status === "publicada" ? "Ver" : "Revisar"}</button>
            <button type="button" className="ds-link is-quiet" disabled={Boolean(busy)} onClick={() => void remove(d)}>{d.status === "publicada" ? "Tirar da lista" : "Excluir"}</button>
          </div></td>
        </tr>)}</tbody></table></div>}

    <Drawer open={Boolean(editing)} width="lg" title={editing ? editing.payload.name : ""} onClose={() => { if (!busy) setEditing(null); }}
      description={locked ? "Já criada no Meta Ads (pausada). Ajustes daqui em diante, no Gerenciador de Anúncios." : "Revise tudo antes de criar. A campanha vai pausada: nada é gasto até alguém ativar no Meta."}>
      {editing ? <form className="metaAdsForm" onSubmit={(e) => void save(e)}>
        <fieldset disabled={locked || Boolean(busy)}>
          <legend>Campanha</legend>
          <label className="ds-field">Nome<input required maxLength={120} value={editing.payload.name} onChange={(e) => set({ name: e.target.value })} /></label>
          <div className="metaAdsRow">
            <label className="ds-field">Objetivo<select value={editing.payload.objective} onChange={(e) => set({ objective: e.target.value as AdPayload["objective"] })}>
              {Object.entries(objectives).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
            <label className="ds-field">Orçamento por dia (R$)<input type="number" min={6} step={1} value={editing.payload.daily_budget} onChange={(e) => set({ daily_budget: Number(e.target.value) })} /></label>
          </div>
          <div className="metaAdsRow">
            <label className="ds-field">Início<input type="date" value={editing.payload.start_date} onChange={(e) => set({ start_date: e.target.value })} /></label>
            <label className="ds-field">Fim<input type="date" value={editing.payload.end_date} onChange={(e) => set({ end_date: e.target.value })} /></label>
          </div>
        </fieldset>
        <fieldset disabled={locked || Boolean(busy)}>
          <legend>Público</legend>
          <div className="metaAdsRow">
            <label className="ds-field">Idade mínima<input type="number" min={18} max={65} value={editing.payload.audience.age_min} onChange={(e) => setAud({ age_min: Number(e.target.value) })} /></label>
            <label className="ds-field">Idade máxima<input type="number" min={18} max={65} value={editing.payload.audience.age_max} onChange={(e) => setAud({ age_max: Number(e.target.value) })} /></label>
            <label className="ds-field">Gênero<select value={editing.payload.audience.gender} onChange={(e) => setAud({ gender: e.target.value as AdPayload["audience"]["gender"] })}>
              <option value="todos">Todos</option><option value="mulheres">Mulheres</option><option value="homens">Homens</option></select></label>
          </div>
          <label className="ds-field">Estados (vazio = Brasil todo; separados por vírgula)<input value={editing.payload.audience.regions.join(", ")} placeholder="São Paulo, Minas Gerais"
            onChange={(e) => setAud({ regions: e.target.value.split(",").map((s) => s.trimStart()) })} /></label>
          <label className="ds-field">Interesses (separados por vírgula)<input value={editing.payload.audience.interests.join(", ")} placeholder="Perfumes, Moda, Beleza"
            onChange={(e) => setAud({ interests: e.target.value.split(",").map((s) => s.trimStart()) })} /></label>
          <label className="metaAdsCheck"><input type="checkbox" checked={editing.payload.audience.advantage} onChange={(e) => setAud({ advantage: e.target.checked })} />
            Público Advantage+ (o Meta pode ampliar além dos interesses quando achar gente com mais chance)</label>
        </fieldset>
        <fieldset disabled={locked || Boolean(busy)}>
          <legend>Anúncio</legend>
          <label className="ds-field">Texto principal<textarea rows={4} maxLength={2000} value={editing.payload.ad.primary_text} onChange={(e) => setAd({ primary_text: e.target.value })} /></label>
          <div className="metaAdsRow">
            <label className="ds-field">Título<input maxLength={120} value={editing.payload.ad.headline} onChange={(e) => setAd({ headline: e.target.value })} /></label>
            <label className="ds-field">Botão<select value={editing.payload.ad.cta} onChange={(e) => setAd({ cta: e.target.value })}>
              {Object.entries(ctas).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          </div>
          <label className="ds-field">Descrição (opcional)<input maxLength={200} value={editing.payload.ad.description} onChange={(e) => setAd({ description: e.target.value })} /></label>
          <label className="ds-field">Link de destino<input type="url" maxLength={500} value={editing.payload.ad.link} placeholder="https://loja.com.br/produto" onChange={(e) => setAd({ link: e.target.value })} /></label>
          <div className="ds-field">Imagem do anúncio
            {arts.length ? <div className="metaAdsArts">{arts.slice(0, 12).map((item) => {
              const url = firstArt(item);
              return <button key={item.id} type="button" className={`metaAdsArt${editing.payload.ad.image_url === url ? " is-selected" : ""}`} title={item.title}
                onClick={() => setAd({ image_url: url, calendar_item_id: item.id })}><img src={url} alt="" loading="lazy" /><span>{item.title}</span></button>;
            })}</div> : <small>Nenhum post com arte em imagem no Calendário deste mês.</small>}
            <input type="url" maxLength={1000} value={editing.payload.ad.image_url} placeholder="ou cole o link direto da imagem (JPG/PNG)"
              onChange={(e) => setAd({ image_url: e.target.value, calendar_item_id: null })} />
          </div>
        </fieldset>
        {!locked && editing.draft.missing.length ? <p className="ds-caption metaAdsMissing">Para criar no Meta falta: {editing.draft.missing.join(" · ")} (salve para conferir de novo).</p> : null}
        {editing.draft.status === "erro" && editing.draft.error ? <div className="ds-notice is-negative"><p className="ds-noticeTitle">{editing.draft.error}</p></div> : null}
        <div className="metaAdsFormActions">
          {editing.draft.ads_manager_url ? <a className="ds-link" href={editing.draft.ads_manager_url} target="_blank" rel="noreferrer">Abrir no Gerenciador de Anúncios</a> : <span />}
          {!locked ? <span className="metaAdsButtons">
            <button className="ds-button" disabled={Boolean(busy)}>{busy === "save" ? "Salvando…" : "Salvar rascunho"}</button>
            <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => void publish()}>{busy === "publish" ? "Criando no Meta…" : "Criar no Meta Ads (pausada)"}</button>
          </span> : null}
        </div>
      </form> : null}
    </Drawer>
  </section>;
}
