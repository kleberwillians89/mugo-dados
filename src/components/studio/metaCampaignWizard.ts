import type { AdPayload } from "../../app/metaAds";

export const META_STEPS = ["Campanha", "Público", "Criativo", "Revisão"] as const;
export type MetaStep = 0 | 1 | 2 | 3;

/** Local validation only; Meta does final provider-side validation. */
export function metaStepIssues(payload: AdPayload, step: MetaStep): string[] {
  const issues: string[] = [];
  if (step === 0) {
    if (!payload.name.trim()) issues.push("Informe o nome da campanha.");
    if (!Number.isFinite(payload.daily_budget) || payload.daily_budget < 6) issues.push("Informe uma verba diária válida (mínimo R$ 6).");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(payload.start_date) || !/^\d{4}-\d{2}-\d{2}$/.test(payload.end_date)
      || payload.end_date <= payload.start_date) issues.push("Confira as datas: o encerramento precisa ser posterior ao início.");
  } else if (step === 1) {
    const a = payload.audience;
    if (!Number.isInteger(a.age_min) || !Number.isInteger(a.age_max)
      || a.age_min < 18 || a.age_max > 65 || a.age_min > a.age_max) issues.push("Defina uma faixa etária válida entre 18 e 65 anos.");
    if (!["todos", "mulheres", "homens"].includes(a.gender)) issues.push("Selecione o gênero.");
    const p = payload.placements;
    if (p?.mode === "manual" && (!p.platforms.length || p.platforms.some(platform => !(p[platform] || []).length)))
      issues.push("Selecione pelo menos um canal e um posicionamento em cada canal escolhido.");
  } else if (step === 2) {
    const ad = payload.ad;
    if (!ad.primary_text.trim()) issues.push("Escreva o texto principal.");
    if (ad.media_type === "video") {
      if (!/^https:\/\/\S+/i.test((ad.video_url || "").trim())) issues.push("Selecione um vídeo com URL HTTPS válida.");
    } else if (!/^https:\/\/[^\s.]+(?:\.[^\s]+|\/)/i.test(ad.image_url.trim())) issues.push("Selecione uma imagem do Calendário, Instagram ou Biblioteca.");
    if (["trafego", "vendas", "leads"].includes(payload.objective) && !/^https:\/\/[^\s.]+(?:\.[^\s]+|\/)/i.test(ad.link.trim()))
      issues.push("Informe o link HTTPS do destino para este objetivo.");
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
