import { useState } from "react";
import { getAiSummary } from "../app/api";

type ContentIdea = {
  hook?: string;
};

type AiSummaryReport = {
  week_summary?: string;
  reach_drivers?: string[];
  improvements?: string[];
  content_ideas?: ContentIdea[];
};

function asReport(value: unknown): AiSummaryReport | null {
  if (!value || typeof value !== "object") return null;
  return value as AiSummaryReport;
}

export default function AiInsights({ days }: { days: number }) {
  const [data, setData] = useState<AiSummaryReport | null>(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    setLoading(true);
    try {
      const r = await getAiSummary(days);
      setData(asReport(r.report));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="glass section">
      <div className="sectionHead">
        <div>
          <div className="h1">Insights Estratégicos da IA</div>
          <div className="p">Análise automática dos dados.</div>
        </div>

        <button className="btn btnPrimary" onClick={run}>
          {loading ? "Gerando..." : "Gerar análise"}
        </button>
      </div>

      {!data && (
        <div className="smallMuted">
          Clique em "Gerar análise" para ver insights.
        </div>
      )}

      {data && (
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <div>
            <h3>Resumo da semana</h3>
            <p>{data.week_summary || "—"}</p>
          </div>

          <div>
            <h3>Drivers de alcance</h3>
            <ul>
              {(data.reach_drivers || []).map((i: string, k: number) => (
                <li key={k}>{i}</li>
              ))}
            </ul>
          </div>

          <div>
            <h3>O que melhorar</h3>
            <ul>
              {(data.improvements || []).map((i: string, k: number) => (
                <li key={k}>{i}</li>
              ))}
            </ul>
          </div>

          <div>
            <h3>Pautas sugeridas</h3>
            <ul>
              {(data.content_ideas || []).map((i: ContentIdea, k: number) => (
                <li key={k}>{i.hook || "—"}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
