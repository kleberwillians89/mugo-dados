import type { Campaign, CampaignSummary, CartOverview, WaTemplate } from "../../app/emailMarketing";

export const CART_FIXTURE: CartOverview = {
  days: 30, provider: "shopify", simulated: { email: false, whatsapp: true },
  summary: { carts: 214, abandoned_value: 61240.5, contacted: 168, recovered: 31, recovered_value: 9874.3, recovery_rate: 18.5,
    bought_without_contact: 22, open: 19, by_channel: { email: { enviado: 160 }, whatsapp: { simulado: 74, pulado: 40 } } },
  settings: {
    enabled: true, steps: [{ channel: "email", delay_minutes: 60 }, { channel: "whatsapp", delay_minutes: 1440 }, { channel: "email", delay_minutes: 4320 }],
    email_subject: "{{primeiro_nome}}, seu carrinho está te esperando", email_consent: "todos",
    email_design: { blocks: [
      { type: "logo", align: "center" }, { type: "titulo", text: "{{primeiro_nome}}, seu carrinho está te esperando" },
      { type: "texto", text: "Separamos os itens que você escolheu. É só voltar e finalizar quando quiser." },
      { type: "produtos" }, { type: "botao", label: "Finalizar minha compra", href: "{{link_carrinho}}", align: "center" },
    ] },
    email_custom_html: null, whatsapp_number_id: null, whatsapp_template: "carrinho_abandonado", whatsapp_language: "pt_BR", whatsapp_variables: ["nome", "produto", "link"],
    whatsapp_consent: "consentimento", attribution_days: 7, webhooks_registered_at: "2026-11-11T20:00:00Z",
  },
  recent: [
    { checkout_id: "1", created_at: "2026-11-11T19:42:00Z", value: 389.7, items: 2, first_item: "Legging Move Preta", status: "aberto", steps_done: 1,
      recovered_value: null, last_touch: { channel: "email", status: "enviado", reason: null, at: "2026-11-11T20:42:00Z" } },
    { checkout_id: "2", created_at: "2026-11-10T14:05:00Z", value: 249.9, items: 1, first_item: "Macaquinho Flow", status: "recuperado", steps_done: 2,
      recovered_value: 249.9, last_touch: { channel: "whatsapp", status: "simulado", reason: null, at: "2026-11-11T14:05:00Z" } },
    { checkout_id: "3", created_at: "2026-11-09T22:30:00Z", value: 189.9, items: 1, first_item: "Top Essencial", status: "aberto", steps_done: 2,
      recovered_value: null, last_touch: { channel: "whatsapp", status: "pulado", reason: "sem consentimento de marketing", at: "2026-11-10T22:30:00Z" } },
    { checkout_id: "4", created_at: "2026-11-08T11:12:00Z", value: 529.8, items: 3, first_item: "Conjunto Skin", status: "comprou_sem_contato", steps_done: 0,
      recovered_value: null, last_touch: null },
  ],
};

export const WA_FIXTURE: { numbers: { id: string; display_phone_number: string; verified_name: string; status: string }[]; templates: WaTemplate[] } = {
  numbers: [{ id: "n1", display_phone_number: "+55 11 9••••-1161", verified_name: "Roove", status: "active" }],
  templates: [{ name: "carrinho_abandonado", language: "pt_BR", status: "APPROVED", category: "MARKETING", variables: 3,
    body: "Oi {{1}}! Vimos que você deixou {{2}} no carrinho. Ainda dá tempo de garantir: {{3}}" }],
};

export const CAMPAIGNS_FIXTURE: CampaignSummary[] = [
  { id: "c1", name: "Black Friday — aquecimento", subject: "{{primeiro_nome}}, a Black da Roove começou", status: "enviada",
    scheduled_at: "2026-11-07T12:00:00Z", started_at: "2026-11-07T12:00:00Z", finished_at: "2026-11-07T12:09:00Z",
    stats: { sent: 8412, delivered: 8270, open_rate: 41.2, click_rate: 6.8 }, created_at: "2026-11-05T10:00:00Z", updated_at: "2026-11-07T12:09:00Z" },
  { id: "c2", name: "Coleção Verão", subject: "Chegou: Verão 27", status: "agendada", scheduled_at: "2026-11-14T13:00:00Z", started_at: null,
    finished_at: null, stats: {}, created_at: "2026-11-10T10:00:00Z", updated_at: "2026-11-10T10:00:00Z" },
  { id: "c3", name: "Reativação 90 dias", subject: "", status: "rascunho", scheduled_at: null, started_at: null, finished_at: null, stats: {},
    created_at: "2026-11-11T10:00:00Z", updated_at: "2026-11-11T10:00:00Z" },
];

export const CAMPAIGN_FIXTURE: Campaign = {
  ...CAMPAIGNS_FIXTURE[2], preheader: "Separamos novidades para você", custom_html: null,
  subject: "{{primeiro_nome}}, sentimos sua falta",
  audience: { segment: "sem_compra", days: 90, only_consent: true },
  design: { blocks: [
    { type: "logo", align: "center" }, { type: "titulo", text: "{{primeiro_nome}}, sentimos sua falta", align: "center" },
    { type: "imagem", url: "https://images.exemplo.com/verao.jpg", alt: "Coleção Verão" },
    { type: "texto", text: "Faz um tempo que você não passa por aqui. Preparamos 15% OFF na sua próxima compra com o cupom VOLTEI.", align: "center" },
    { type: "botao", label: "Ver novidades", href: "{{link_loja}}", align: "center" },
  ] },
};
