type Props = {
  onGoHome?: () => void;
};

/** Tela que o usuário não tem permissão para ver (Usuários e acessos por módulo). */
export default function AccessRestricted({ onGoHome }: Props) {
  return (
    <main className="routeStatePage">
      <section className="routeStateCard">
        <span className="routeStateCode">Acesso restrito</span>
        <h1>Você não tem acesso a esta tela</h1>
        <p>Peça ao administrador da sua empresa para liberar em Usuários.</p>
        {onGoHome ? (
          <button className="btn btnPrimary" type="button" onClick={onGoHome}>
            Ir para uma tela liberada
          </button>
        ) : null}
      </section>
    </main>
  );
}
