import type { ReactNode } from "react";

type Props = {
  /** Empresa analisada — a marca já está na sidebar; aqui, só o nome. */
  company?: string | null;
  /** Nome da página (único h1). */
  title: string;
  /** Subnavegação da página (ex.: Google Ads | Google Analytics), logo abaixo do título. */
  subnav?: ReactNode;
  /** Procedência dos dados (fonte, sincronização e ações): menor, menos contraste. */
  dateline?: ReactNode;
  /** Controle principal da página, em geral o período. */
  controls?: ReactNode;
  /** Painel que só existe enquanto aberto (ex.: datas do período personalizado). */
  panel?: ReactNode;
  /** Nota do controle, ex.: as datas efetivas do período. */
  controlsNote?: ReactNode;
};

/**
 * Cabeçalho comum das páginas: onde estou (empresa › página) à esquerda,
 * período à direita. Nada de marca do produto nem navegação aqui.
 */
export default function PageHeader({ company, title, subnav, dateline, controls, panel, controlsNote }: Props) {
  return (
    <header className="ds-pageHeader">
      <div className="ds-pageHeaderIdentity">
        {company ? <p className="ds-pageEyebrow">{company}</p> : null}
        <h1 className="ds-pageTitle">{title}</h1>
        {subnav ? <div className="ds-pageSubnav">{subnav}</div> : null}
        {dateline ? <div className="ds-dateline">{dateline}</div> : null}
      </div>
      {controls || panel || controlsNote ? (
        <div className="ds-pageHeaderAside">
          {controls}
          {panel}
          {controlsNote ? <p className="ds-controlsNote">{controlsNote}</p> : null}
        </div>
      ) : null}
    </header>
  );
}
