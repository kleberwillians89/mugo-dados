import "../../styles/skeleton.css";

/**
 * Esqueleto da página enquanto os dados chegam (feedback do designer): nada de número antigo ou vazio piscando.
 * Quando a página aparece, o que está na tela já é a leitura atual.
 */
export default function PageSkeleton({ label = "Carregando os dados…", cards = 4, rows = 4, chart = true }:
  { label?: string; cards?: number; rows?: number; chart?: boolean }) {
  return <div className="skPage" role="status" aria-live="polite" aria-busy="true">
    <span className="skSr">{label}</span>
    {cards ? <div className="skCards" aria-hidden="true">{Array.from({ length: cards }, (_, i) => <div key={i} className="skCard"><i className="sk skLine is-s" /><i className="sk skLine is-l" /><i className="sk skLine is-m" /></div>)}</div> : null}
    {chart ? <div className="sk skChart" aria-hidden="true" /> : null}
    {rows ? <div className="skRows" aria-hidden="true">{Array.from({ length: rows }, (_, i) => <i key={i} className="sk skRow" />)}</div> : null}
  </div>;
}
