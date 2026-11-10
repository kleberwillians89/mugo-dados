import { getPathForRoute, navigateToAppRoute, type AppRoute } from "../../app/routes";

type Tab = "customers" | "origins";
const TABS: { route: Tab; label: string }[] = [
  { route: "customers", label: "Clientes" },
  { route: "origins", label: "Origem das vendas" },
];

/**
 * "Clientes e vendas": as duas telas moram num item só do menu e trocam por estas abas.
 * Cada aba continua com o próprio endereço (/clientes, /origem-das-vendas) e a própria permissão.
 */
export default function ClientsSalesTabs({ current, canView }: { current: Tab; canView?: (route: AppRoute) => boolean }) {
  const tabs = TABS.filter((tab) => !canView || canView(tab.route));
  if (tabs.length < 2) return null;
  return (
    <nav className="clientsSalesTabs" aria-label="Clientes e vendas">
      {tabs.map((tab) => (
        <a key={tab.route} href={getPathForRoute(tab.route)} aria-current={tab.route === current ? "page" : undefined}
          className={tab.route === current ? "is-active" : ""}
          onClick={(event) => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
            event.preventDefault();
            if (tab.route === current) return;
            navigateToAppRoute(tab.route);
            window.dispatchEvent(new PopStateEvent("popstate"));
          }}>
          {tab.label}
        </a>
      ))}
    </nav>
  );
}
