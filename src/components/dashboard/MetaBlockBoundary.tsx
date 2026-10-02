import { Component, type ErrorInfo, type ReactNode } from "react";

import DataNotice from "../data/DataNotice";

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
        <DataNotice tone="negative" role="alert" title={`${this.props.title} indisponível`}>
          {this.props.fallbackMessage ||
            "Esse bloco encontrou um erro, mas o restante da página continua disponível."}{" "}
          Atualize o período ou a conexão para tentar novamente.
        </DataNotice>
      );
    }

    return this.props.children;
  }
}
