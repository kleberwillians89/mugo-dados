import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import Redacao from "../components/studio/Redacao";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { getPathForRoute } from "../app/routes";
import "../styles/studio.css";

/**
 * Redação (trazida da iAgência): página própria no menu, fora de Social Media.
 * Editor de texto estilo Word por marca, com a IA da marca. Mesmo módulo de permissão do
 * Social Media (social_media.*): equipe Mugô sempre; cliente só quando a Mugô libera.
 */
export default function RedacaoPage({ canManage = true }: { canManage?: boolean }) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "empresa";
  const openCalendar = () => {
    window.history.pushState({}, document.title, `${getPathForRoute("campaigns")}?aba=calendario`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  };
  return <Shell title="Redação" variant="editorial" themeClass="redacaoShell"><div className="ds-page studioPage redacaoPage">
    <PageHeader company={clientName} title="Redação" />
    <Redacao key={`redacao:${clientId}`} canManage={canManage} onOpenCalendar={openCalendar} />
  </div></Shell>;
}
