import type { ReactNode } from "react";
import MetricHelp from "./MetricHelp";
import type { MetricId } from "../../app/metricGlossary";

type Props = {
  /** Valor formatado para leitura (pode ser abreviado). */
  value: string;
  /** Valor numérico bruto (atributo value de <data>). */
  rawValue?: number;
  /** Valor exato, exibido ao passar o mouse quando `value` é abreviado. */
  exactValue?: string;
  /** Complemento em linguagem natural: "vendidos no período". */
  label: string;
  metricId?: MetricId;
  /** Variação, com a referência por extenso (única vez na página). */
  delta?: ReactNode;
  testId?: string;
};

/**
 * O dado principal da página: a primeira coisa que se lê. Um número,
 * o que ele significa e se melhorou ou piorou — sem cartão, sem ícone.
 */
export default function HeroFigure({ value, rawValue, exactValue, label, metricId, delta, testId }: Props) {
  return (
    <div className="ds-hero" data-testid={testId}>
      <data className="ds-heroValue" value={rawValue == null ? undefined : String(rawValue)} title={exactValue}>{value}</data>
      <p className="ds-heroLabel">{label}<MetricHelp label={label} metricId={metricId} /></p>
      {delta ? <p className="ds-heroDelta">{delta}</p> : null}
    </div>
  );
}
