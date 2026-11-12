import { getActiveClientName } from "../app/activeClient";
import { getPathForRoute } from "../app/routes";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import BrandHealth from "../components/clipping/BrandHealth";
import "../styles/studio.css";

/** Saúde da Marca: uma aba só, com o índice, menções, sentimento, canais e assuntos desta marca. */
function openAlerts() {
  window.history.pushState({}, document.title, `${getPathForRoute("clipping")}?aba=alertas`);
  window.dispatchEvent(new PopStateEvent("popstate"));  // o App troca de tela pelo popstate
}

export default function BrandHealthPage({ canManage = false }: { canManage?: boolean }) {
  return <Shell title="Saúde da Marca" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={getActiveClientName() || "Empresa"} title="Saúde da Marca" />
    <BrandHealth canManage={canManage} onOpenAlerts={openAlerts} />
  </div></Shell>;
}
