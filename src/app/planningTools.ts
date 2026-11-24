import type { AppRoute } from "./routes";

/** "Explorar ferramentas" dentro do Planejamento (abaixo de Metas), nesta ordem. Cada uma aparece só com permissão. */
export const PLANNING_TOOL_INFO: { route: AppRoute; label: string; description: string }[] = [
  { route: "brand_health", label: "Saúde da Marca", description: "Presença, sentimento e consistência da marca." },
  { route: "radar", label: "Radar", description: "Sinais e oportunidades para explorar." },
  { route: "benchmark", label: "Benchmarking", description: "Referências e movimentos dos concorrentes." },
  { route: "clipping", label: "Clipping", description: "Notícias, alertas e menções da marca." },
  { route: "engagement", label: "Comentários", description: "O que o público comenta e pergunta." },
  { route: "channels", label: "Redes Sociais", description: "Desempenho dos canais sociais conectados." },
];
export const PLANNING_TOOLS: AppRoute[] = PLANNING_TOOL_INFO.map((tool) => tool.route);
