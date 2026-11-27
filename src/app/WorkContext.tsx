import { createContext, useContext } from "react";
import type { AppRoute } from "./routes";

/**
 * O que o Kanban integrado precisa saber sobre a tela e a pessoa. Quem vê quais tarefas continua decidido no
 * backend (/tasks e /client-tasks): aqui só se escolhe qual quadro mostrar, com a mesma regra da página Tarefas.
 * - "team": equipe Mugô e quem gerencia tarefas (o backend dá tudo ao admin e só as próprias a cada integrante);
 * - "client": os demais membros da empresa (só as tarefas marcadas como visíveis ao cliente).
 */
export type WorkValue = {
  route: AppRoute;
  clientId: string;
  userId: string | null;
  mode: "team" | "client" | null;
  canManage: boolean;
  isAgency: boolean;
};

export const WorkContext = createContext<WorkValue | null>(null);
export const useWork = () => useContext(WorkContext);
