import { useEffect, useState } from "react";
import { getPublicReport, hasBusiness, type PublicReport as Report } from "../app/monthlyReport";
import { BusinessDeck, ReportDeck } from "./SocialReport";
import "../styles/studio.css";
import "../styles/social-report.css";

/** Relatório do mês pelo link (sem login): só o que a equipe liberou. Imprime em PDF como na tela da marca. */
export default function PublicReport({ token }: { token: string }) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getPublicReport(token).then(setReport).catch((cause) => setError(cause instanceof Error ? cause.message : "Relatório indisponível."));
  }, [token]);

  if (error) return <main className="publicReport"><p className="studioError" role="alert">{error}</p></main>;
  if (!report) return <main className="publicReport"><p role="status">Carregando o relatório…</p></main>;
  const social = report.social;
  return <main className="publicReport srPage">
    <header className="publicReportHead">
      <div><small>MUGOVERSO · relatório do mês</small><h1>{report.brand}</h1></div>
      <button type="button" className="ds-button is-primary" onClick={() => window.print()}>Baixar PDF</button>
    </header>
    {social.built && social.data ? <ReportDeck d={social.data} images={social.images || {}} brand={report.brand} insights={social.insights || []} /> : null}
    {hasBusiness(report.business) || report.summary ? <BusinessDeck b={report.business} summary={report.summary} month={report.month} /> : null}
  </main>;
}
