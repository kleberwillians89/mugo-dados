import type { MetaLiveDeliveryStatus } from "../../app/metaAds";

export type Tone = "ok" | "wait" | "off" | "bad";
/** Uma frase do estado real na Meta, do jeito que qualquer pessoa entende. */
export function deliverySummary(status: MetaLiveDeliveryStatus | null): { tone: Tone; title: string; detail: string } {
  if (!status) return { tone: "wait", title: "Consultando a Meta…", detail: "" };
  const all = Object.values(status.objects).filter(Boolean) as { effective_status: string; status: string }[];
  const eff = all.map((o) => (o.effective_status || o.status || "").toUpperCase());
  const ads = Object.entries(status.objects).filter(([k]) => k === "ad_id" || k.startsWith("ad_")).map(([, o]) => (o?.effective_status || "").toUpperCase());
  const campaign = (status.objects.campaign_id?.effective_status || status.objects.campaign_id?.status || "").toUpperCase();
  if (eff.includes("PENDING_BILLING_INFO")) return { tone: "bad", title: "Falta forma de pagamento", detail: "Cadastre um cartão na conta de anúncios da Meta para a campanha rodar." };
  if (ads.length && ads.every((s) => s === "DISAPPROVED")) return { tone: "bad", title: "Recusada pela Meta", detail: "Os anúncios foram reprovados. Abra no Gerenciador para ver o motivo e trocar o criativo." };
  if (eff.includes("WITH_ISSUES")) return { tone: "bad", title: "Com problema na Meta", detail: "A Meta apontou um problema de entrega. Veja os detalhes no Gerenciador." };
  if (ads.some((s) => s === "PENDING_REVIEW" || s === "IN_PROCESS")) {
    const on = status.delivery?.state === "ativa";
    return { tone: "wait", title: on ? "Ativada · em análise na Meta" : "Em análise na Meta", detail: on ? "Começa a rodar assim que a Meta aprovar (normalmente em minutos, até 24 h)." : "A Meta está revisando os anúncios." };
  }
  if (status.joined ? ads.some((s) => s === "ACTIVE") : campaign === "ACTIVE" && ads.some((s) => s === "ACTIVE"))
    return { tone: "ok", title: "Ativa · rodando", detail: ads.some((s) => s === "DISAPPROVED") ? "Algum anúncio foi recusado, os outros estão rodando." : "Os anúncios estão sendo mostrados e gastando a verba." };
  if (status.joined && ads.some((s) => s === "CAMPAIGN_PAUSED" || s === "ADSET_PAUSED"))
    return { tone: "off", title: "Anúncio ligado, campanha pausada", detail: "Este anúncio só roda quando a campanha original estiver ativa." };
  return { tone: "off", title: "Pausada", detail: "Nada está sendo gasto." };
}

