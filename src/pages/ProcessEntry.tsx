import type { MouseEvent as ReactMouseEvent } from "react";
import { ArrowRight, BarChart3, CalendarDays, FileText, HeartPulse, Mail, Megaphone, MessageCircle, MessageSquare, PenLine, Search, ShoppingCart, Sparkles, Target, UserPlus, Users } from "lucide-react";
import { getActiveClientName } from "../app/activeClient";
import { getPathForRoute, type AppRoute } from "../app/routes";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import { requestGoalsSection, requestNewProject } from "../app/newProjectRequest";
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
      { label: "E-mail Marketing", description: "Crie e envie campanhas de e-mail para a base.", route: "email_marketing", icon: Mail },
      { label: "Captação", description: "Capte e organize os contatos da operação.", route: "capture", icon: UserPlus },
    ],
  },
  campaign: {
    title: "Lançar campanha",
    lead: "Campanhas, criativos, briefings, Meta Ads, Google Ads, Resumo Executivo e Análise Técnica ficam todos na Mídia On.",
    // Lançar campanha abre a Mídia On direto (App.tsx). Esta lista só aparece para quem não pode abrir a Mídia On.
    // Aprovação Interna/Final seguem na Home ("Precisa da sua atenção") e no menu; o acompanhamento, em Meu trabalho.
    tools: [
      { label: "Mídia On", description: "Campanhas, criativos, verba e resultados de mídia.", route: "media", icon: Target },
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

// E-mail Marketing e Captação têm o acesso principal em Criar conteúdo; os resultados deles seguem nas próprias telas.
// O WhatsApp aparece aqui pelos resultados e em Meu trabalho pela operação (a mesma ferramenta).
const RELATIONSHIP_TOOLS: Tool[] = [
  { label: "WhatsApp", description: "Resultados das conversas, atendimentos e disparos.", route: "whatsapp", icon: MessageCircle },
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

  if (kind === "planning") {
    const planningTool = tools.find((tool) => tool.route === "planning");
    const quickStarts = tools.filter((tool) => ["planning", "campaigns", "goals"].includes(tool.route));

    return <Shell title={process.title} variant="editorial"><div className="ds-page processEntryPage planningEntryPage">
      <PageHeader company={getActiveClientName() || "empresa"} title={process.title} />
      <p className="processEntryLead">{process.lead}</p>

      {planningTool ? <section className="planningCurrent" aria-labelledby="planning-current-title">
        <div className="planningSectionEyebrow">Seu espaço de estratégia</div>
        <div className="planningCurrentContent">
          <div>
            <h2 id="planning-current-title">Meu planejamento</h2>
            <p>Continue no ambiente de planejamento da empresa selecionada, com os registros e períodos já salvos.</p>
          </div>
          <a className="planningPrimaryAction" href={getPathForRoute(planningTool.route)} onClick={(event) => open(event, planningTool.route)}>
            Continuar planejamento <ArrowRight size={18} aria-hidden="true" />
          </a>
        </div>
      </section> : null}

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
        return <a key={`${tool.label}:${tool.route}`} className="processToolCard" data-accent={index % 6} href={getPathForRoute(tool.route)} onClick={(event) => open(event, tool.route)}>
          <span className="processToolIcon"><Icon size={20} aria-hidden="true" /></span>
          <span><strong>{tool.label}</strong><small>{tool.description}</small></span>
          <ArrowRight size={18} aria-hidden="true" className="processToolArrow" />
        </a>;
      })}
    </div> : null}
    {relationshipTools.length ? <section className="processToolSection" aria-labelledby="process-relationship-title">
      <h2 id="process-relationship-title">Relacionamento</h2>
      <div className="processToolGrid">
        {relationshipTools.map((tool, index) => {
          const Icon = tool.icon;
          return <a key={`${tool.label}:${tool.route}`} className="processToolCard" data-accent={(index + 3) % 6} href={getPathForRoute(tool.route)} onClick={(event) => open(event, tool.route)}>
            <span className="processToolIcon"><Icon size={20} aria-hidden="true" /></span>
            <span><strong>{tool.label}</strong><small>{tool.description}</small></span>
            <ArrowRight size={18} aria-hidden="true" className="processToolArrow" />
          </a>;
        })}
      </div>
    </section> : null}
  </div></Shell>;
}
