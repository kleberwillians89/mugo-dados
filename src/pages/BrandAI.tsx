import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import BrandKnowledge from "../components/studio/BrandKnowledge";
import "../styles/studio.css";

/** IA da marca: o que a IA sabe sobre a empresa e onde ensinar com documentos. Todo mundo vê; admin e equipe ensinam. */
export default function BrandAI({ canManage }: { canManage: boolean }) {
  const clientId = getActiveClientId();
  return <Shell title="IA da marca" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={getActiveClientName() || "empresa"} title="IA da marca" />
    <p className="libHint">{canManage
      ? "Envie apresentações, cardápios, tabelas de produtos e briefings. A IA lê, guarda o que importa e o arquivo é descartado. Ela usa isso nas pautas, nas ideias de post e nas respostas de comentários."
      : "O que a IA da Mugô sabe sobre a sua empresa. Ela usa isso para criar as pautas e responder comentários."}</p>
    <BrandKnowledge key={clientId} canManage={canManage} />
  </div></Shell>;
}
