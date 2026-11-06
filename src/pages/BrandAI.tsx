import { useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import BrandAgent from "../components/studio/BrandAgent";
import BrandKnowledge from "../components/studio/BrandKnowledge";
import "../styles/studio.css";

/** IA da marca: o que a IA sabe sobre a empresa, onde ensinar com documentos e onde conversar com ela.
 * Todo mundo vê e conversa; admin e equipe ensinam. */
export default function BrandAI({ canManage }: { canManage: boolean }) {
  const clientId = getActiveClientId();
  const company = getActiveClientName() || "empresa";
  const [version, setVersion] = useState(0);
  return <Shell title="IA da marca" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={company} title="IA da marca" />
    <p className="libHint">{canManage
      ? "Envie apresentações, cardápios, tabelas de produtos e briefings. O conteúdo fica guardado e a IA aprende com ele. Ela usa isso nas pautas, nas ideias de post, nas respostas de comentários e na conversa abaixo."
      : "O que a IA da Mugô sabe sobre a sua empresa. Ela usa isso para criar as pautas e responder comentários, e você pode conversar com ela abaixo."}</p>
    <BrandKnowledge key={clientId} canManage={canManage} version={version} />
    <BrandAgent key={`agent:${clientId}`} canManage={canManage} company={company} onLearned={() => setVersion((v) => v + 1)} />
  </div></Shell>;
}
