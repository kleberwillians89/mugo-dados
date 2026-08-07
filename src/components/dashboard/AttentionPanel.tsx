import { computeExecutiveNarrative } from "./executiveNarrative";
import type { ExecutiveMetric } from "./ExecutiveOverview";

export default function AttentionPanel({ metrics }: { metrics: ExecutiveMetric[] }) {
  const { risk, opportunity, nextAction } = computeExecutiveNarrative(metrics);

  return (
    <div className="attentionPanel">
      <div className="attentionPanelHead">
        <h3>O que merece atenção</h3>
      </div>
      <div className="attentionRow is-risk">
        <span className="attentionLabel">{risk ? "Risco" : "Informação"}</span>
        <p className="attentionText">
          {risk
            ? `${risk.metric.label} caiu ${Math.abs(risk.percent || 0).toFixed(1)}% frente ao período anterior.`
            : "Nenhuma queda comparável confirmada neste período."}
        </p>
      </div>
      <div className="attentionRow is-opportunity">
        <span className="attentionLabel">Oportunidade</span>
        <p className="attentionText">{opportunity}</p>
      </div>
      <div className="attentionRow is-action">
        <span className="attentionLabel">Próxima ação</span>
        <p className="attentionText">{nextAction}</p>
      </div>
    </div>
  );
}
