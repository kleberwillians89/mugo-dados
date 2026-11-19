import { Component, type ErrorInfo, type ReactNode } from "react";

/** Painel novo nunca derruba a tela de baixo: se quebrar, some e registra no console. */
export default class QuietBoundary extends Component<{ children: ReactNode; name: string }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: unknown, info: ErrorInfo) { console.error(`[${this.props.name}]`, error, info.componentStack); }
  render() { return this.state.failed ? null : this.props.children; }
}
