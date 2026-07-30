import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  children: ReactNode;
};

type State = {
  hasError: boolean;
  message: string;
};

const FALLBACK_MESSAGE =
  "A interface do cliente ativo nao conseguiu iniciar. Revise as variaveis do frontend e tente novamente.";

export default class AppErrorBoundary extends Component<Props, State> {
  state: State = {
    hasError: false,
    message: FALLBACK_MESSAGE,
  };

  static getDerivedStateFromError(error: unknown): State {
    const message =
      error instanceof Error && error.message ? error.message : FALLBACK_MESSAGE;
    return { hasError: true, message };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error("[app-error-boundary]", error, info.componentStack);
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div
        style={{
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          padding: "24px",
          background:
            "radial-gradient(900px 360px at 12% -10%, rgba(215,219,106,.24), transparent 62%), #f2f0ec",
        }}
      >
        <div
          style={{
            width: "min(560px, 100%)",
            padding: "24px",
            borderRadius: "20px",
            background: "rgba(255,255,255,.92)",
            boxShadow: "0 18px 52px rgba(15, 23, 42, .10)",
          }}
        >
          <div className="pill pillDanger" style={{ marginBottom: 12 }}>
            Erro ao iniciar a Mugô Dados
          </div>
          <h1 style={{ margin: "0 0 10px" }}>A aplicacao encontrou um erro em runtime</h1>
          <p style={{ margin: 0, color: "rgba(15, 23, 42, .74)" }}>
            {this.state.message || FALLBACK_MESSAGE}
          </p>
        </div>
      </div>
    );
  }
}
