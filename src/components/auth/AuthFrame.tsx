import type { ReactNode } from "react";
import { LEGAL_CONTACT } from "../../app/legalContact";
import { MUGO_LOGO_ASSETS, MUGO_LOGO_VIDEO, PRODUCT_WORDMARK } from "../MugoLogo";
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
        <section className="loginIntro" aria-label="Mugoverso">
          <p className="loginProduct">
            <span className="loginProductName">{PRODUCT_WORDMARK}</span>
          </p>
          <div className="loginStage">
            {/* Logo girando acima da frase. Sem som, em loop; quem prefere menos movimento vê o logo parado. */}
            <video className="loginLogoVideo" autoPlay muted loop playsInline preload="auto" poster={MUGO_LOGO_VIDEO.poster} aria-hidden="true">
              <source src={MUGO_LOGO_VIDEO.mp4} type="video/mp4" />
            </video>
            <img className="loginLogoStill" src={MUGO_LOGO_ASSETS.mark3d} alt="" aria-hidden="true" />
          <p className="loginStatement">
            <span>Dados claros.</span>
            <span className="loginStatementSecond">Decisões melhores.</span>
          </p>
          </div>
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
