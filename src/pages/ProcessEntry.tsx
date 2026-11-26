import type { MouseEvent as ReactMouseEvent } from "react";
import { ArrowRight, BarChart3, CalendarDays, FileText, HeartPulse, Instagram, Linkedin, Mail, Megaphone, MessageCircle, MessageSquare, Music2, Newspaper, PenLine, Pin, Search, ShoppingCart, Sparkles, Target, UserPlus, Users } from "lucide-react";
import { getActiveClientName } from "../app/activeClient";
import { getPathForRoute, type AppRoute } from "../app/routes";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import { requestGoalsSection, requestNewProject, requestWhatsAppArea } from "../app/newProjectRequest";
import "../styles/process-entry.css";

export type ProcessKind = "planning" | "content" | "campaign" | "relationship" | "analysis" | "social";

type Tool = {
  label: string;
  description: string;
  route: AppRoute;
  icon: typeof Sparkles;
  permission?: string;
  /** Abre direto uma área do WhatsApp (Disparos em massa, Modelos). */
  whatsappArea?: "bulk" | "models";
};

// Cada ferramenta mora em um card só. A Mugô IA fica no menu lateral, abaixo de Meu trabalho.
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
      { label: "Briefing", description: "Organize a demanda antes da produção.", route: "briefing", icon: FileText },
      { label: "Social Media", description: "Planeje, aprove e publique conteúdo.", route: "campaigns", icon: Megaphone, permission: "social_media.view" },
      { label: "Redação", description: "Produza e refine textos no editor profissional.", route: "redacao", icon: PenLine },
      { label: "Criadores", description: "Consulte e organize criadores para as ações.", route: "creators", icon: Users },
      { label: "Eventos", description: "Planeje produções e eventos da marca.", route: "production", icon: CalendarDays },
      { label: "Clipping", description: "Notícias, alertas e menções da marca para pautar conteúdo.", route: "clipping", icon: Newspaper },
    ],
  },
  campaign: {
    title: "Lançar campanha",
    lead: "Crie campanhas e acompanhe a operação de mídia paga no Mídia On.",
    tools: [
      { label: "Mídia On", description: "Campanhas, criativos, verba e leitura da IA.", route: "media", icon: Target },
    ],
  },
  relationship: {
    title: "Relacionamento",
    lead: "Fale com a base: e-mail, WhatsApp, captação e comentários.",
    tools: [
      { label: "E-mail Marketing", description: "Crie e envie campanhas de e-mail para a base.", route: "email_marketing", icon: Mail },
      { label: "Captação", description: "Capte e organize os contatos da operação.", route: "capture", icon: UserPlus },
      { label: "Comentários", description: "Responda comentários e interações das redes.", route: "engagement", icon: MessageSquare },
      { label: "Disparos em massa", description: "Envie campanhas pelo WhatsApp para listas da base.", route: "whatsapp", icon: MessageCircle, whatsappArea: "bulk" },
      { label: "Modelos de campanha", description: "Consulte e envie modelos de mensagem para aprovação.", route: "whatsapp", icon: MessageCircle, whatsappArea: "models" },
      { label: "WhatsApp", description: "Conversas, atendimentos e resultados.", route: "whatsapp", icon: MessageCircle },
    ],
  },
  analysis: {
    title: "CRM",
    lead: "Vendas, clientes e saúde da marca: o resultado do negócio.",
    tools: [
      { label: "Vendas", description: "Entenda a origem das vendas registradas.", route: "origins", icon: ShoppingCart },
      { label: "E-commerce", description: "Acompanhe loja, pedidos e produtos.", route: "ecommerce", icon: ShoppingCart },
      { label: "Clientes", description: "Consulte clientes, recorrência e relacionamento.", route: "customers", icon: Users },
      { label: "Relatórios", description: "Abra os relatórios consolidados disponíveis.", route: "social_report", icon: FileText },
      { label: "Saúde da Marca", description: "Acompanhe os indicadores de presença e consistência.", route: "brand_health", icon: HeartPulse },
      { label: "O que a IA fez", description: "Propostas e ações da IA na base de clientes.", route: "ai_actions", icon: Sparkles },
    ],
  },
  social: {
    title: "Redes sociais",
    lead: "Desempenho orgânico e pago por rede, conforme os dados disponíveis.",
    tools: [
      { label: "Instagram e Facebook", description: "Desempenho orgânico do Instagram e resultados de Meta Ads.", route: "meta", icon: Instagram },
      { label: "TikTok", description: "Vídeos, visualizações e crescimento.", route: "tiktok", icon: Music2 },
      { label: "Pinterest", description: "Pins, impressões e salvamentos.", route: "pinterest", icon: Pin },
      { label: "LinkedIn", description: "Página da empresa, seguidores e engajamento.", route: "linkedin", icon: Linkedin },
    ],
  },
};

type Props = {
  kind: ProcessKind;
  canView: (route: AppRoute) => boolean;
  canUse: (permission: string) => boolean;
  onOpen: (route: AppRoute) => void;
};

export default function ProcessEntry({ kind, canView, canUse, onOpen }: Props) {
  const process = PROCESSES[kind];
  const tools = process.tools.filter((tool) => canView(tool.route) && (!tool.permission || canUse(tool.permission)));

  function open(event: ReactMouseEvent<HTMLAnchorElement>, route: AppRoute) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onOpen(route);
  }

  if (kind === "planning") {
    const quickStarts = tools.filter((tool) => ["planning", "campaigns", "goals"].includes(tool.route));

    return <Shell title={process.title} variant="editorial"><div className="ds-page processEntryPage planningEntryPage">
      <PageHeader company={getActiveClientName() || "empresa"} title={process.title} />
      <p className="processEntryLead">{process.lead}</p>

      {quickStarts.length ? <section className="planningStart" aria-labelledby="planning-start-title">
        <div className="planningSectionHeading">
          <div><span>Começar</span><h2 id="planning-start-title">Começar um trabalho</h2></div>
          <p>Escolha o ponto de partida mais adequado. Não há uma ordem obrigatória.</p>
        </div>
        <div className="planningStartGrid">
          {quickStarts.map((tool) => {
            const Icon = tool.icon;
            const action = tool.route === "planning" ? "Criar planejamento" : tool.route === "campaigns" ? "Criar Matriz Tática" : "Definir metas";
            // Criar planejamento cai direto no formulário; Definir metas abre o Planejamento na seção Metas
            // (os mesmos registros de /metas). Sem acesso ao Planejamento, Definir metas abre a página Metas.
            const isNew = tool.route === "planning";
            const goalsInPlanning = tool.route === "goals" && canView("planning");
            const target: AppRoute = goalsInPlanning ? "planning" : tool.route;
            const href = `${getPathForRoute(target)}${isNew ? "?novo=1" : goalsInPlanning ? "#metas" : ""}`;
            return <a key={`start:${tool.route}`} className="planningStartCard" href={href}
              onClick={(event) => {
                const plain = event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
                if (plain && isNew) requestNewProject("planejamento");
                if (plain && goalsInPlanning) requestGoalsSection();
                open(event, target);
              }}>
              <span className="planningStartIcon"><Icon size={21} aria-hidden="true" /></span>
              <span><strong>{action}</strong><small>{tool.description}</small></span>
              <ArrowRight size={18} aria-hidden="true" />
            </a>;
          })}
        </div>
      </section> : null}

      {tools.length ? <section className="planningExplore" aria-labelledby="planning-explore-title">
        <div className="planningSectionHeading">
          <div><span>Ferramentas</span><h2 id="planning-explore-title">Explorar ferramentas</h2></div>
          <p>Acesse diretamente cada recurso disponível para o seu perfil.</p>
        </div>
        <div className="planningToolGrid" aria-label="Ferramentas de Planejar">
          {tools.map((tool, index) => {
            const Icon = tool.icon;
            return <a key={`${tool.label}:${tool.route}`} className="planningToolCard" data-accent={index % 6} href={getPathForRoute(tool.route)} onClick={(event) => open(event, tool.route)}>
              <span className="planningToolIcon"><Icon size={21} aria-hidden="true" /></span>
              <span><strong>{tool.label}</strong><small>{tool.description}</small></span>
              <ArrowRight size={18} aria-hidden="true" className="planningToolArrow" />
            </a>;
          })}
        </div>
      </section> : null}
    </div></Shell>;
  }

  return <Shell title={process.title} variant="editorial"><div className="ds-page processEntryPage">
    <PageHeader company={getActiveClientName() || "empresa"} title={process.title} />
    <p className="processEntryLead">{process.lead}</p>
    {tools.length ? <div className="processToolGrid" aria-label={`Ferramentas de ${process.title}`}>
      {tools.map((tool, index) => {
        const Icon = tool.icon;
        const href = `${getPathForRoute(tool.route)}${tool.whatsappArea ? `?area=${tool.whatsappArea}` : ""}`;
        return <a key={`${tool.label}:${tool.route}`} className="processToolCard" data-accent={index % 6} href={href} onClick={(event) => {
          if (tool.whatsappArea && event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) requestWhatsAppArea(tool.whatsappArea);
          open(event, tool.route);
        }}>
          <span className="processToolIcon"><Icon size={20} aria-hidden="true" /></span>
          <span><strong>{tool.label}</strong><small>{tool.description}</small></span>
          <ArrowRight size={18} aria-hidden="true" className="processToolArrow" />
        </a>;
      })}
    </div> : null}
  </div></Shell>;
}
