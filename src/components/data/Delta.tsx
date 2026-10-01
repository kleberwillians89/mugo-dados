import { formatPercentNumber } from "../../app/dataFormat";

type Props = {
  /** Variação percentual já calculada; null/undefined = sem base de comparação. */
  change: number | null | undefined;
  /** Abaixo deste módulo (em pontos percentuais) a variação não ganha cor. */
  relevance?: number;
  reference?: string;
  /**
   * Escreve a referência ("em relação ao período anterior") por extenso.
   * Usado uma vez por página, no dado principal; nos demais a referência
   * fica só para leitores de tela, sem repetição visual.
   */
  showReference?: boolean;
  /**
   * O que é "melhor": alta (padrão), baixa (custos) ou nenhum dos dois
   * (investimento). Só muda a cor; seta e texto continuam iguais.
   */
  sentiment?: "higher-is-better" | "lower-is-better" | "neutral";
};

/**
 * Variação vs. período anterior. A seta e o texto acessível carregam o
 * sentido; a cor só reforça — e só quando a variação é relevante.
 * Sem base anterior mostra "—", nunca um 0% falso.
 */
export default function Delta({ change, relevance = 1, reference = "período anterior", showReference = false, sentiment = "higher-is-better" }: Props) {
  if (change === null || change === undefined || !Number.isFinite(change)) {
    if (showReference) {
      return (
        <span className="ds-delta">
          <span aria-hidden="true">—</span> sem base de comparação com o {reference}
        </span>
      );
    }
    return (
      <span className="ds-delta" title={`Sem base de comparação no ${reference}`}>
        <span aria-hidden="true">—</span>
        <span className="ds-srOnly">sem base de comparação no {reference}</span>
      </span>
    );
  }
  const direction = change > 0 ? "up" : change < 0 ? "down" : "flat";
  const favorable = sentiment === "lower-is-better" ? direction === "down" : direction === "up";
  const tone = direction === "flat" || Math.abs(change) < relevance || sentiment === "neutral"
    ? ""
    : favorable ? " is-positive" : " is-negative";
  const arrow = direction === "up" ? "↑" : direction === "down" ? "↓" : "→";
  const words = direction === "up" ? "acima do" : direction === "down" ? "abaixo do" : "igual ao";
  if (showReference) {
    const spoken = direction === "up" ? "alta de " : direction === "down" ? "queda de " : "variação de ";
    return (
      <span className={`ds-delta${tone}`}>
        <span aria-hidden="true">{arrow}</span>
        <span className="ds-srOnly">{spoken}</span>
        <span className="ds-deltaValue">{formatPercentNumber(Math.abs(change))}%</span>
        <span className="ds-deltaReference"> em relação ao {reference}</span>
      </span>
    );
  }
  return (
    <span className={`ds-delta${tone}`}>
      <span aria-hidden="true">{arrow}</span>
      {formatPercentNumber(Math.abs(change))}%
      <span className="ds-srOnly">{words} {reference}</span>
    </span>
  );
}
