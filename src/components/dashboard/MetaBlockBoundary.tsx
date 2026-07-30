import { Component, type ErrorInfo, type ReactNode } from "react";

import MetaStateNotice from "./MetaStateNotice";

type Props = {
  children: ReactNode;
  resetKey: string;
  title: string;
  description?: string;
  fallbackMessage?: string;
};

type State = {
  hasError: boolean;
};

export default class MetaBlockBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error(
      "[meta-block-boundary]",
      this.props.title,
      error,
      info.componentStack
    );
  }

  componentDidUpdate(prevProps: Props) {
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false });
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="card cardWide">
          <MetaStateNotice
            title={this.props.title}
            description={this.props.description}
            tone="unavailable"
            message={
              this.props.fallbackMessage ||
              "Esse bloco encontrou um erro, mas o restante do dashboard continua disponível."
            }
            secondaryMessage="Atualize o período ou a conexão para tentar novamente."
          />
        </div>
      );
    }

    return this.props.children;
  }
}
