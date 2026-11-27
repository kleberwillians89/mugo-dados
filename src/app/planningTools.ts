import { BarChart3, Search } from "lucide-react";
import type { AppRoute } from "./routes";

/** "Explorar ferramentas" dentro do Planejamento (abaixo de Metas), nesta ordem. Cada uma aparece só com permissão.
 *  Saúde da Marca foi para CRM, Clipping para Criar conteúdo, Comentários para Relacionamento e Redes Sociais tem card próprio. */
export const PLANNING_TOOL_INFO: { route: AppRoute; label: string; description: string; icon: typeof Search }[] = [
  { route: "radar", label: "Radar", description: "Sinais e oportunidades para explorar.", icon: Search },
  { route: "benchmark", label: "Benchmarking", description: "Referências e movimentos dos concorrentes.", icon: BarChart3 },
];
export const PLANNING_TOOLS: AppRoute[] = PLANNING_TOOL_INFO.map((tool) => tool.route);
