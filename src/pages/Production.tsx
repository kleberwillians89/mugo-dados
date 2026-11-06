import { ArrowUpRight, Clapperboard, FileText, Image as ImageIcon, Library, PenTool } from "lucide-react";
import { getActiveClientName } from "../app/activeClient";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import "../styles/studio.css";

/** Endereço do iAgência (configurável por ambiente). */
export const IAGENCIA_URL = String(import.meta.env.VITE_IAGENCIA_URL || "https://iagencia.ia.br").replace(/\/+$/, "");

const MODULES = [
  { path: "/production", icon: FileText, title: "Produção", text: "Planos de produção do mês: do rascunho à aprovação de cada peça." },
  { path: "/creation", icon: PenTool, title: "Criação", text: "Textos e peças com os agentes de criação a partir do briefing." },
  { path: "/image-studio", icon: ImageIcon, title: "Estúdio de imagem", text: "Gere e ajuste imagens no estilo da marca." },
  { path: "/video-studio", icon: Clapperboard, title: "Estúdio de vídeo", text: "Vídeos curtos para Reels e anúncios." },
  { path: "/library", icon: Library, title: "Biblioteca", text: "Artes e materiais prontos da marca." },
];

/**
 * Produção de conteúdo com a iAgência (no lugar da antiga Redação). Abre cada módulo da iAgência em outra aba,
 * com o login da iAgência. A arte pronta volta para o Mugoverso pela janela do post (arrastar ou "Trazer arte").
 */
export default function Production() {
  const brand = getActiveClientName() || "marca";
  return <Shell title="Produção de conteúdo" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={brand} title="Produção de conteúdo" />
    <p className="libHint">Feita com a <b>iAgência</b>. Cada módulo abre em outra aba, com o seu login da iAgência. Peça pronta? Leve para o
      Calendário do Mugoverso: abra o post e arraste a arte (ou cole o link e clique em <b>Trazer arte</b>) para aprovar com o cliente e publicar.</p>
    <div className="prodGrid">
      {MODULES.map((m) => { const Icon = m.icon; return <a key={m.path} className="prodCard" href={`${IAGENCIA_URL}${m.path}`} target="_blank" rel="noreferrer noopener">
        <span className="prodIcon" aria-hidden="true"><Icon size={20} /></span>
        <b>{m.title} <ArrowUpRight size={14} aria-hidden="true" /></b>
        <small>{m.text}</small>
      </a>; })}
    </div>
    <p className="prodFoot">iAgência · produção de conteúdo da Mugô</p>
  </div></Shell>;
}
