import type { ReactNode } from "react";

type Props = {
  label: string;
  /** Valor formatado para leitura. */
  value: string;
  /** Valor numérico bruto (atributo value de <data>). */
  rawValue: number;
  /** Valor exato, exibido ao passar o mouse quando `value` é abreviado. */
  exactValue?: string;
  delta?: ReactNode;
  /** A métrica principal da página ganha mais espaço. */
  hero?: boolean;
  testId?: string;
};

/** Número protagonista, rótulo discreto, variação abaixo. Sem cartão. */
export default function KpiFigure({ label, value, rawValue, exactValue, delta, hero = false, testId }: Props) {
  return (
    <div className={`ds-kpi${hero ? " is-hero" : ""}`} data-testid={testId}>
      <data className="ds-kpiValue" value={String(rawValue)} title={exactValue}>{value}</data>
      <span className="ds-kpiLabel">{label}</span>
      <span className="ds-kpiDelta">{delta}</span>
    </div>
  );
}
