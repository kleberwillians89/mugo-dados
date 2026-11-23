import type { MouseEvent as ReactMouseEvent } from "react";
import { ArrowRight, BarChart3, CheckCircle2, Megaphone, PenLine, Target } from "lucide-react";
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
  { title: "Analisar resultados", description: "Entender o que funcionou.", route: "process_analysis", icon: BarChart3 },
];

const COMPLEMENTARY: { label: string; route: AppRoute }[] = [
  { label: "Tira-dúvidas", route: "mugo_ia" },
  { label: "O que a IA fez", route: "ai_actions" },
];

export default function Home({ canView, onOpen }: Props) {
  const actions = ACTIONS.filter((action) => canView(action.route));
  const attention = [
    canView("tasks") ? { label: "Abrir meu trabalho", route: "tasks" as AppRoute } : null,
    canView("calendar") ? { label: "Ver aprovações", route: "calendar" as AppRoute } : null,
  ].filter((item): item is { label: string; route: AppRoute } => Boolean(item));
  const complementary = COMPLEMENTARY.filter((item) => canView(item.route));

  function open(event: ReactMouseEvent<HTMLAnchorElement>, route: AppRoute) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onOpen(route);
  }

  return <Shell title="Início" variant="editorial"><div className="ds-page processHomePage">
    <PageHeader company={getActiveClientName() || "empresa"} title="O que vamos fazer hoje?" />
    <div className="processHomeGrid" aria-label="Processos do Mugoverso">
      {actions.map((action) => {
        const Icon = action.icon;
        return <a key={action.route} className="processHomeCard" href={getPathForRoute(action.route)} onClick={(event) => open(event, action.route)}>
          <Icon size={22} aria-hidden="true" />
          <span><strong>{action.title}</strong><small>{action.description}</small></span>
          <ArrowRight size={18} aria-hidden="true" />
        </a>;
      })}
    </div>
    {attention.length ? <section className="processAttention" aria-labelledby="process-attention-title">
      <div><CheckCircle2 size={19} aria-hidden="true" /><span><strong id="process-attention-title">Precisa da sua atenção</strong><small>Acesse as pendências disponíveis para o seu perfil.</small></span></div>
      <nav aria-label="Atalhos de atenção">{attention.map((item) => <a key={item.route} href={getPathForRoute(item.route)} onClick={(event) => open(event, item.route)}>{item.label}<ArrowRight size={15} aria-hidden="true" /></a>)}</nav>
    </section> : null}
    {complementary.length ? <nav className="processComplementary" aria-label="Ferramentas complementares">
      <strong>Ferramentas complementares</strong>
      <span>{complementary.map((item) => <a key={item.route} href={getPathForRoute(item.route)} onClick={(event) => open(event, item.route)}>{item.label}</a>)}</span>
    </nav> : null}
  </div></Shell>;
}
