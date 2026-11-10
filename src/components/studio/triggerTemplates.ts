import type { RuleInput } from "../../app/engagement";

/**
 * Modelos prontos de gatilho (Comentários > Gatilhos). Abrem o formulário já preenchido e DESLIGADO:
 * a equipe troca o link {LINK} e liga quando quiser.
 *
 * Instagram não avisa "acabou de seguir" (não existe evento de novo seguidor na API oficial), e a marca
 * não pode mandar Direct primeiro. O jeito permitido é o "siga e comente": a legenda pede para seguir e
 * comentar a palavra, e o comentário dispara o Direct.
 */
export type TriggerTemplate = {
  id: string;
  title: string;
  /** Uma linha: o que acontece. */
  summary: string;
  /** O que escrever na legenda/story para o gatilho disparar. */
  caption: string;
  rule: Omit<RuleInput, "active" | "media_id">;
};

export const TRIGGER_TEMPLATES: TriggerTemplate[] = [
  {
    id: "quero",
    title: "Comente QUERO",
    summary: "Quem comentar QUERO recebe o link no Direct.",
    caption: "Comenta QUERO que eu te mando o link no Direct 💌",
    rule: {
      name: "Comente QUERO → link",
      keywords: ["quero", "eu quero", "link"],
      public_reply: "Te mandei no Direct, {nome}! 💌",
      dm_message: "Oi {nome}! Aqui está o link que você pediu: {LINK}",
      ai_greeting: false,
    },
  },
  {
    id: "siga-comente",
    title: "Siga e comente (boas-vindas)",
    summary: "O jeito permitido de dar oi pra quem acabou de seguir: a legenda pede para seguir e comentar.",
    caption: "Segue o perfil e comenta EU que eu te mando um presente no Direct 🎁",
    rule: {
      name: "Siga e comente → boas-vindas",
      keywords: ["eu", "eu quero", "presente"],
      public_reply: "Bem-vindo(a), {nome}! Olha o Direct 🎁",
      dm_message: "Seu presente de boas-vindas: {LINK}",
      ai_greeting: true,
    },
  },
  {
    id: "preco",
    title: "Pergunta de preço",
    summary: "Quem perguntar preço/valor recebe o link do produto ou catálogo.",
    caption: "Quer saber o valor? Comenta PREÇO",
    rule: {
      name: "Preço → catálogo",
      keywords: ["preço", "preco", "valor", "quanto custa", "quanto"],
      public_reply: "Te mandei os valores no Direct, {nome}!",
      dm_message: "Oi {nome}! Os valores e o link para comprar estão aqui: {LINK}",
      ai_greeting: false,
    },
  },
  {
    id: "cupom",
    title: "Cupom de desconto",
    summary: "Quem comentar CUPOM recebe o código e o link da loja.",
    caption: "Comenta CUPOM e ganha desconto na primeira compra",
    rule: {
      name: "Cupom → código",
      keywords: ["cupom", "desconto"],
      public_reply: "Cupom no seu Direct, {nome}! 🏷️",
      dm_message: "Seu cupom: CODIGO10 — use aqui: {LINK}",
      ai_greeting: false,
    },
  },
  {
    id: "lista",
    title: "Lista VIP / lançamento",
    summary: "Quem comentar LISTA entra no aviso do lançamento (link do WhatsApp ou formulário).",
    caption: "Comenta LISTA para ser avisado(a) primeiro do lançamento",
    rule: {
      name: "Lista VIP → WhatsApp",
      keywords: ["lista", "vip", "me avisa"],
      public_reply: "Você está na lista, {nome}! Olha o Direct ✨",
      dm_message: "Entra aqui para receber o aviso antes de todo mundo: {LINK}",
      ai_greeting: true,
    },
  },
];
