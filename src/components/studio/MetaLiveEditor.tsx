import { useEffect, useState } from "react";
import { getActiveClientId } from "../../app/activeClient";
import {
  listShopPromotionCodes, updateLiveMetaBudget, updateLiveMetaCreative,
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
  const [codes, setCodes] = useState<ShopPromotionCode[]>([]);
  const [codesBusy, setCodesBusy] = useState(false);
  const [codesMessage, setCodesMessage] = useState("");
  const [busy, setBusy] = useState<"budget" | "creative" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const ids = draft.meta_ids || {};
  const singleImage = draft.status === "publicada" && !!ids.ad_id &&
    (ids.ad_ids || [ids.ad_id]).length === 1 &&
    (draft.payload.ad.format || "single") === "single" &&
    draft.payload.ad.media_type !== "video";

  useEffect(() => {
    setBudget(draft.payload.daily_budget);
    setAd({ ...draft.payload.ad });
    setError(""); setNotice("");
  }, [draft.id, draft.payload]);

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
    <button className="ds-button" type="button" onClick={() => { setOpen(true); setCodes([]); setCodesMessage(""); }}>
      Editar no Mugô Verso
    </button>
    <Drawer open={open} width="lg" title={`Editar na Meta · ${draft.payload.name}`}
      description="As alterações são enviadas à conta Meta da empresa selecionada. Nada é salvo automaticamente."
      onClose={() => { if (!busy) setOpen(false); }}>
      <div className="metaAdsForm">
        {error ? <p role="alert" className="studioError">{error}</p> : null}
        {notice ? <p role="status" className="ds-noticeText">{notice}</p> : null}

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
            {singleImage ? <button type="button" className="ds-button" style={{ marginLeft: 8 }}
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
