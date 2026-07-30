import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  children: ReactNode;
};

type State = {
  hasError: boolean;
};

export default class DashboardErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error("[dashboard-error-boundary]", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            minHeight: "100vh",
            display: "grid",
            placeItems: "center",
            padding: "24px",
            background:
              "radial-gradient(900px 360px at 12% -10%, rgba(199,152,48,.20), transparent 62%), #f4f7fa",
          }}
        >
          <div style={{ maxWidth: 560, textAlign: "center" }}>
            <h2 style={{ marginBottom: 8 }}>O dashboard encontrou um erro</h2>
            <p style={{ color: "rgba(10,13,16,.70)" }}>
              Atualize a página. Se o problema continuar, revise a integração do cliente ativo na tela de configuração.
            </p>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
