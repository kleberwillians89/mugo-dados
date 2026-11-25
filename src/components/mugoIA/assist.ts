import { createContext } from "react";
import type { AppRoute } from "../../app/routes";

/** Telas de criação onde a Mugô IA aparece no cabeçalho (mesmo cérebro; a tela só muda o foco da ajuda). */
export const ASSIST_SCREENS: Partial<Record<AppRoute, { label: string; suggestions: string[] }>> = {
  briefing: { label: "Briefing", suggestions: ["Monta o briefing da próxima campanha da marca", "O que não pode faltar neste briefing para a equipe executar?"] },
  redacao: { label: "Redação", suggestions: ["Escreve 3 opções de legenda para o próximo post, no tom da marca", "Revisa o texto que vou colar aqui no tom da marca"] },
  campaigns: { label: "Social Media", suggestions: ["Sugere 5 pautas para a próxima semana com base no que está funcionando", "O que os concorrentes estão postando agora?"] },
  calendar: { label: "Calendário", suggestions: ["Quais datas comerciais vêm aí e o que postar em cada uma?", "Monta a semana de posts da próxima data comercial"] },
  email_marketing: { label: "E-mail Marketing", suggestions: ["Cria um e-mail para a próxima data comercial", "Cria um e-mail para quem não compra há 90 dias"] },
  media: { label: "Mídia On", suggestions: ["Monta uma campanha de vendas na Meta com R$ 50 por dia por 14 dias", "O que os concorrentes estão anunciando agora?"] },
  planning: { label: "Planejamento", suggestions: ["Quais objetivos e fases fazem sentido para o próximo trimestre?", "O que o mercado da marca pede nos próximos 60 dias?"] },
  production: { label: "Eventos", suggestions: ["Ideias de ativação para o próximo evento da marca", "Monta o briefing do próximo evento"] },
  creators: { label: "Criadores", suggestions: ["Que perfil de criador combina com a marca agora?", "Monta o briefing para os criadores da próxima campanha"] },
};

export type AssistValue = { screen: AppRoute; canCreate: boolean } | null;
export const MugoIAAssistContext = createContext<AssistValue>(null);
