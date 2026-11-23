import type { MouseEvent as ReactMouseEvent } from "react";
import { ArrowRight, BarChart3, CalendarDays, FileText, HeartPulse, Mail, Megaphone, MessageCircle, MessageSquare, PenLine, Search, ShoppingCart, Sparkles, Target, UserPlus, Users } from "lucide-react";
import { getActiveClientName } from "../app/activeClient";
import { getPathForRoute, type AppRoute } from "../app/routes";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import "../styles/process-entry.css";

export type ProcessKind = "planning" | "content" | "campaign" | "analysis";

type Tool = {
  label: string;
  description: string;
  route: AppRoute;
  icon: typeof Sparkles;
  permission?: string;
};

const PROCESSES: Record<ProcessKind, { title: string; lead: string; tools: Tool[] }> = {
  planning: {
    title: "Planejar",
    lead: "Defina objetivos, encontre oportunidades e organize o calendário sem uma sequência obrigatória.",
    tools: [
      { label: "Radar", description: "Encontre sinais e oportunidades para explorar.", route: "radar", icon: Search },
      { label: "Benchmarking", description: "Consulte referências e movimentos do mercado.", route: "benchmark", icon: BarChart3 },
      { label: "Planejamento", description: "Estruture objetivos, fases e ações.", route: "planning", icon: Target },
      { label: "Metas", description: "Acompanhe os objetivos cadastrados.", route: "goals", icon: Target },
      { label: "Matriz Tática de Conteúdo", description: "Distribua oportunidades por canal, pilar e período.", route: "campaigns", icon: Sparkles, permission: "social_media.view" },
      { label: "Calendário", description: "Organize datas, publicações e aprovações.", route: "calendar", icon: CalendarDays },
    ],
  },
  content: {
    title: "Criar conteúdo",
    lead: "Acesse diretamente as ferramentas de criação disponíveis para a empresa selecionada.",
    tools: [
      { label: "Social Media", description: "Trabalhe a matriz e as postagens sociais.", route: "campaigns", icon: Megaphone, permission: "social_media.view" },
      { label: "Redação", description: "Produza e refine textos no editor profissional.", route: "redacao", icon: PenLine },
      { label: "Eventos", description: "Planeje produções e eventos da marca.", route: "production", icon: CalendarDays },
      { label: "Briefing", description: "Organize a demanda antes da produção.", route: "briefing", icon: FileText },
      { label: "Criadores", description: "Consulte e organize criadores para as ações.", route: "creators", icon: Users },
    ],
  },
  campaign: {
    title: "Lançar campanha",
    lead: "Prepare, aprove e acompanhe campanhas usando os recursos operacionais já existentes.",
    tools: [
      { label: "Campanhas", description: "Abra a central de campanhas e seus planos.", route: "media", icon: Megaphone },
      { label: "Mídia On", description: "Defina estratégia, verba e cenários de mídia.", route: "media", icon: Target },
      { label: "Criativos", description: "Use os recursos de criativos disponíveis na central de campanhas.", route: "media", icon: Sparkles },
      { label: "Aprovação Interna", description: "Revise as peças que aguardam a decisão da equipe.", route: "internal_approval", icon: FileText },
      { label: "Aprovação Final", description: "Acompanhe as peças enviadas para a decisão final.", route: "final_approval", icon: FileText },
      { label: "Acompanhamento", description: "Acompanhe a execução nas tarefas da empresa.", route: "tasks", icon: BarChart3 },
    ],
  },
  analysis: {
    title: "Analisar resultados",
    lead: "Leia os resultados da marca, dos canais e do negócio nas telas já disponíveis.",
    tools: [
      { label: "Saúde da Marca", description: "Acompanhe os indicadores de presença e consistência.", route: "brand_health", icon: HeartPulse },
      { label: "Meta", description: "Consulte mídia e presença nos canais Meta.", route: "meta", icon: Megaphone },
      { label: "Google", description: "Consulte mídia e dados disponíveis do Google.", route: "google", icon: Search },
      { label: "Redes sociais", description: "Acompanhe os demais canais sociais conectados.", route: "channels", icon: Users },
      { label: "Vendas", description: "Entenda a origem das vendas registradas.", route: "origins", icon: ShoppingCart },
      { label: "E-commerce", description: "Acompanhe loja, pedidos e produtos.", route: "ecommerce", icon: ShoppingCart },
      { label: "CRM", description: "Consulte clientes e relacionamento.", route: "customers", icon: Users },
      { label: "Clipping", description: "Veja notícias, alertas e sinais da marca.", route: "clipping", icon: Search },
      { label: "Relatórios", description: "Abra os relatórios consolidados disponíveis.", route: "social_report", icon: FileText },
    ],
  },
};

const RELATIONSHIP_TOOLS: Tool[] = [
  { label: "WhatsApp", description: "Acompanhe conversas e relacionamento pelo WhatsApp.", route: "whatsapp", icon: MessageCircle },
  { label: "E-mail Marketing", description: "Acesse campanhas e resultados de e-mail.", route: "email_marketing", icon: Mail },
  { label: "Captação", description: "Consulte os contatos captados pela operação.", route: "capture", icon: UserPlus },
  { label: "Comentários", description: "Acompanhe comentários e interações disponíveis.", route: "engagement", icon: MessageSquare },
];

type Props = {
  kind: ProcessKind;
  canView: (route: AppRoute) => boolean;
  canUse: (permission: string) => boolean;
  onOpen: (route: AppRoute) => void;
};

export default function ProcessEntry({ kind, canView, canUse, onOpen }: Props) {
  const process = PROCESSES[kind];
  const tools = process.tools.filter((tool) => canView(tool.route) && (!tool.permission || canUse(tool.permission)));
  const relationshipTools = kind === "analysis" ? RELATIONSHIP_TOOLS.filter((tool) => canView(tool.route)) : [];

  function open(event: ReactMouseEvent<HTMLAnchorElement>, route: AppRoute) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onOpen(route);
  }

  return <Shell title={process.title} variant="editorial"><div className="ds-page processEntryPage">
    <PageHeader company={getActiveClientName() || "empresa"} title={process.title} />
    <p className="processEntryLead">{process.lead}</p>
    {tools.length ? <div className="processToolGrid" aria-label={`Ferramentas de ${process.title}`}>
      {tools.map((tool) => {
        const Icon = tool.icon;
        return <a key={`${tool.label}:${tool.route}`} className="processToolCard" href={getPathForRoute(tool.route)} onClick={(event) => open(event, tool.route)}>
          <span className="processToolIcon"><Icon size={20} aria-hidden="true" /></span>
          <span><strong>{tool.label}</strong><small>{tool.description}</small></span>
          <ArrowRight size={18} aria-hidden="true" className="processToolArrow" />
        </a>;
      })}
    </div> : null}
    {relationshipTools.length ? <section className="processToolSection" aria-labelledby="process-relationship-title">
      <h2 id="process-relationship-title">Relacionamento</h2>
      <div className="processToolGrid">
        {relationshipTools.map((tool) => {
          const Icon = tool.icon;
          return <a key={`${tool.label}:${tool.route}`} className="processToolCard" href={getPathForRoute(tool.route)} onClick={(event) => open(event, tool.route)}>
            <span className="processToolIcon"><Icon size={20} aria-hidden="true" /></span>
            <span><strong>{tool.label}</strong><small>{tool.description}</small></span>
            <ArrowRight size={18} aria-hidden="true" className="processToolArrow" />
          </a>;
        })}
      </div>
    </section> : null}
  </div></Shell>;
}
