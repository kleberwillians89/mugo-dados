import { getPathForRoute, navigateToAppRoute, type AppRoute } from "../../app/routes";

type Tab = "customers" | "origins" | "customer_value";
const TABS: { route: Tab; label: string }[] = [
  { route: "origins", label: "Origem das vendas" },
  { route: "customers", label: "Clientes" },
  { route: "customer_value", label: "LTV e CAC" },
];

/**
 * CRM: as duas telas moram num item só do menu e trocam por estas abas.
 * Cada aba tem o próprio endereço (/crm, /crm/clientes; os antigos /origem-das-vendas e /clientes seguem
 * funcionando) e a própria permissão.
 */
export default function ClientsSalesTabs({ current, canView }: { current: Tab; canView?: (route: AppRoute) => boolean }) {
  const tabs = TABS.filter((tab) => !canView || canView(tab.route));
  if (tabs.length < 2) return null;
  return (
    <nav className="clientsSalesTabs" aria-label="CRM">
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
