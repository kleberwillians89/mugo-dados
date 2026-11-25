import type { MouseEvent as ReactMouseEvent } from "react";
import { ArrowRight, CheckCircle2, HeartHandshake, Megaphone, PenLine, Share2, ShoppingCart, Target } from "lucide-react";
import WorkKanban from "../components/shell/WorkKanban";
import MyTasksButton from "../components/shell/MyTasksButton";
import { getActiveClientName } from "../app/activeClient";
import { getPathForRoute, type AppRoute } from "../app/routes";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import "../styles/process-entry.css";

type Props = { canView: (route: AppRoute) => boolean; onOpen: (route: AppRoute) => void };

const ACTIONS: { title: string; description: string; route: AppRoute; icon: typeof Target }[] = [
  { title: "Planejar", description: "Definir objetivos e ações.", route: "process_planning", icon: Target },
  { title: "Criar conteúdo", description: "Produzir e publicar.", route: "process_content", icon: PenLine },
  { title: "Lançar campanha", description: "Ativar canais e acompanhar.", route: "process_campaign", icon: Megaphone },
  { title: "Relacionamento", description: "E-mail, WhatsApp, captação e comentários.", route: "process_relationship", icon: HeartHandshake },
  { title: "CRM", description: "Vendas, clientes, relatórios e saúde da marca.", route: "process_analysis", icon: ShoppingCart },
  { title: "Redes sociais", description: "Desempenho de cada rede.", route: "process_social", icon: Share2 },
];

export default function Home({ canView, onOpen }: Props) {
  const actions = ACTIONS.filter((action) => canView(action.route));
  // Atalhos de aprovação ao lado do Kanban, conforme a permissão de cada pessoa.
  const approvals = [
    canView("internal_approval") ? { label: "Aprovação Interna", route: "internal_approval" as AppRoute } : null,
    canView("final_approval") ? { label: "Aprovação Final", route: "final_approval" as AppRoute } : null,
  ].filter((item): item is { label: string; route: AppRoute } => Boolean(item));

  function open(event: ReactMouseEvent<HTMLAnchorElement>, route: AppRoute) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onOpen(route);
  }

  return <Shell title="Início" variant="editorial"><div className="ds-page processHomePage">
    <PageHeader company={getActiveClientName() || "empresa"} title="O que vamos fazer hoje?" back={false} />
    <div className="processHomeWork">
    <MyTasksButton onOpen={() => onOpen("my_tasks")} />
    <WorkKanban place="home" />
    {approvals.length ? <nav className="processApprovals" aria-label="Aprovações">
      <CheckCircle2 size={17} aria-hidden="true" />
      {approvals.map((item) => <a key={item.route} href={getPathForRoute(item.route)} onClick={(event) => open(event, item.route)}>{item.label}<ArrowRight size={15} aria-hidden="true" /></a>)}
    </nav> : null}
    </div>
    <div className="processHomeGrid" aria-label="Processos do Mugoverso">
      {actions.map((action, index) => {
        const Icon = action.icon;
        return <a key={action.route} className="processHomeCard" data-accent={index % 4} href={getPathForRoute(action.route)} onClick={(event) => open(event, action.route)}>
          <Icon size={22} aria-hidden="true" />
          <span><strong>{action.title}</strong><small>{action.description}</small></span>
          <ArrowRight size={18} aria-hidden="true" />
        </a>;
      })}
    </div>
  </div></Shell>;
}
