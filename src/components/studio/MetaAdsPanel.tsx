import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { deleteAdDraft, duplicateAdDraft, generateAdDraft, listAdDrafts, publishAdDraft, saveAdDraft, metaPublicationPreflight, readMetaCampaignOverview, type MetaOverviewCampaign, type MetaPublicationPreflight, type AdDraft, type AdPayload, type AdCreative, MAX_ADS, normalizeAdFormats, PIXEL_OBJECTIVES } from "../../app/metaAds";
import { getCalendar, type CalendarItem } from "../../app/studio";
import Drawer from "../Drawer";
import StatusBadge from "../StatusBadge";
import MetaAudiencePicker from "./MetaAudiencePicker";
import MetaCreativeStudio from "./MetaCreativeStudio";
import MetaLiveCampaign from "./MetaLiveCampaign";
import MetaLiveEditor from "./MetaLiveEditor";
import { campaignCategory, type CampaignFilter } from "./MediaClientCampaigns";
import MetaPixelSwitch from "./MetaPixelSwitch";
import MetaPixelPicker from "./MetaPixelPicker";
import MetaWhatsappNumber from "./MetaWhatsappNumber";
import MetaImportCampaign from "./MetaImportCampaign";
import CampaignTrackingFields from "./CampaignTrackingFields";
import MetaPlacementPicker from "./MetaPlacementPicker";
import { DEFAULT_META_PLACEMENTS } from "./metaPlacements";
import { META_STEPS, accountAudienceText, metaStepIssues, type MetaStep } from "./metaCampaignWizard";

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
  const handledRequest = useRef<number | null>(null);
  const [drafts, setDrafts] = useState<AdDraft[] | null>(null);
  const [cardFilter, setCardFilter] = useState<CampaignFilter | "drafts">("active");
  const [liveList, setLiveList] = useState<MetaOverviewCampaign[] | null>(null);
  const [liveError, setLiveError] = useState(false);
  const [objectives, setObjectives] = useState<Record<string, string>>({});
  const [ctas, setCtas] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<{ draft: AdDraft; payload: AdPayload } | null>(null);
  const [step, setStep] = useState<MetaStep>(0);
  const [audienceApproved, setAudienceApproved] = useState(false);
  const [stepIssue, setStepIssue] = useState<string | null>(null);
  const [arts, setArts] = useState<CalendarItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [metaPreflight, setMetaPreflight] = useState<MetaPublicationPreflight | null>(null);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const [preflightError, setPreflightError] = useState<string | null>(null);
  const [preflightVersion, setPreflightVersion] = useState(0);
  useEffect(() => {
    if (!editing || step !== 3 || editing.draft.status === "publicada") return;
    const tenant = clientId;
    let valid = true;
    setMetaPreflight(null); setPreflightError(null); setPreflightBusy(true);
    metaPublicationPreflight(editing.payload.objective)
      .then((result) => { if (valid && getActiveClientId() === tenant) setMetaPreflight(result); })
      .catch((cause) => { if (valid && getActiveClientId() === tenant)
        setPreflightError(message(cause, "Não foi possível verificar a conta de anúncios.")); })
      .finally(() => { if (valid && getActiveClientId() === tenant) setPreflightBusy(false); });
    return () => { valid = false; };
  }, [clientId, editing?.draft.id, editing?.payload.objective, step, preflightVersion]);


  const load = useCallback(async () => {
    try {
      const data = await listAdDrafts();
      if (getActiveClientId() !== clientId) return;
      setDrafts(data.drafts); setObjectives(data.objectives); setCtas(data.ctas);
    } catch (cause) { setError(message(cause, "Não foi possível carregar as campanhas do Meta Ads.")); setDrafts([]); }
  }, [clientId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    let active = true;
    setLiveList(null); setLiveError(false); setCardFilter("active");
    readMetaCampaignOverview(clientId)
      .then((r) => { if (active && getActiveClientId() === clientId) setLiveList(r.campaigns); })
      .catch(() => { if (active && getActiveClientId() === clientId) setLiveError(true); });
    return () => { active = false; };
  }, [clientId]);
  useEffect(() => {
    getCalendar(month).then((r) => setArts(r.items.filter((i) => firstArt(i) && isImage(firstArt(i))))).catch(() => setArts([]));
  }, [month, clientId]);

  async function run<T>(key: string, fn: () => Promise<T>, fallback: string): Promise<T | null> {
    setBusy(key); setError(null); setNotice(null);
    try { return await fn(); } catch (cause) { setError(message(cause, fallback)); return null; } finally { setBusy(null); }
  }

  const open = (draft: AdDraft) => {
    const inside = Boolean(draft.joined || draft.meta_ids?.joined || (draft.status !== "publicada" && draft.meta_ids?.adset_id));
    const copy = JSON.parse(JSON.stringify(draft.payload)) as AdPayload;
    setEditing({ draft, payload: { ...copy, ad: normalizeAdFormats(copy.ad) } });
    setActiveAd(0);
    setStep(inside && draft.status !== "publicada" ? 2 : 0);
    setAudienceApproved(inside);
    setStepIssue(null);
  };
  const upsert = (d: AdDraft) => setDrafts((list) => [d, ...(list || []).filter((x) => x.id !== d.id)]);

  const generate = useCallback(async (campaign: Record<string, unknown>) => {
    const r = await run("generate", () => generateAdDraft({ month, objective, days_left: daysLeft, campaign }), "Não foi possível montar a campanha.");
    if (r) { upsert(r.draft); open(r.draft); }
  }, [month, objective, daysLeft]);
  useEffect(() => { if (request && request.nonce !== handledRequest.current) { handledRequest.current = request.nonce; void generate(request.campaign); } }, [request, generate]);

  async function save(event?: FormEvent) {
    event?.preventDefault();
    if (!editing) return null;
    const r = await run("save", () => saveAdDraft(editing.draft.id, editing.payload), "Não foi possível salvar.");
    if (r) { upsert(r.draft); setEditing({ draft: r.draft, payload: r.draft.payload }); }
    return r;
  }

  async function publish() {
    if (!editing || step !== 3 || !audienceApproved || busy) return;
    const p = editing.payload;
    const missing = metaStepIssues(p, 3);
    if (missing.length) { setStepIssue(missing.join(" ")); return; }
    if (!window.confirm(`Criar "${p.name}" no Meta Ads?\n\nVai PAUSADA, com orçamento de ${brl(p.daily_budget)}/dia de ${p.start_date.split("-").reverse().join("/")} a ${p.end_date.split("-").reverse().join("/")}. Nada é gasto até alguém ativar no Gerenciador de Anúncios.`)) return;
    const saved = await save();
    if (!saved) return;
    const r = await run("publish", () => publishAdDraft(editing.draft.id), "Não foi possível criar no Meta Ads.");
    await load();
    if (r) { setEditing(null); setNotice(`"${r.draft.payload.name}" foi criada no Meta Ads, pausada. Confira e ative no Gerenciador de Anúncios.`); }
  }

  async function duplicate(d: AdDraft, into?: "campaign") {
    const r = await run(`duplicate${into ? "-ad" : ""}:${d.id}`, () => duplicateAdDraft(d.id, into),
      into ? "Não foi possível criar o anúncio nesta campanha." : "Não foi possível duplicar esta campanha.");
    if (r) {
      upsert(r.draft);
      setNotice(into ? `Novo anúncio dentro de "${d.payload.name}": mesma verba e mesmo público. Troque o criativo e crie pausado.`
        : `Cópia de "${d.payload.name}" criada como campanha nova, com verba própria. Nada foi publicado nem ativado.`);
      open(r.draft);
    }
  }

  async function remove(d: AdDraft) {
    if (!window.confirm(d.status === "publicada" ? `Tirar "${d.payload.name}" desta lista? A campanha continua no Meta Ads.` : `Excluir o rascunho "${d.payload.name}"?`)) return;
    const r = await run(`d:${d.id}`, () => deleteAdDraft(d.id), "Não foi possível excluir.");
    if (r) setDrafts((list) => (list || []).filter((x) => x.id !== d.id));
  }

  const set = (patch: Partial<AdPayload>) => setEditing((e) => (e ? { ...e, payload: { ...e.payload, ...patch } } : e));
  const setAud = (patch: Partial<AdPayload["audience"]>) => {
    setAudienceApproved(false);
    setEditing((e) => (e ? { ...e, payload: { ...e.payload, audience: { ...e.payload.audience, ...patch } } } : e));
  };
  const [activeAd, setActiveAd] = useState(0);
  const [importing, setImporting] = useState(false);
  const CREATIVE_KEYS = ["format", "image_url", "media_type", "video_url", "instagram_post_id", "calendar_item_id", "cards"] as const;
  /** Muda a parte visual do anúncio da aba aberta (o 1 é o próprio `ad`; os outros ficam em extra_ads). */
  const setCreative = (index: number, patch: Partial<AdPayload["ad"]>) => {
    if (index === 0) { setAd(patch); return; }
    setEditing((e) => {
      if (!e) return e;
      const extras = [...(e.payload.ad.extra_ads || [])];
      const picked = Object.fromEntries(Object.entries(patch).filter(([k]) => (CREATIVE_KEYS as readonly string[]).includes(k)));
      extras[index - 1] = { ...extras[index - 1], ...picked } as AdCreative;
      return { ...e, payload: { ...e.payload, ad: { ...e.payload.ad, extra_ads: extras } } };
    });
  };
  const addAd = () => {
    if (!editing) return;
    const extras = [...(editing.payload.ad.extra_ads || []), { format: "single" as const, image_url: "", media_type: "image" as const, cards: [] }];
    setAd({ extra_ads: extras });
    setActiveAd(extras.length);
  };
  const removeAd = (index: number) => {
    if (!editing || index === 0) return;
    setAd({ extra_ads: (editing.payload.ad.extra_ads || []).filter((_, i) => i !== index - 1) });
    setActiveAd(Math.max(0, index - 1));
  };
  const setAd = (patch: Partial<AdPayload["ad"]>) => setEditing((e) => (e ? { ...e, payload: { ...e.payload, ad: { ...e.payload.ad, ...patch } } } : e));
  const locked = editing ? editing.draft.status === "publicada" || editing.draft.status === "publicando" : false;
  // Anúncio dentro de campanha já criada: verba, datas e público são os da campanha original.
  const joined = Boolean(editing?.draft.joined || editing?.draft.meta_ids?.joined);
  // Criação que parou no meio: campanha e conjunto já existem na Meta; só falta terminar os anúncios.
  const halfway = !locked && !joined && Boolean(editing?.draft.meta_ids?.adset_id);
  function advance() {
    if (!editing || busy) return;
    const missing = metaStepIssues(editing.payload, step);
    if (missing.length) { setStepIssue(missing.join(" ")); return; }
    if (step === 1 && !audienceApproved) {
      setStepIssue("Confirme o público selecionado antes de escolher o criativo.");
      return;
    }
    setStepIssue(null);
    if (step < 3) setStep((step + 1) as MetaStep);
  }


  const cardStatuses = new Map((liveList || []).map((c) => [c.id, campaignCategory(c)]));
  const visibleDrafts = (drafts || []).filter((d) => {
    if (cardFilter === "all") return true;
    if (cardFilter === "drafts") return d.status !== "publicada";
    if (d.status !== "publicada" || !d.meta_ids?.campaign_id) return false;
    return cardStatuses.get(d.meta_ids.campaign_id) === cardFilter;
  });

  return <section className="ds-section metaAds" aria-labelledby="media-meta-ads">
    <div className="ds-sectionHead"><div className="ds-sectionHeadText"><h2 id="media-meta-ads" className="ds-sectionTitle">Campanhas no Meta Ads</h2>
      <p className="ds-caption">A IA monta a campanha completa a partir do plano. Você revisa, escolhe a arte do Calendário e cria no Meta, sempre pausada.</p></div>
      <span className="metaAdsHeadActions">
        <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => setImporting((v) => !v)}>Puxar campanha da Meta</button>
        <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void generate({ campaign: "Nova campanha", action: "testar" })}>
          {busy === "generate" ? "Montando…" : "+ Nova campanha"}</button></span></div>
    {importing ? <MetaImportCampaign onClose={() => setImporting(false)}
      onImported={(d) => { upsert(d); setNotice(`"${d.payload.name}" agora está na Mídia On: status, Ativar/Pausar e resultados no card.`); }} /> : null}
    {error ? <div className="ds-notice is-negative" role="alert"><p className="ds-noticeTitle">{error}</p></div> : null}
    {notice ? <div className="ds-notice is-positive" role="status"><p className="ds-noticeTitle">{notice}</p></div> : null}
    {busy === "generate" ? <p className="ds-caption">A IA está montando público, texto e verba… até 1 minuto.</p> : null}
    <div className="mediaAllClientsFilters" style={{ marginTop: 16, marginBottom: 16 }}>
      <label>Status das campanhas
        <select aria-label="Filtrar cards por status" value={cardFilter} onChange={(e) => setCardFilter(e.target.value as CampaignFilter | "drafts")}>
          <option value="active">Ativas (padrão)</option>
          <option value="paused">Pausadas / desativadas</option>
          <option value="finished">Encerradas / arquivadas</option>
          <option value="review">Em análise</option>
          <option value="issues">Com problemas</option>
          <option value="other">Status não confirmado</option>
          <option value="drafts">Rascunhos e erros de publicação</option>
          <option value="all">Todas as campanhas</option>
        </select>
      </label>
    </div>
    {liveError && cardFilter !== "all" && cardFilter !== "drafts" ? <p className="studioError" role="alert">Não foi possível confirmar os status na Meta. Atualize a página ou escolha “Todas as campanhas” para consultar os registros.</p> : null}
    {!drafts || (liveList === null && !liveError && cardFilter !== "all" && cardFilter !== "drafts") ? <p className="ds-caption">Consultando as campanhas da empresa na Meta…</p>
      : !drafts.length ? <p className="ds-emptyLine">Nenhuma campanha preparada. Use “Preparar no Meta Ads” numa campanha do Meta acima ou “+ Nova campanha”.</p>
      : !visibleDrafts.length ? <p className="ds-emptyLine">Nenhuma campanha neste status. Use o filtro para visualizar campanhas pausadas, encerradas ou rascunhos.</p> :
      <div className="metaAdsCampaignCards" aria-label="Campanhas Meta Ads já preparadas">
        {visibleDrafts.map((d) => <article className="metaAdsCampaignCard" key={d.id}>
          <StatusBadge label={STATUS[d.status].label} tone={STATUS[d.status].tone} />
          <h3>{d.payload.name}</h3>
          {d.source_campaign && d.source_campaign !== d.payload.name ? <p className="ds-caption">Origem: {d.source_campaign}</p> : null}
          <div className="metaAdsCampaignMeta">
            <span>{objectives[d.payload.objective] || d.payload.objective}</span>
            <span>{brl(d.payload.daily_budget)}/dia</span>
            <span>{d.payload.start_date.slice(8, 10)}/{d.payload.start_date.slice(5, 7)} a {d.payload.end_date.slice(8, 10)}/{d.payload.end_date.slice(5, 7)}</span>
          </div>
          {d.status === "erro" && d.error ? <p className="studioError" role="alert">{d.error}</p> : null}
          {d.status === "rascunho" && d.missing.length ? <p className="ds-caption">Antes de publicar: {d.missing.join(" · ")}</p> : null}
          {d.meta_ids?.adset_id && PIXEL_OBJECTIVES.includes(d.payload.objective) ? <MetaPixelSwitch draftId={d.id} /> : null}
          {d.status === "publicada" && d.meta_ids?.campaign_id ? <MetaLiveCampaign draft={d}
            adsCount={d.payload.ad.format === "multi" ? (d.payload.ad.cards || []).length : 1 + (d.payload.ad.extra_ads || []).length} /> : null}

          {d.status === "publicada" && d.meta_ids?.campaign_id ? <MetaLiveEditor key={clientId + ":" + d.id} draft={d} month={month} calendar={arts} onUpdated={upsert} /> : null}

          <div className="metaAdsActions">
            <button type="button" className="ds-button is-primary" onClick={() => open(d)}>
              {d.status === "publicada" ? "Ver campanha" : "Editar campanha"}
            </button>
            {d.status !== "publicada" && d.status !== "publicando" ? <>
              <button type="button" className="ds-button" onClick={() => { open(d); setStep(2); }}>Criativos</button>
              <button type="button" className="ds-button" onClick={() => { open(d); setStep(3); }}>Revisar publicação</button>
            </> : null}
            {d.status === "publicada" && d.meta_ids?.adset_id ? <button type="button" className="ds-button" disabled={Boolean(busy)}
              title="Cria só um anúncio novo dentro desta campanha: mesma verba, mesmo público"
              onClick={() => void duplicate(d, "campaign")}>{busy === `duplicate-ad:${d.id}` ? "Criando…" : "Novo anúncio nesta campanha"}</button> : null}
            <button type="button" className="ds-button" disabled={Boolean(busy)}
              title="Cria outra campanha, com verba própria"
              onClick={() => void duplicate(d)}>{busy === `duplicate:${d.id}` ? "Duplicando…" : "Duplicar campanha"}</button>
            {d.ads_manager_url ? <a className="ds-button" href={d.ads_manager_url} target="_blank" rel="noreferrer">Abrir no Gerenciador</a> : null}
            <button type="button" className="ds-link is-quiet" disabled={Boolean(busy)} onClick={() => void remove(d)}>
              {d.status === "publicada" ? "Tirar da lista" : "Excluir"}
            </button>
          </div>
        </article>)}
      </div>}

    <Drawer open={Boolean(editing)} width="lg" title={editing ? editing.payload.name : ""} onClose={() => { if (!busy) setEditing(null); }}
      description={locked ? "Já criada no Meta Ads. Ligue, pause e acompanhe os resultados no card da campanha; outros ajustes, no Gerenciador." : "Revise tudo antes de criar. A campanha vai pausada: nada é gasto até alguém ativar no Meta."}>
      {editing ? <form className="metaAdsForm" onSubmit={(e) => void save(e)}>
        <nav aria-label="Etapas para criar campanha" className="metaAdsStepper">
          {META_STEPS.map((label, index) => <button key={label} type="button" aria-current={step === index ? "step" : undefined}
            className={step === index ? "is-current" : ""}
            disabled={Boolean(busy) || (!locked && index > step)}
            onClick={() => { if (locked || index <= step) { setStep(index as MetaStep); setStepIssue(null); } }}>
            <span>{index + 1}</span>{label}
          </button>)}
        </nav>
        <p className="ds-caption metaAdsStepHint">{step === 0 ? "Etapa 1 de 4 — Defina objetivo, verba e datas." : step === 1 ? "Etapa 2 de 4 — Escolha e confirme a segmentação do anúncio." : step === 2 ? "Etapa 3 de 4 — Escolha imagem ou vídeo e revise a mensagem." : "Etapa 4 de 4 — Confira tudo antes de criar uma campanha pausada."}</p>
        {joined && !locked ? <div className="ds-notice" role="note"><p className="ds-noticeTitle">Anúncio novo dentro de uma campanha já criada</p>
          <p>Verba, datas e público são os da campanha original e dividem o mesmo orçamento. Aqui você só escolhe o criativo e o texto.</p></div> : null}
        {halfway ? <div className="ds-notice" role="note"><p className="ds-noticeTitle">Campanha já começou a ser criada na Meta</p>
          <p>A campanha, o conjunto e os anúncios que deram certo já estão lá, pausados. Troque ou remova o anúncio que deu erro e clique em Criar de novo: o MUGOVERSO cria só o que falta. Verba e público ficam como já estão na Meta.</p></div> : null}
        {step === 0 ? <fieldset disabled={locked || joined || halfway || Boolean(busy)}>
          <legend>1 · Campanha</legend>
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
        </fieldset> : null}
        {step === 1 ? <fieldset disabled={locked || joined || halfway || Boolean(busy)}>
          <legend>2 · Público</legend>
          <MetaAudiencePicker audience={editing.payload.audience} onChange={setAud} disabled={locked || joined || Boolean(busy)} />
          {editing.payload.audience.saved_audience ? <p className="ds-caption metaAudSavedNote">
            Idade, gênero, locais e interesses vêm do público salvo “{editing.payload.audience.saved_audience.name}”. Os campos abaixo ficam de lado.</p> : null}
          <fieldset className="metaAudManual" disabled={Boolean(editing.payload.audience.saved_audience)}>
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
          <div className="metaAdsAudienceSummary">
            <strong>Prévia do público</strong>
            {!editing.payload.audience.saved_audience ? <p>{editing.payload.audience.age_min}–{editing.payload.audience.age_max} anos · {editing.payload.audience.gender} · {editing.payload.audience.regions.filter(Boolean).join(", ") || "Brasil inteiro"} · {editing.payload.audience.interests.filter(Boolean).join(", ") || "Sem interesses específicos (amplo)"}</p> : null}
            {accountAudienceText(editing.payload.audience) ? <p>{accountAudienceText(editing.payload.audience)}</p> : null}
          </div>
          <MetaPlacementPicker value={editing.payload.placements || DEFAULT_META_PLACEMENTS}
            onChange={placements => set({placements})} disabled={locked || joined || Boolean(busy)} />
          {!locked && !joined && !halfway ? <label className="metaAdsCheck"><input type="checkbox" checked={audienceApproved}
            onChange={(e) => { setAudienceApproved(e.target.checked); setStepIssue(null); }} />
            Revisei e confirmo esse público, inclusive a possível ampliação pelo Advantage+.</label> : null}
        </fieldset> : null}
        {step === 2 ? <fieldset disabled={locked || Boolean(busy)}>
          <legend>3 · Criativo e anúncio</legend>
          <label className="ds-field">Texto principal<textarea rows={4} maxLength={2000} value={editing.payload.ad.primary_text} onChange={(e) => setAd({ primary_text: e.target.value })} /></label>
          <div className="metaAdsRow">
            <label className="ds-field">Título<input maxLength={120} value={editing.payload.ad.headline} onChange={(e) => setAd({ headline: e.target.value })} /></label>
            <label className="ds-field">Botão<select value={editing.payload.ad.cta} onChange={(e) => setAd({ cta: e.target.value })}>
              {Object.entries(ctas).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          </div>
          <label className="ds-field">Descrição (opcional)<input maxLength={200} value={editing.payload.ad.description} onChange={(e) => setAd({ description: e.target.value })} /></label>
          {editing.payload.objective === "whatsapp"
            ? <MetaWhatsappNumber value={editing.payload.ad.whatsapp_number} disabled={locked || Boolean(busy)} onChange={(whatsapp_number) => setAd({ whatsapp_number })} />
            : <label className="ds-field">Link de destino<input type="url" maxLength={500} value={editing.payload.ad.link} placeholder="https://loja.com.br/produto" onChange={(e) => setAd({ link: e.target.value })} /></label>}
          <CampaignTrackingFields platform="meta" campaignName={editing.payload.name}
            value={editing.payload.tracking || {}} disabled={locked || Boolean(busy)}
            onChange={tracking => set({tracking})} />
          {(() => {
            const ad = editing.payload.ad;
            const all: AdCreative[] = [{ format: ad.format === "carousel" ? "carousel" : "single", image_url: ad.image_url, media_type: ad.media_type, video_url: ad.video_url, cards: ad.cards }, ...(ad.extra_ads || [])];
            const current = Math.min(activeAd, all.length - 1);
            const c = all[current];
            const shown: AdPayload["ad"] = current === 0 ? ad : { ...ad, format: c.format, image_url: c.image_url || "", media_type: c.media_type || "image",
              video_url: c.video_url || "", cards: c.cards || [], instagram_post_id: c.instagram_post_id ?? null, calendar_item_id: c.calendar_item_id ?? null, extra_ads: [] };
            return <>
              <div className="metaAdTabs" role="tablist" aria-label="Anúncios desta campanha">
                <b>Anúncios no conjunto</b>
                {all.map((item, i) => <button key={i} type="button" role="tab" aria-selected={i === current} className={`metaAdTab${i === current ? " is-active" : ""}`}
                  onClick={() => setActiveAd(i)}>
                  {(item.format === "carousel" ? item.cards?.[0]?.image_url : item.image_url) ? <img src={item.format === "carousel" ? item.cards?.[0]?.image_url : item.image_url} alt="" /> : <i />}
                  <span>Anúncio {i + 1}<small>{item.format === "carousel" ? `Carrossel · ${item.cards?.length || 0}` : item.media_type === "video" ? "Vídeo" : "Imagem única"}</small></span>
                </button>)}
                {!locked && all.length < MAX_ADS ? <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={addAd}>+ Adicionar anúncio</button> : null}
              </div>
              <div className="metaAdTabNote">
                <span>{all.length > 1 ? `${all.length} anúncios no mesmo conjunto: dividem a mesma verba e a Meta entrega mais para o melhor. Texto, título e link são os de cima.` : "Para testar outra arte com a mesma verba, adicione outro anúncio."}</span>
                {!locked && current > 0 ? <button type="button" className="ds-link is-quiet" disabled={Boolean(busy)} onClick={() => removeAd(current)}>Remover anúncio {current + 1}</button> : null}
              </div>
              <MetaCreativeStudio key={clientId + ":" + editing.draft.id + ":" + current} clientId={clientId} month={month}
                calendar={arts} ad={shown} disabled={locked || Boolean(busy)} onChoose={(patch) => setCreative(current, patch)} />
            </>;
          })()}
        </fieldset> : null}
        {step === 3 ? <section className="metaAdsReview" aria-label="Revisão da campanha">
          <div className="metaPublishPreflight" aria-label="Verificação de publicação na conta Meta">
            <div className="metaPublishPreflightHead"><div>
              <h3>Conta Meta: pronta para publicar?</h3>
              <p className="ds-caption">Checagem em tempo real da conta, permissões, página e pixel. Nenhum anúncio será enviado nesta verificação.</p>
            </div>
              <button type="button" className="ds-button" disabled={preflightBusy || Boolean(busy)}
                onClick={() => setPreflightVersion((n) => n + 1)}>
                {preflightBusy ? "Conferindo…" : "Verificar novamente"}
              </button>
            </div>
            {preflightError ? <p className="studioError" role="alert">{preflightError}</p> : null}
            {preflightBusy ? <p className="ds-caption">Conferindo as conexões desta empresa na Meta…</p> : null}
            {metaPreflight ? <>
              <p className={metaPreflight.ready ? "metaPublishReady" : "metaPublishBlocked"} role="status">
                {metaPreflight.ready ? "Conta pronta para tentar criar a campanha PAUSADA." :
                  "Há pendências na conexão Meta. Resolva antes de publicar."}
              </p>
              <div className="metaPublishChecklist">
                {metaPreflight.checks.map((check) => <div key={check.key} className={check.ok ? "is-ok" : "is-missing"}>
                  <span aria-hidden="true">{check.ok ? "✓" : "!"}</span>
                  <div><b>{({account:"Conta de anúncios",page:"Página do Facebook",instagram:"Instagram",pixel:"Pixel de conversão"} as Record<string,string>)[check.key] || check.key}</b>
                    <small>{check.label ? check.label + " · " : ""}{check.message}</small></div>
                </div>)}
              </div>
            </> : null}
          </div>
          {!locked && PIXEL_OBJECTIVES.includes(editing.payload.objective) ? <MetaPixelPicker draftId={editing.draft.id}
            value={editing.payload.pixel_id} disabled={Boolean(busy)} onChange={(pixel_id) => set({ pixel_id })} /> : null}
          <h3>Revise antes de criar no Meta</h3>
          <dl>
            <div><dt>Campanha</dt><dd>{editing.payload.name} · {objectives[editing.payload.objective] || editing.payload.objective}</dd></div>
            <div><dt>Canais e posicionamentos</dt><dd>{editing.payload.placements?.mode === "manual"
              ? [editing.payload.placements.platforms.includes("instagram") ? "Instagram: " + editing.payload.placements.instagram.join(", ") : "",
                 editing.payload.placements.platforms.includes("facebook") ? "Facebook: " + editing.payload.placements.facebook.join(", ") : ""].filter(Boolean).join(" · ")
              : "Automático (Advantage+)"}</dd></div>
            <div><dt>Orçamento e período</dt><dd>{brl(editing.payload.daily_budget)}/dia · {editing.payload.start_date.split("-").reverse().join("/")} até {editing.payload.end_date.split("-").reverse().join("/")}</dd></div>
            <div><dt>Público confirmado</dt><dd>{editing.payload.audience.saved_audience ? "" : <>{editing.payload.audience.age_min}–{editing.payload.audience.age_max} anos · {editing.payload.audience.gender} · {editing.payload.audience.regions.filter(Boolean).join(", ") || "Brasil"} · {editing.payload.audience.interests.filter(Boolean).join(", ") || "Amplo"} · Advantage+ {editing.payload.audience.advantage ? "ligado" : "desligado"}</>}
              {accountAudienceText(editing.payload.audience) ? <p>{accountAudienceText(editing.payload.audience)}</p> : null}</dd></div>
            <div><dt>Anúncio</dt><dd><strong>{editing.payload.ad.headline}</strong><p>{editing.payload.ad.primary_text}</p><p>{editing.payload.ad.link}</p></dd></div>
          </dl>
          {editing.payload.ad.format === "carousel" || (editing.payload.ad.extra_ads || []).length ? <div className="metaAdsReviewCards">
            {[{ format: editing.payload.ad.format === "carousel" ? "carousel" : "single", image_url: editing.payload.ad.image_url, cards: editing.payload.ad.cards, media_type: editing.payload.ad.media_type } as AdCreative,
              ...(editing.payload.ad.extra_ads || [])].map((c, n) => <div key={n} className="metaAdsReviewAd">
              <b>Anúncio {n + 1} · {c.format === "carousel" ? `Carrossel com ${c.cards?.length || 0} cartões` : c.media_type === "video" ? "Vídeo" : "Imagem única"}</b>
              <ol>{(c.format === "carousel" ? c.cards || [] : [{ image_url: c.image_url, headline: "" }]).map((card, i) => <li key={card.image_url + i}>
                <img src={card.image_url} alt={`Anúncio ${n + 1}, imagem ${i + 1}`} loading="lazy" />
                {c.format === "carousel" ? <small>{i + 1}. {card.headline || editing.payload.ad.headline}</small> : null}</li>)}</ol>
            </div>)}
          </div> : editing.payload.ad.image_url ? <img className="metaAdsReviewImage" src={editing.payload.ad.image_url} alt="Criativo selecionado para publicação" loading="lazy" /> : null}
          <p className="ds-caption">A campanha, o conjunto e {(editing.payload.ad.extra_ads || []).length ? "os anúncios" : "o anúncio"} serão criados PAUSADOS no Meta. A ativação posterior é feita no Gerenciador.</p>
          {!locked && metaStepIssues(editing.payload, 3).length ? <p role="alert" className="metaAdsMissing">{metaStepIssues(editing.payload, 3).join(" ")}</p> : null}
        </section> : null}
        {stepIssue ? <p className="ds-caption metaAdsMissing" role="alert">{stepIssue}</p> : null}
        {editing.draft.status === "erro" && editing.draft.error ? <div className="ds-notice is-negative"><p className="ds-noticeTitle">{editing.draft.error}</p></div> : null}
        <div className="metaAdsFormActions">
          {editing.draft.ads_manager_url ? <a className="ds-link" href={editing.draft.ads_manager_url} target="_blank" rel="noreferrer">Abrir no Gerenciador de Anúncios</a> : <span />}
          <span className="metaAdsButtons">
            {step > 0 ? <button type="button" className="ds-button" disabled={Boolean(busy)}
              onClick={() => { setStep((step - 1) as MetaStep); setStepIssue(null); }}>Voltar</button> : null}
            {!locked ? <button type="submit" className="ds-button" disabled={Boolean(busy)}>{busy === "save" ? "Salvando…" : "Salvar rascunho"}</button> : null}
            {!locked && step < 3 ? <button type="button" className="ds-button is-primary" disabled={Boolean(busy)}
              onClick={advance}>{step === 0 ? "Escolher público" : step === 1 ? "Escolher criativo" : "Revisar campanha"}</button> : null}
            {!locked && step === 3 ? <button type="button" className="ds-button is-primary"
              disabled={Boolean(busy) || preflightBusy || !metaPreflight?.ready || !audienceApproved || metaStepIssues(editing.payload, 3).length > 0}
              onClick={() => void publish()}>{busy === "publish" ? "Criando no Meta…" : halfway ? "Terminar de criar no Meta (pausada)" : "Criar no Meta Ads (pausada)"}</button> : null}
          </span>
        </div>
      </form> : null}
    </Drawer>
  </section>;
}
