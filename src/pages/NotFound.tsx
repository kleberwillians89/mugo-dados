type Props = {
  onGoHome: () => void;
};

export default function NotFound({ onGoHome }: Props) {
  return (
    <main className="routeStatePage">
      <section className="routeStateCard">
        <span className="routeStateCode">404</span>
        <h1>Página não encontrada</h1>
        <p>O endereço informado não existe no Mugô Dados.</p>
        <button className="btn btnPrimary" type="button" onClick={onGoHome}>
          Voltar ao dashboard
        </button>
      </section>
    </main>
  );
}
