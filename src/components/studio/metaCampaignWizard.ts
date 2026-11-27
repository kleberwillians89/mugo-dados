import type { AdPayload } from "../../app/metaAds";
import { metaOf, needsVideo } from "./metaStructure";

/** Os mesmos 3 níveis do Gerenciador de Anúncios, e a revisão antes de criar pausada. */
export const META_STEPS = ["Campanha", "Conjunto de anúncios", "Anúncio", "Revisão"] as const;
export type MetaStep = 0 | 1 | 2 | 3;
const MIN_DAILY = 6;
const https = (v: string) => /^https:\/\/[^\s.]+(?:\.[^\s]+|\/)/i.test(v.trim());

/** Local validation only; Meta does final provider-side validation. */
export function metaStepIssues(payload: AdPayload, step: MetaStep): string[] {
  const issues: string[] = [];
  const m = metaOf(payload);
  if (step === 0) {
    if (!payload.name.trim()) issues.push("Informe o nome da campanha.");
    if (m.budget_type === "daily" && (!Number.isFinite(m.budget) || m.budget < MIN_DAILY)) issues.push(`Informe um orçamento diário válido (mínimo R$ ${MIN_DAILY}).`);
    if (m.budget_type === "lifetime" && (!Number.isFinite(m.budget) || m.budget <= 0)) issues.push("Informe o orçamento total.");
    if ((m.bid_strategy === "COST_CAP" || m.bid_strategy === "LOWEST_COST_WITH_BID_CAP") && !(Number(m.bid_amount) > 0))
      issues.push(m.bid_strategy === "COST_CAP" ? "Informe a meta de custo por resultado." : "Informe o limite de lance.");
    if (m.bid_strategy === "LOWEST_COST_WITH_MIN_ROAS" && !(Number(m.roas_floor) > 0)) issues.push("Informe a meta de ROAS.");
  } else if (step === 1) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(payload.start_date)) issues.push("Informe a data de início.");
    if (m.has_end_date && (!/^\d{4}-\d{2}-\d{2}$/.test(payload.end_date) || payload.end_date <= payload.start_date))
      issues.push("Confira as datas: o término precisa ser depois do início.");
    if (m.budget_type === "lifetime") {
      const days = Math.max(1, Math.round((Date.parse(payload.end_date) - Date.parse(payload.start_date)) / 86_400_000) + 1);
      if (m.budget < MIN_DAILY * days) issues.push(`Orçamento total baixo para ${days} dias (mínimo R$ ${MIN_DAILY * days}).`);
    }
    if (m.conversion_location === "APP" && !m.app?.store_url) issues.push("Escolha o app e a loja.");
    if (m.conversion_location === "ON_AD" && !m.lead_form) issues.push("Escolha o formulário instantâneo.");
    if (m.conversion_location === "PHONE_CALL" && (m.phone_number || "").replace(/\D/g, "").length < 10) issues.push("Informe o telefone com DDI e DDD.");
    if (m.conversion_location === "MESSAGING" && !m.messaging_apps.length) issues.push("Escolha pelo menos um app de mensagem.");
    const a = payload.audience;
    if (!Number.isInteger(a.age_min) || !Number.isInteger(a.age_max)
      || a.age_min < 18 || a.age_max > 65 || a.age_min > a.age_max) issues.push("Defina uma faixa etária válida entre 18 e 65 anos.");
    if (!["todos", "mulheres", "homens"].includes(a.gender)) issues.push("Selecione o gênero.");
    const p = payload.placements;
    if (p?.mode === "manual" && (!p.platforms.length || p.platforms.some(platform => !(p[platform] || []).length)))
      issues.push("Selecione pelo menos um canal e um posicionamento em cada canal escolhido.");
  } else if (step === 2) {
    const ad = payload.ad;
    const existing = m.use_existing_post;
    if (existing && !ad.instagram_post_id) issues.push("Escolha a publicação existente do Instagram.");
    if (!existing && !ad.primary_text.trim()) issues.push("Escreva o texto principal.");
    (ad.extra_ads || []).forEach((extra, i) => {
      if (extra.format === "carousel" ? (extra.cards || []).length < 2 : extra.media_type === "video" ? !/^https:\/\/\S+/i.test(extra.video_url || "") : !/^https:\/\//i.test(extra.image_url || ""))
        issues.push(extra.format === "carousel" ? `Anúncio ${i + 2}: escolha pelo menos 2 imagens para o carrossel.` : `Anúncio ${i + 2}: escolha a imagem ou o vídeo.`);
    });
    if (!existing) {
      if (ad.format === "carousel" || ad.format === "multi") {
        if ((ad.cards || []).length < 2) issues.push(ad.format === "carousel" ? "Anúncio 1: escolha pelo menos 2 imagens para o carrossel." : "Escolha pelo menos 2 imagens para os anúncios.");
      } else if (ad.media_type === "video") {
        if (!/^https:\/\/\S+/i.test((ad.video_url || "").trim())) issues.push("Selecione um vídeo com URL HTTPS válida.");
      } else if (!https(ad.image_url)) issues.push("Selecione uma imagem do Calendário, Instagram ou Biblioteca.");
    }
    if (needsVideo(m.performance_goal) && ad.media_type !== "video" && !(ad.extra_ads || []).some((x) => x.media_type === "video"))
      issues.push("A meta de desempenho escolhida conta visualizações de vídeo: use um vídeo.");
    if (m.conversion_location === "WEBSITE" && !https(ad.link)) issues.push("Informe a URL do site (https://).");
  } else {
    for (const prior of [0, 1, 2] as const) issues.push(...metaStepIssues(payload, prior));
  }
  return issues;
}

/** Texto curto dos públicos da conta escolhidos (prévia e revisão). */
export function accountAudienceText(a: AdPayload["audience"]): string {
  const parts: string[] = [];
  if (a.saved_audience) parts.push(`Público salvo: ${a.saved_audience.name}`);
  if (a.custom_audiences?.length) parts.push(`Inclui: ${a.custom_audiences.map((x) => x.name).join(", ")}`);
  if (a.excluded_audiences?.length) parts.push(`Exclui: ${a.excluded_audiences.map((x) => x.name).join(", ")}`);
  return parts.join(" · ");
}
