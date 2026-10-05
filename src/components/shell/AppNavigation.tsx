import { useCallback, useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { Menu, X } from "lucide-react";
import type { ClientMembership } from "../../app/api";
import { MUGO_LOGO_ASSETS } from "../MugoLogo";
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
  canManageIntegrations?: boolean;
  onOpen: (route: AppRoute) => void;
  /** Memberships já resolvidas pelo App — a única fonte da lista de empresas. */
  clients?: ClientMembership[];
  activeClientId?: string;
  onClientChange?: (clientId: string) => void;
  onLogout: () => void | Promise<void>;
  user?: NavigationUser | null;
};

type NavItem = { route: AppRoute; label: string };

// Produto: o que a empresa analisa. A ordem segue a leitura comercial
// (resultado de vendas → mídia → site → leitura assistida).
const PRODUCT_ITEMS: NavItem[] = [
  { route: "ecommerce", label: "Ecommerce" },
  { route: "customers", label: "Clientes" },
  { route: "goals", label: "Metas" },
  { route: "meta", label: "Meta" },
  { route: "google", label: "Google" },
  { route: "intelligence", label: "Inteligência" },
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
  canManageIntegrations,
  onOpen,
  clients,
  activeClientId,
  onClientChange,
  onLogout,
  user,
}: Props) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const sidebarRef = useRef<HTMLElement | null>(null);

  // Perfil somente-leitura nunca vê a configuração de integrações (OAuth,
  // reconexões, detalhe técnico) — nem no menu, nem por navegação direta
  // (guarda em resolveAuthenticatedView). client_admin/owner gerenciam as
  // integrações da própria empresa; Empresas é só plataforma/agência.
  const showIntegrations = canManageIntegrations ?? (platformAdmin || agencyAdmin);
  const adminItems: NavItem[] = [];
  if (showIntegrations) adminItems.push({ route: "integrations", label: "Integrações" });
  if (platformAdmin || agencyAdmin) adminItems.push({ route: "companies", label: "Empresas" });

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

  function go(event: ReactMouseEvent<HTMLAnchorElement>, target: AppRoute) {
    // Links reais (abrem em nova aba com Ctrl/Cmd); clique simples navega no app.
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    setDrawerOpen(false);
    onOpen(target);
  }

  const renderItem = (item: NavItem) => (
    <li key={item.route}>
      <a
        className="appNavLink"
        href={getPathForRoute(item.route)}
        aria-current={route === item.route ? "page" : undefined}
        onClick={(event) => go(event, item.route)}
      >
        {item.label}
      </a>
    </li>
  );

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
          <span className="appTopbarProductName">Mugô Dados</span>
        )}
      </header>

      <aside
        ref={sidebarRef}
        id="app-sidebar"
        className={`appSidebar${drawerOpen ? " is-open" : ""}`}
        aria-label="Mugô Dados"
      >
        <div className="appSidebarHead">
          <a className="appProduct" href={getPathForRoute("meta")} onClick={(event) => go(event, "meta")}>
            <span className="appProductMark" aria-hidden="true">
              <img src={MUGO_LOGO_ASSETS.symbol} alt="" />
            </span>
            <span className="appProductName">Mugô Dados</span>
          </a>
          <button type="button" className="appSidebarClose" aria-label="Fechar navegação" onClick={() => closeDrawer(true)}>
            <X size={20} aria-hidden="true" />
          </button>
        </div>

        {clients && activeClientId && onClientChange ? (
          <div className="appSidebarCompany">
            <ClientSwitcher clients={clients} activeClientId={activeClientId} onChange={onClientChange} />
          </div>
        ) : null}

        <nav className="appSidebarNav" aria-label="Navegação principal">
          <ul className="appNavList">{PRODUCT_ITEMS.map(renderItem)}</ul>
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
      {drawerOpen ? <div className="appSidebarBackdrop" aria-hidden="true" onClick={() => closeDrawer(true)} /> : null}
    </>
  );
}
