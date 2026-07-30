type Props = {
  aiReport: Record<string, unknown> | null;
  aiErr: string | null;
};

type AiWord = {
  word: string;
  count: number;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function toUnknownArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export default function AiSummaryCard({ aiReport, aiErr }: Props) {
  const aiReportData = asRecord(aiReport);
  const aiInsights = toUnknownArray(aiReportData.insights);
  const aiOpportunities = toUnknownArray(aiReportData.content_opportunities);
  const aiRisks = toUnknownArray(aiReportData.risks);
  const aiActions = toUnknownArray(aiReportData.next_actions);
  const aiTopWordsRaw = toUnknownArray(aiReportData.top_words);
  const aiTopWords: AiWord[] = aiTopWordsRaw.map((item) => {
    const row = asRecord(item);
    return {
      word: String(row.word ?? ""),
      count: Number(row.count ?? 0),
    };
  });

  return (
    <div className="sidebarCard">
      <div className="sidebarHead">
        <div className="sidebarTitle">Resumo Estratégico</div>
        <div className="sidebarSub">Clique em “Análise IA” para gerar (a memória vem depois).</div>
      </div>

      {aiErr ? <div className="pill pillDanger">{aiErr}</div> : null}

      {!aiReport ? (
        <div className="emptyBox">Ainda sem relatório. Clique em “Análise IA”.</div>
      ) : (
        <div className="aiStack">
          <div className="aiBlock">
            <div className="aiBlockTitle">Resumo Estratégico</div>
            <div className="aiText">
              {String(aiReportData.data_quality_note || aiReportData.week_summary || "—")}
            </div>
          </div>

          <div className="aiBlock">
            <div className="aiBlockTitle">Insights Práticos</div>
            <div className="aiList">
              {aiInsights.length
                ? aiInsights.slice(0, 7).map((insight: unknown, index: number) => (
                    <div className="aiItem" key={index}>
                      <span className="rank">{index + 1}</span>
                      <span className="aiItemText">{String(insight)}</span>
                    </div>
                  ))
                : "—"}
            </div>
          </div>

          <div className="aiBlock">
            <div className="aiBlockTitle">Oportunidades</div>
            <div className="aiList">
              {aiOpportunities.length
                ? aiOpportunities.map((opportunity: unknown, index: number) => (
                    <div className="aiPill" key={index}>
                      {String(opportunity)}
                    </div>
                  ))
                : "—"}
            </div>
          </div>

          <div className="aiBlock">
            <div className="aiBlockTitle">Riscos e Próximas Ações</div>
            <div className="aiList">
              {aiRisks.length
                ? aiRisks.map((risk: unknown, index: number) => (
                    <div className="aiIdea" key={index}>
                      Risco: {String(risk)}
                    </div>
                  ))
                : "—"}
              {aiActions.length
                ? aiActions.map((action: unknown, index: number) => (
                    <div className="aiIdea" key={`a-${index}`}>
                      Ação: {String(action)}
                    </div>
                  ))
                : null}
            </div>
          </div>

          <div className="aiBlock">
            <div className="aiBlockTitle">Top Palavras</div>
            <div className="aiList">
              {aiTopWords.length
                ? aiTopWords.slice(0, 12).map((word: AiWord, index: number) => (
                    <div className="aiPill" key={`w-${index}`}>
                      {String(word.word || "")} ({Number(word.count || 0)})
                    </div>
                  ))
                : "Sem dados suficientes de comentários"}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
