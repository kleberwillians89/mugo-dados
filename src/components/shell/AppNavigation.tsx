import { useCallback, useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { Menu, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
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

// Operação: o cliente também vê, cada tela com a parte que é dele (o backend filtra).
// Social Media (antes Redação): equipe Mugô sempre; cliente só quando a Mugô libera o módulo.
const OPERATION_ITEMS: NavItem[] = [
  // Mugoverso IA: pergunte qualquer coisa sobre o mundo do cliente (lê todo o contexto dele).
  { route: "mugo_ia", label: "Mugoverso IA" },
  { route: "central", label: "Central da Marca" },
  { route: "briefing", label: "Briefing" },
  { route: "planning", label: "Planejamento" },
  { route: "production", label: "Evento" },
  { route: "tasks", label: "Tarefas" },
  { route: "campaigns", label: "Social Media" },
  { route: "redacao", label: "Redação" },
  { route: "creators", label: "Criadores" },
  { route: "library", label: "Biblioteca" },
];

const INTELLIGENCE_ITEMS: NavItem[] = [
  { route: "meta", label: "Meta" },
  { route: "google", label: "Google" },
  { route: "ecommerce", label: "Ecommerce" },
  // CRM: Origem das vendas e Clientes moram aqui, como abas (ClientsSalesTabs).
  { route: "origins", label: "CRM", also: ["customers"] },
  { route: "whatsapp", label: "WhatsApp" },
  { route: "media", label: "Mídia On" },
  { route: "engagement", label: "Comentários" },
  { route: "clipping", label: "Clipping" },
  { route: "radar", label: "Radar Cultural" },
  { route: "benchmark", label: "Benchmarking" },
  { route: "social_report", label: "Relatório" },
];
const TEAM_ONLY_ROUTES = new Set<AppRoute>(["campaigns", "redacao", "planning", "production"]);

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
  if (showIntegrations) adminItems.push({ route: "integrations", label: "Integrações" });
  if ((platformAdmin || agencyAdmin || teamHere) || (canView ? canView("users") : false)) adminItems.push({ route: "users", label: "Usuários" });
  if (platformAdmin || agencyAdmin) adminItems.push({ route: "companies", label: "Empresas" });
  if (platformAdmin || agencyAdmin) adminItems.push({ route: "ai_usage", label: "Consumo de IA" });
  // Configurações → WhatsApp → Automações: central da equipe Mugô.
  if (platformAdmin || agencyAdmin) adminItems.push({ route: "automations", label: "Automações" });
  // A posição é administrativa, mas a visibilidade continua obedecendo apenas
  // à permissão preexistente do módulo, sem exigir um papel administrativo.
  if (!canView || canView("brand_ai")) adminItems.push({ route: "brand_ai", label: "IA da marca" });
  if (adminItems.length && (!canView || canView("central"))) adminItems.push({ route: "central", label: "Central da Marca" });

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
    const target = routesOf(item).find((candidate) => !canView || canView(candidate)) || item.route;
    return (
      <li key={item.route}>
        <a
          className="appNavLink"
          href={getPathForRoute(target)}
          aria-current={routesOf(item).includes(route) ? "page" : undefined}
          onClick={(event) => go(event, target)}
        >
          {item.label}
        </a>
      </li>
    );
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
          <a className="appProduct" href={getPathForRoute("meta")} onClick={(event) => go(event, "meta")}>
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
          <div className="appNavGroup">
            <p className="appNavGroupLabel" id="app-nav-agency">Operação</p>
            <ul className="appNavList" aria-labelledby="app-nav-agency">
              {OPERATION_ITEMS.filter((item) => platformAdmin || agencyAdmin || teamHere || (canView ? true : !TEAM_ONLY_ROUTES.has(item.route))).filter(visible).map(renderItem)}
            </ul>
          </div>
          <div className="appNavGroup">
            <p className="appNavGroupLabel" id="app-nav-intelligence">Inteligência</p>
            <ul className="appNavList" aria-labelledby="app-nav-intelligence">
              {INTELLIGENCE_ITEMS.filter(visible).map(renderItem)}
            </ul>
          </div>
          {adminItems.length ? (
            <div className="appNavGroup">
              <p className="appNavGroupLabel" id="app-nav-admin">Administração</p>
              <ul className="appNavList" aria-labelledby="app-nav-admin">{adminItems.map(renderItem)}</ul>
            </div>
          ) : null}
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
