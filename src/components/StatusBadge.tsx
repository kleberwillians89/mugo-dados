export type StatusTone = "success" | "info" | "warning" | "error" | "neutral";

type Props = {
  label: string;
  tone: StatusTone;
};

/**
 * Badge único de status, reutilizado em Integrações e Administração.
 * Mantém a mesma linguagem visual para qualquer um dos 8 estados de
 * conexão do produto (conectado, configuração necessária, sincronizando,
 * sincronizado, erro, token expirado, permissão insuficiente,
 * desconectado) — nunca duas versões visuais para o mesmo significado.
 */
export default function StatusBadge({ label, tone }: Props) {
  return <span className={`statusBadge is-${tone}`} role="status">{label}</span>;
}
