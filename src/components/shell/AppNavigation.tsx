import { useCallback, useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import {
  Activity, BrainCircuit, Building2, ChevronDown, Circle, ClipboardList, Cpu, CreditCard, Home, LayoutDashboard,
  Library, ListChecks, Menu, PanelLeftClose, PanelLeftOpen, Plug, Settings, UserCog, Workflow, X, type LucideIcon,
} from "lucide-react";
import type { ClientMembership } from "../../app/api";
import { MUGO_LOGO_ASSETS, PRODUCT_WORDMARK } from "../MugoLogo";
import { ACCOUNT_ROLE_LABELS } from "../../app/roles";
import { getPathForRoute, type AppRoute } from "../../app/routes";
import ClientBrand from "../ClientBrand";
import ClientSwitcher from "../ClientSwitcher";
import UserMenu from "./UserMenu";

export type NavigationUser = {
  name: string;
  email?: string | null;
};

type Props = {
  route: AppRoute;
  platformAdmin: boolean;
  agencyAdmin: boolean;
  /** Equipe Mugô nesta empresa (inclui gestora da conta, que não vê Empresas/Automações). */
  teamHere?: boolean;
  canManageIntegrations?: boolean;
  onOpen: (route: AppRoute) => void;
  /** Memberships já resolvidas pelo App — a única fonte da lista de empresas. */
  clients?: ClientMembership[];
  activeClientId?: string;
  onClientChange?: (clientId: string) => void;
  onLogout: () => void | Promise<void>;
  user?: NavigationUser | null;
  /** Permissão de ver cada tela (Usuários e acessos por módulo). Sem ela, tudo aparece como antes. */
  canView?: (route: AppRoute) => boolean;
};

/** `also`: telas que vivem dentro deste item (abas). O item fica ativo nelas e abre a primeira permitida. */
type NavItem = { route: AppRoute; label: string; also?: AppRoute[] };
const COLLAPSE_KEY = "mugo.sidebarCollapsed";

// Um ícone por página: com o menu recolhido sobra só o ícone (o nome aparece ao passar o mouse).
const ROUTE_ICONS: Partial<Record<AppRoute, LucideIcon>> = {
  home: Home, central: LayoutDashboard, tasks: ListChecks, library: Library,
  integrations: Plug, users: UserCog, companies: Building2, integration_health: Activity, plan: ClipboardList,
  plans_admin: CreditCard, ai_usage: Cpu, automations: Workflow, brand_ai: BrainCircuit,
};

// A nova navegação orienta o acesso sem substituir nenhuma ferramenta. Os quatro
// processos vivem na Home; aqui ficam somente os pontos transversais aprovados.
const PRIMARY_ITEMS: NavItem[] = [
  { route: "home", label: "Início" },
  { route: "central", label: "Dashboard" },
  { route: "tasks", label: "Meu trabalho" },
  { route: "library", label: "Biblioteca" },
];

/**
 * Estrutura global: a sidebar diz "onde posso ir" (produto, empresa, conta);
 * cada página diz "onde estou". No mobile a mesma sidebar vira gaveta.
 * Regras de visibilidade idênticas às anteriores — nenhuma permissão nova.
 */
export default function AppNavigation({
  route,
  platformAdmin,
  agencyAdmin,
  teamHere,
  canManageIntegrations,
  onOpen,
  clients,
  activeClientId,
  onClientChange,
  onLogout,
  user,
  canView,
}: Props) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  // Desktop: menu recolhido (lembrado neste navegador). No celular o menu já é gaveta.
  const [collapsed, setCollapsed] = useState(() => {
    try { return window.localStorage.getItem(COLLAPSE_KEY) === "1"; } catch { return false; }
  });
  useEffect(() => {
    document.documentElement.classList.toggle("is-sidebar-collapsed", collapsed);
    try { window.localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0"); } catch { /* storage bloqueado */ }
    return () => document.documentElement.classList.remove("is-sidebar-collapsed");
  }, [collapsed]);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const sidebarRef = useRef<HTMLElement | null>(null);

  // Perfil somente-leitura nunca vê a configuração de integrações (OAuth,
  // reconexões, detalhe técnico) — nem no menu, nem por navegação direta
  // (guarda em resolveAuthenticatedView). client_admin/owner gerenciam as
  // integrações da própria empresa; Empresas é só plataforma/agência.
  const showIntegrations = canManageIntegrations ?? (platformAdmin || agencyAdmin);
  const adminItems: NavItem[] = [];
  // Contexto da Marca: quem vê o módulo da IA da marca consulta; editar continua sendo do admin (o backend valida).
  if (canView ? canView("brand_ai") : true) adminItems.push({ route: "brand_ai", label: "Contexto da Marca" });
  if (showIntegrations) adminItems.push({ route: "integrations", label: "Integrações" });
  if ((platformAdmin || agencyAdmin || teamHere) || (canView ? canView("users") : false)) adminItems.push({ route: "users", label: "Usuários" });
  if (platformAdmin || agencyAdmin) adminItems.push({ route: "companies", label: "Empresas" });
  if (platformAdmin || agencyAdmin) adminItems.push({ route: "integration_health", label: "Saúde das integrações" });
  if (platformAdmin || agencyAdmin) adminItems.push({ route: "plan", label: "Plano e implantação" });
  if (platformAdmin || agencyAdmin) adminItems.push({ route: "plans_admin", label: "Planos e cobrança" });
  if (platformAdmin || agencyAdmin) adminItems.push({ route: "ai_usage", label: "Consumo de IA" });
  // Configurações → WhatsApp → Automações: central da equipe Mugô.
  if (platformAdmin || agencyAdmin) adminItems.push({ route: "automations", label: "Automações" });
  const [openGroups, setOpenGroups] = useState<Set<string>>(() => new Set());

  const activeClient = clients?.find((client) => client.client_id === activeClientId);
  const roleLabel = activeClient?.role ? ACCOUNT_ROLE_LABELS[activeClient.role] || null : null;

  const closeDrawer = useCallback((returnFocus: boolean) => {
    setDrawerOpen(false);
    if (returnFocus) menuButtonRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!drawerOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") closeDrawer(true);
      if (event.key === "Tab") {
        const nodes = [...(sidebarRef.current?.querySelectorAll<HTMLElement>("*") || [])].filter(node => node.tabIndex >= 0 && !node.matches(':disabled') && !node.closest('[hidden], [inert]'));
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (first && last && event.shiftKey && document.activeElement === first) {event.preventDefault(); last.focus();}
        else if (first && last && !event.shiftKey && document.activeElement === last) {event.preventDefault(); first.focus();}
      }
    }
    document.addEventListener("keydown", onKeyDown);
    sidebarRef.current?.querySelector<HTMLElement>("a, button")?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [closeDrawer, drawerOpen]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const desktop = window.matchMedia("(min-width: 1024px)");
    const changed = () => {if (desktop.matches) closeDrawer(false);};
    desktop.addEventListener("change", changed);
    return () => desktop.removeEventListener("change", changed);
  }, [closeDrawer]);

  function go(event: ReactMouseEvent<HTMLAnchorElement>, target: AppRoute) {
    // Links reais (abrem em nova aba com Ctrl/Cmd); clique simples navega no app.
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    setDrawerOpen(false);
    onOpen(target);
  }

  const routesOf = (item: NavItem): AppRoute[] => [item.route, ...(item.also || [])];
  const visible = (item: NavItem) => !canView || routesOf(item).some((target) => canView(target));
  const renderItem = (item: NavItem) => {
    const Icon = ROUTE_ICONS[item.route] || Circle;
    const target = routesOf(item).find((candidate) => !canView || canView(candidate)) || item.route;
    return (
      <li key={item.route}>
        <a
          className="appNavLink"
          href={getPathForRoute(target)}
          title={collapsed ? item.label : undefined}
          aria-current={routesOf(item).includes(route) ? "page" : undefined}
          onClick={(event) => go(event, target)}
        >
          <Icon size={18} aria-hidden="true" className="appNavIcon" />
          <span className="appNavLabel">{item.label}</span>
        </a>
      </li>
    );
  };

  const primaryItems = PRIMARY_ITEMS.filter(visible);

  const renderGroup = (group: { id: string; label: string; icon: LucideIcon; items: NavItem[] }) => {
    const Icon = group.icon;
    const active = group.items.some((item) => routesOf(item).includes(route));
    // Grupo de um item só (Mugoverso IA, Relatório): link direto, sem subitens.
    if (group.items.length === 1 && group.items[0].label === group.label) {
      const item = group.items[0];
      const target = routesOf(item).find((candidate) => !canView || canView(candidate)) || item.route;
      return <div className="appNavGroup" key={group.id} data-group={group.id}>
        <a className="appNavGroupLink" href={getPathForRoute(target)} title={collapsed ? group.label : undefined}
          aria-current={active ? "page" : undefined} onClick={(event) => go(event, target)}>
          <Icon size={18} aria-hidden="true" className="appNavIcon" /><span className="appNavLabel">{group.label}</span>
        </a>
      </div>;
    }
    const open = active || openGroups.has(group.id);
    const first = group.items[0];
    const firstTarget = routesOf(first).find((candidate) => !canView || canView(candidate)) || first.route;
    const toggle = () => setOpenGroups((prev) => { const next = new Set(prev); if (next.has(group.id)) next.delete(group.id); else next.add(group.id); return next; });
    return <div className={`appNavGroup${active ? " is-active" : ""}`} key={group.id} data-group={group.id}>
      <div className="appNavGroupHead">
        <a className="appNavGroupLink" href={getPathForRoute(firstTarget)} title={collapsed ? group.label : undefined}
          data-active={active ? "true" : undefined} onClick={(event) => go(event, firstTarget)}>
          <Icon size={18} aria-hidden="true" className="appNavIcon" /><span className="appNavLabel">{group.label}</span>
        </a>
        <button type="button" className="appNavToggle" aria-expanded={open} aria-controls={`app-nav-${group.id}`}
          aria-label={`${open ? "Fechar" : "Abrir"} ${group.label}`} onClick={toggle}>
          <ChevronDown size={15} aria-hidden="true" />
        </button>
      </div>
      <ul className="appNavList appNavSubList" id={`app-nav-${group.id}`} hidden={!open}>{group.items.map(renderItem)}</ul>
    </div>;
  };

  return (
    <>
      {/* Mobile/tablet: barra mínima — empresa ativa e acesso à navegação. */}
      <header className="appTopbar">
        <button
          ref={menuButtonRef}
          type="button"
          className="appTopbarMenu"
          aria-label="Abrir navegação"
          aria-expanded={drawerOpen}
          aria-controls="app-sidebar"
          onClick={() => setDrawerOpen(true)}
        >
          <Menu size={20} aria-hidden="true" />
        </button>
        {activeClientId ? (
          <span className="appTopbarCompany">
            <ClientBrand inline size="compact" titleAs="span" clientId={activeClientId} clientName={activeClient?.name} />
          </span>
        ) : (
          <span className="appTopbarProductName">{PRODUCT_WORDMARK}</span>
        )}
      </header>

      <aside
        ref={sidebarRef}
        id="app-sidebar"
        className={`appSidebar${drawerOpen ? " is-open" : ""}`}
        aria-label="Mugoverso"
      >
        <div className="appSidebarHead">
          <a className="appProduct" href={getPathForRoute("home")} onClick={(event) => go(event, "home")}>
            <span className="appProductMark" aria-hidden="true">
              <img src={MUGO_LOGO_ASSETS.mark3d} alt="" />
            </span>
            <span className="appProductName">{PRODUCT_WORDMARK}</span>
          </a>
          <button type="button" className="appSidebarClose" aria-label="Fechar navegação" onClick={() => closeDrawer(true)}>
            <X size={20} aria-hidden="true" />
          </button>
          <button type="button" className="appSidebarCollapse" aria-label="Recolher menu" title="Recolher menu"
            aria-controls="app-sidebar" aria-expanded={!collapsed} onClick={() => setCollapsed(true)}>
            <PanelLeftClose size={18} aria-hidden="true" />
          </button>
        </div>

        {clients && activeClientId && onClientChange ? (
          <div className="appSidebarCompany">
            <ClientSwitcher clients={clients} activeClientId={activeClientId} onChange={onClientChange} />
          </div>
        ) : null}

        <nav className="appSidebarNav" aria-label="Navegação principal">
          <ul className="appNavList appNavPrimaryList">{primaryItems.map(renderItem)}</ul>
          {adminItems.length ? renderGroup({ id: "config", label: "Configurações", icon: Settings, items: adminItems }) : null}
        </nav>

        <div className="appSidebarFooter">
          <UserMenu
            name={user?.name || "Conta"}
            email={user?.email}
            roleLabel={roleLabel}
            onLogout={onLogout}
          />
        </div>
      </aside>
      {collapsed ? (
        <button type="button" className="appSidebarExpand" aria-label="Abrir menu" title="Abrir menu"
          aria-controls="app-sidebar" aria-expanded={false} onClick={() => setCollapsed(false)}>
          <PanelLeftOpen size={18} aria-hidden="true" />
        </button>
      ) : null}
      {drawerOpen ? <div className="appSidebarBackdrop" aria-hidden="true" onClick={() => closeDrawer(true)} /> : null}
    </>
  );
}
