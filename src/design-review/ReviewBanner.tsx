import { REVIEW_SCENARIOS, type ReviewScenario } from "./fixtures";

type Props = {
  /** Rótulo do perfil simulado (ex.: "Administrador do cliente"). */
  profileLabel?: string;
  /** Cenários do Ecommerce, quando a tela for Ecommerce. */
  scenario?: ReviewScenario;
};

/** Aviso fixo do harness: números, empresas e pessoas são de exemplo. */
export default function ReviewBanner({ profileLabel, scenario }: Props) {
  function withScenario(id: ReviewScenario) {
    const params = new URLSearchParams(window.location.search);
    params.set("cenario", id);
    return `?${params.toString()}`;
  }
  return (
    <aside className="designReviewBanner" aria-label="Revisão visual">
      <strong>Revisão visual · dados de exemplo</strong>
      <span>{profileLabel ? `Perfil: ${profileLabel}. ` : ""}Nada aqui é dado real de clientes.</span>
      <nav>
        <a href="?">Índice</a>
        {scenario
          ? REVIEW_SCENARIOS.map((item) => (
              <a key={item.id} href={withScenario(item.id)} aria-current={item.id === scenario ? "page" : undefined}>{item.label}</a>
            ))
          : null}
      </nav>
    </aside>
  );
}
