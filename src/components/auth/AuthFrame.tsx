import type { ReactNode } from "react";
import { LEGAL_CONTACT } from "../../app/legalContact";
import { MUGO_LOGO_ASSETS } from "../MugoLogo";
import "../../styles/Login.css";

type Props = {
  /** id do título do painel (aria-labelledby). */
  labelledBy: string;
  children: ReactNode;
};

/**
 * Moldura das telas de acesso (login, convite): o produto e uma frase de um
 * lado, o painel do outro, links legais no rodapé. Nada de clientes ou logos
 * de terceiros no lado do produto.
 */
export default function AuthFrame({ labelledBy, children }: Props) {
  return (
    <div className="loginPage">
      <main className="loginLayout">
        <section className="loginIntro" aria-label="Mugô Dados">
          <p className="loginProduct">
            <span className="loginProductMark" aria-hidden="true">
              <img src={MUGO_LOGO_ASSETS.symbol} alt="" />
            </span>
            <span className="loginProductName">Mugô Dados</span>
          </p>
          <p className="loginStatement">
            <span>Dados claros.</span>
            <span className="loginStatementSecond">Decisões melhores.</span>
          </p>
        </section>

        <section className="loginPanel" aria-labelledby={labelledBy}>
          <div className="loginPanelInner">{children}</div>
        </section>
      </main>

      <footer className="loginFooter">
        <nav aria-label="Privacidade e termos">
          <a href="/privacidade">Política de Privacidade</a>
          <a href="/termos-de-uso">Termos de Uso</a>
          <a href="/protecao-de-dados">Proteção de dados</a>
        </nav>
        <p>
          Privacidade: <a href={`mailto:${LEGAL_CONTACT}`}>{LEGAL_CONTACT}</a>
        </p>
      </footer>
    </div>
  );
}
