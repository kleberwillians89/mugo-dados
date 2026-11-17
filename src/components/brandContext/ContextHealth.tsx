import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, CircleDashed } from "lucide-react";
import { getContextHealth, type ContextHealth as Health, type HealthItem } from "../../app/brandContext";

const ICON = { ok: CheckCircle2, atencao: AlertTriangle, falta: CircleDashed } as const;

/**
 * O que falta ou está velho para a IA trabalhar bem com esta marca (regras fixas, sem IA).
 * ``onAction`` leva para a aba ou tela que resolve. ``version`` muda quando algo foi salvo: recarrega.
 */
export default function ContextHealth({ onAction, version = 0 }: { onAction?: (action: NonNullable<HealthItem["action"]>) => void; version?: number }) {
  const [data, setData] = useState<Health | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    getContextHealth().then((d) => { if (alive) { setData(d); setFailed(false); } }).catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [version]);

  if (failed || !data) return null;  // painel de apoio: sem ele a tela segue normal
  const pending = data.items.filter((i) => i.level !== "ok");
  const shown = open ? data.items : pending.slice(0, 4);
  const tone = data.score >= 85 ? "is-good" : data.score >= 60 ? "is-mid" : "is-low";

  return <section className="bcCard bcHealth" aria-labelledby="bc-health-title" data-testid="context-health">
    <header className="bcCardHead">
      <div className="bcHealthScore">
        <span className={`bcScore ${tone}`} aria-label={`Contexto ${data.score}% completo`}>{data.score}%</span>
        <div><h2 id="bc-health-title">Saúde do contexto</h2>
          <p className="libHint">{pending.length ? `${pending.length} ponto(s) para a IA conhecer melhor a marca.` : "Tudo em dia: a IA tem o que precisa desta marca."}</p></div>
      </div>
      {data.items.length > shown.length || open ? <button type="button" className="kbLink" onClick={() => setOpen((v) => !v)}>{open ? "Ver só pendências" : "Ver tudo"}</button> : null}
    </header>
    {shown.length ? <ul className="bcHealthList">{shown.map((item) => {
      const Icon = ICON[item.level];
      return <li key={item.id} className={`is-${item.level}`}>
        <Icon size={16} aria-hidden="true" />
        <div><b>{item.title}</b><small>{item.detail}</small></div>
        {item.action && onAction && item.level !== "ok" ? <button type="button" className="ds-button" onClick={() => onAction(item.action!)}>Resolver</button> : null}
      </li>;
    })}</ul> : null}
  </section>;
}
