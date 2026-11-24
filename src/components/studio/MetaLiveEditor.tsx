import { useEffect, useState } from "react";
import { getActiveClientId } from "../../app/activeClient";
import {
  listShopPromotionCodes, updateLiveMetaBudget, updateLiveMetaCreative, readLiveMetaStructure, changeLiveMetaObjectStatus, updateLiveMetaAdsetBudget, readLiveMetaObjectInsights,
  type LiveMetaStructure, type LiveMetaObjectInsights,
  type AdDraft, type AdPayload, type ShopPromotionCode,
} from "../../app/metaAds";
import type { CalendarItem } from "../../app/studio";
import Drawer from "../Drawer";
import MetaCreativeStudio from "./MetaCreativeStudio";

type Props = { draft: AdDraft; month: string; calendar: CalendarItem[]; onUpdated: (draft: AdDraft) => void };

const currency = (value: number) => value.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const message = (cause: unknown) => cause instanceof Error ? cause.message : "Não foi possível salvar na Meta.";

export default function MetaLiveEditor({ draft, month, calendar, onUpdated }: Props) {
  const clientId = getActiveClientId();
  const [open, setOpen] = useState(false);
  const [budget, setBudget] = useState(draft.payload.daily_budget);
  const [ad, setAd] = useState<AdPayload["ad"]>({ ...draft.payload.ad });
  const [structure, setStructure] = useState<LiveMetaStructure | null>(null);
  const [structureBusy, setStructureBusy] = useState(false);
  const [objectBusy, setObjectBusy] = useState<string | null>(null);
  const [insights, setInsights] = useState<Record<string, LiveMetaObjectInsights>>({});
  const [insightsBusy, setInsightsBusy] = useState<string | null>(null);
  const [adsetBudgets, setAdsetBudgets] = useState<Record<string, string>>({});
  const [codes, setCodes] = useState<ShopPromotionCode[]>([]);
  const [codesBusy, setCodesBusy] = useState(false);
  const [codesMessage, setCodesMessage] = useState("");
  const [busy, setBusy] = useState<"budget" | "creative" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const ids = draft.meta_ids || {};
  const singleImage = draft.status === "publicada" && !!ids.ad_id &&
    (!Array.isArray(ids.ad_ids) || ids.ad_ids.length === 1) &&
    (draft.payload.ad.format || "single") === "single" &&
    draft.payload.ad.media_type !== "video";

  useEffect(() => {
    setBudget(draft.payload.daily_budget);
    setAd({ ...draft.payload.ad });
    setError(""); setNotice("");
  }, [draft.id, draft.payload]);

  async function loadStructure() {
    setStructureBusy(true); setError("");
    try {
      const result = await readLiveMetaStructure(draft.id);
      if (getActiveClientId() === clientId) setStructure(result);
    } catch (cause) {
      if (getActiveClientId() === clientId) { setStructure(null); setError(message(cause)); }
    } finally { setStructureBusy(false); }
  }

  async function applyObjectStatus(level: "adset" | "ad", id: string, name: string, status: string) {
    const next = status === "ACTIVE" ? "PAUSED" : "ACTIVE";
    const description = next === "ACTIVE" ? "ATIVAR" : "PAUSAR";
    if (!window.confirm(`${description} ${level === "adset" ? "o conjunto" : "o anúncio"} "${name}" na Meta? ${next === "ACTIVE" ? "Se a campanha e os demais níveis estiverem ativos, poderá haver gasto de verba." : "A entrega desse item será interrompida."}`)) return;
    setObjectBusy(id); setError(""); setNotice("");
    try {
      await changeLiveMetaObjectStatus(draft.id, level, id, next);
      if (getActiveClientId() !== clientId) return;
      await loadStructure();
      setNotice("Status atualizado e confirmado pela Meta.");
    } catch (cause) { if (getActiveClientId() === clientId) setError(message(cause)); }
    finally { setObjectBusy(null); }
  }

  async function applyAdsetBudget(id: string, name: string, originalCents: number) {
    const newBudget = Number(adsetBudgets[id] ?? String(originalCents / 100));
    if (!Number.isFinite(newBudget) || newBudget < 6 || newBudget > 1_000_000) {
      setError("Informe um orçamento diário válido a partir de R$ 6,00.");
      return;
    }
    if (!window.confirm(`Alterar a verba diária APENAS do conjunto "${name}" de ${currency(originalCents / 100)} para ${currency(newBudget)}? Essa alteração pode gerar gastos reais imediatamente.`)) return;
    setObjectBusy(id); setError(""); setNotice("");
    try {
      await updateLiveMetaAdsetBudget(draft.id, id, newBudget);
      if (getActiveClientId() !== clientId) return;
      await loadStructure();
      setAdsetBudgets((old) => { const next = { ...old }; delete next[id]; return next; });
      setNotice("Orçamento do conjunto atualizado e confirmado diretamente na Meta.");
    } catch (cause) { if (getActiveClientId() === clientId) setError(message(cause)); }
    finally { setObjectBusy(null); }
  }

  async function loadObjectInsights(level: "adset" | "ad", id: string) {
    const key = `${level}:${id}`;
    setInsightsBusy(key); setError("");
    try {
      const result = await readLiveMetaObjectInsights(draft.id, level, id);
      if (getActiveClientId() === clientId) setInsights((current) => ({ ...current, [key]: result }));
    } catch (cause) { if (getActiveClientId() === clientId) setError(message(cause)); }
    finally { setInsightsBusy(null); }
  }

  function insightSummary(data: LiveMetaObjectInsights) {
    if (!data.has_data) return <p className="ds-caption">Sem dados disponíveis para este item nos últimos 7 dias.</p>;
    return <div className="ds-caption" role="status" style={{ padding: 8, marginTop: 6 }}>
      <strong>Últimos 7 dias (Meta)</strong> · Gasto {currency(data.spend)} · Alcance {data.reach.toLocaleString("pt-BR")}
      {" · "}Impressões {data.impressions.toLocaleString("pt-BR")} · Cliques no link {data.link_clicks.toLocaleString("pt-BR")}
      {" · "}CTR {data.ctr.toFixed(2)}% · CPC {currency(data.cpc)} · CPM {currency(data.cpm)}
      {data.actions.length ? <details><summary>Resultados por evento ({data.actions.length})</summary>
        <ul>{data.actions.map((event, i) => <li key={`${event.type}:${i}`}>{event.type}: {event.value.toLocaleString("pt-BR")}</li>)}</ul>
      </details> : null}
    </div>;
  }

  async function loadCodes() {
    setCodesBusy(true); setCodesMessage("");
    try {
      const found = await listShopPromotionCodes();
      if (getActiveClientId() !== clientId) return;
      setCodes(found.codes);
      if (!found.codes.length) setCodesMessage("Nenhum código encontrado na loja conectada.");
    } catch (cause) {
      if (getActiveClientId() === clientId) {
        setCodes([]);
        setCodesMessage(message(cause) + " Se necessário, reconecte Shopify em Integrações para autorizar read_discounts.");
      }
    } finally { setCodesBusy(false); }
  }

  async function applyBudget() {
    if (!Number.isFinite(budget) || budget <= 0 || busy) return;
    if (!window.confirm(`Alterar o orçamento na Meta de ${currency(draft.payload.daily_budget)}/dia para ${currency(budget)}/dia? Essa alteração pode afetar gastos reais imediatamente.`)) return;
    setBusy("budget"); setError(""); setNotice("");
    try {
      const response = await updateLiveMetaBudget(draft.id, budget);
      if (getActiveClientId() !== clientId) return;
      onUpdated(response.draft);
      setNotice("Orçamento alterado e confirmado diretamente na Meta.");
    } catch (cause) { if (getActiveClientId() === clientId) setError(message(cause)); }
    finally { setBusy(null); }
  }

  async function applyCreative() {
    if (!singleImage || busy) return;
    if (!ad.image_url || !ad.primary_text || !ad.link) {
      setError("Informe imagem, texto principal e link.");
      return;
    }
    if (!window.confirm("Substituir o criativo desse anúncio na Meta? A plataforma criará um novo criativo, atualizará o anúncio existente e a Meta poderá revisar a alteração.")) return;
    setBusy("creative"); setError(""); setNotice("");
    try {
      const response = await updateLiveMetaCreative(draft.id, {
        primary_text: ad.primary_text, headline: ad.headline, description: ad.description,
        cta: ad.cta, link: ad.link, image_url: ad.image_url,
      });
      if (getActiveClientId() !== clientId) return;
      onUpdated(response.draft);
      setNotice("Novo criativo confirmado na Meta. A alteração pode passar por análise.");
    } catch (cause) { if (getActiveClientId() === clientId) setError(message(cause)); }
    finally { setBusy(null); }
  }

  return <>
    <button className="ds-button" type="button" onClick={() => { setOpen(true); setCodes([]); setCodesMessage(""); void loadStructure(); }}>
      Editar no Mugô Verso
    </button>
    <Drawer open={open} width="lg" title={`Editar na Meta · ${draft.payload.name}`}
      description="As alterações são enviadas à conta Meta da empresa selecionada. Nada é salvo automaticamente."
      onClose={() => { if (!busy) setOpen(false); }}>
      <div className="metaAdsForm">
        {error ? <p role="alert" className="studioError">{error}</p> : null}
        {notice ? <p role="status" className="ds-noticeText">{notice}</p> : null}

        <h3>Conjuntos de anúncios e anúncios</h3>
        <p className="ds-caption">Estrutura consultada na Meta desta empresa. Você pode ativar ou pausar cada item individualmente; ativar um item não altera automaticamente o status dos demais níveis.</p>
        <button className="ds-button" type="button" onClick={() => void loadStructure()} disabled={structureBusy || !!objectBusy}>
          {structureBusy ? "Consultando a Meta…" : "Atualizar estrutura da Meta"}
        </button>
        {structure ? <>
          <small className="ds-caption">Sincronizado: {new Date(structure.checked_at).toLocaleString("pt-BR")}</small>
          <h4>Conjuntos ({structure.adsets.length})</h4>
          {structure.adsets.map((item) => <div key={item.id} className="ds-noticeText" style={{ padding: 10, borderBottom: "1px solid #e3e6eb" }}>
            <strong>{item.name || item.id}</strong> · {item.effective_status || item.status}
            {item.daily_budget ? ` · Verba R$ ${(Number(item.daily_budget) / 100).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}/dia` : ""}
            {item.daily_budget && Number(item.daily_budget) > 0 ? <div style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap", marginTop: 8 }}>
              <label className="ds-field">Verba diária deste conjunto (R$)
                <input type="number" min={6} max={1000000} step={0.01}
                  aria-label={`Verba diária do conjunto ${item.name || item.id}`}
                  disabled={!!objectBusy || structureBusy}
                  value={adsetBudgets[item.id] ?? String(Number(item.daily_budget) / 100)}
                  onChange={(e) => setAdsetBudgets((old) => ({ ...old, [item.id]: e.target.value }))} />
              </label>
              <button type="button" className="ds-button" disabled={!!objectBusy || structureBusy || Number(adsetBudgets[item.id] ?? String(Number(item.daily_budget) / 100)) === Number(item.daily_budget) / 100}
                onClick={() => void applyAdsetBudget(item.id, item.name || item.id, Number(item.daily_budget))}>
                {objectBusy === item.id ? "Confirmando na Meta…" : "Salvar verba do conjunto"}
              </button>
            </div> : <small className="ds-caption">Orçamento definido na campanha ou vitalício; edição diária individual indisponível.</small>}
            <button type="button" className="ds-button" style={{ marginLeft: 8 }} disabled={!!objectBusy || structureBusy}
              onClick={() => void loadObjectInsights("adset", item.id)}>
              {insightsBusy === `adset:${item.id}` ? "Consultando…" : insights[`adset:${item.id}`] ? "Atualizar métricas" : "Ver métricas (7 dias)"}
            </button>
            {insights[`adset:${item.id}`] ? insightSummary(insights[`adset:${item.id}`]) : null}
            <button type="button" className="ds-button" style={{ marginLeft: 8 }} disabled={!!objectBusy || structureBusy}
              onClick={() => void applyObjectStatus("adset", item.id, item.name, item.status)}>
              {objectBusy === item.id ? "Confirmando…" : item.status === "ACTIVE" ? "Pausar conjunto" : "Ativar conjunto"}
            </button>
          </div>)}
          <h4>Anúncios ({structure.ads.length})</h4>
          {structure.ads.map((item) => <div key={item.id} className="ds-noticeText" style={{ padding: 10, borderBottom: "1px solid #e3e6eb" }}>
            {item.creative?.thumbnail_url ? <img src={item.creative.thumbnail_url} alt="" style={{ maxWidth: 80, verticalAlign: "middle", marginRight: 10 }} /> : null}
            <strong>{item.name || item.id}</strong> · {item.effective_status || item.status}
            <button type="button" className="ds-button" style={{ marginLeft: 8 }} disabled={!!objectBusy || structureBusy}
              onClick={() => void loadObjectInsights("ad", item.id)}>
              {insightsBusy === `ad:${item.id}` ? "Consultando…" : insights[`ad:${item.id}`] ? "Atualizar métricas" : "Ver métricas (7 dias)"}
            </button>
            {insights[`ad:${item.id}`] ? insightSummary(insights[`ad:${item.id}`]) : null}
            <button type="button" className="ds-button" style={{ marginLeft: 8 }} disabled={!!objectBusy || structureBusy}
              onClick={() => void applyObjectStatus("ad", item.id, item.name, item.status)}>
              {objectBusy === item.id ? "Confirmando…" : item.status === "ACTIVE" ? "Pausar anúncio" : "Ativar anúncio"}
            </button>
          </div>)}
        </> : !structureBusy ? <p className="ds-caption">Clique em Atualizar estrutura da Meta para consultar conjuntos e anúncios.</p> : null}

        <h3>Orçamento diário</h3>
        <p className="ds-caption">A Meta aplica mudanças de verba à campanha ou ao conjunto, conforme a configuração original. Isso pode alterar o gasto imediatamente.</p>
        <label className="ds-field">Valor por dia (R$)
          <input type="number" min={6} step={0.01} value={budget}
            onChange={(event) => setBudget(Number(event.target.value))} />
        </label>
        <button type="button" className="ds-button is-primary" onClick={() => void applyBudget()} disabled={!!busy || !Number.isFinite(budget) || budget <= 0 || budget === draft.payload.daily_budget}>
          {busy === "budget" ? "Confirmando na Meta…" : "Confirmar nova verba na Meta"}
        </button>

        <h3>Códigos promocionais da loja</h3>
        <p className="ds-caption">Consulta os códigos cadastrados na Shopify desta empresa. A consulta não cria nem ativa descontos.</p>
        <button type="button" className="ds-button" onClick={() => void loadCodes()} disabled={codesBusy}>
          {codesBusy ? "Consultando Shopify…" : "Buscar cupons na Shopify"}
        </button>
        {codesMessage ? <p role="status" className="ds-caption">{codesMessage}</p> : null}
        {codes.length ? <div className="metaAdsForm">
          {codes.map((c) => <div key={c.code} className="ds-noticeText" style={{ padding: 9, borderBottom: "1px solid #e3e6eb" }}>
            <strong>{c.code}</strong> · {c.title || "Promoção"} · {c.status || "Status indisponível"}
            <button type="button" className="ds-button" style={{ marginLeft: 8 }}
              onClick={() => { navigator.clipboard?.writeText(c.code); }}>Copiar</button>
            {singleImage && c.status === "ACTIVE" ? <button type="button" className="ds-button" style={{ marginLeft: 8 }}
              onClick={() => setAd((prev) => ({ ...prev, primary_text: `${prev.primary_text.trim()}\nCupom: ${c.code}` }))}>
              Inserir no texto
            </button> : null}
          </div>)}
        </div> : null}

        <h3>Criativo publicado</h3>
        {singleImage ? <>
          <p className="ds-caption">Altere imagem, texto, título, descrição, CTA ou destino. A Meta poderá exigir nova análise. Carrosséis, vídeos e anúncios múltiplos precisam de um editor individual específico.</p>
          <label className="ds-field">Texto principal
            <textarea rows={4} value={ad.primary_text} onChange={(e) => setAd((a) => ({ ...a, primary_text: e.target.value }))} />
          </label>
          <label className="ds-field">Título
            <input value={ad.headline} onChange={(e) => setAd((a) => ({ ...a, headline: e.target.value }))} />
          </label>
          <label className="ds-field">Descrição
            <input value={ad.description} onChange={(e) => setAd((a) => ({ ...a, description: e.target.value }))} />
          </label>
          <label className="ds-field">Destino do anúncio
            <input type="url" value={ad.link} onChange={(e) => setAd((a) => ({ ...a, link: e.target.value }))} />
          </label>
          <label className="ds-field">Botão (CTA)
            <select value={ad.cta} onChange={(e) => setAd((a) => ({ ...a, cta: e.target.value }))}>
              <option value="LEARN_MORE">Saiba mais</option>
              <option value="SHOP_NOW">Comprar agora</option>
              <option value="SIGN_UP">Cadastre-se</option>
              <option value="GET_OFFER">Obter oferta</option>
              <option value="CONTACT_US">Fale conosco</option>
            </select>
          </label>
          <MetaCreativeStudio clientId={clientId} month={month} calendar={calendar} ad={ad}
            onChoose={(patch) => {
              if (patch.media_type === "video" || patch.format === "carousel" || patch.format === "multi") {
                setError("Para esta edição, escolha uma imagem única. Vídeos e carrosséis ainda não podem ser substituídos aqui.");
                return;
              }
              setAd((prev) => ({ ...prev, ...patch }));
            }} />
          <button type="button" className="ds-button is-primary" disabled={!!busy} onClick={() => void applyCreative()}>
            {busy === "creative" ? "Confirmando novo criativo…" : "Substituir criativo na Meta"}
          </button>
        </> : <p className="ds-caption">O anúncio tem vídeo, carrossel ou múltiplas peças. A edição deste formato ainda não foi habilitada para evitar mudanças no anúncio errado. O orçamento continua editável acima.</p>}
      </div>
    </Drawer>
  </>;
}
