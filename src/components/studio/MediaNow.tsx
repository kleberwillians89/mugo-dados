import { useEffect, useState } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { getLiveRead, getMediaNow, type LiveReadNote, type MediaNowCampaign, type MediaNowSignal } from "../../app/metaAds";

const SIGNAL: Record<MediaNowSignal, { icon: string; label: string; tone: string }> = {
  bem: { icon: "✅", label: "Indo bem", tone: "is-good" },
  atencao: { icon: "⚠️", label: "Atenção", tone: "is-warn" },
  aprendendo: { icon: "⏳", label: "Aprendendo", tone: "is-learn" },
};
const brl = (n: number | null | undefined) => n == null ? "—" : n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);
const int = (n: number | null | undefined) => n == null ? "—" : Math.round(n).toLocaleString("pt-BR");

/** "Sua mídia agora": só campanhas no ar, cada uma com o número que importa para o objetivo dela. Sem palpite. */
export default function MediaNow({ showRecommendations }: { showRecommendations: boolean }) {
  const clientId = getActiveClientId();
  const [items, setItems] = useState<MediaNowCampaign[] | null>(null);
  const [spend7, setSpend7] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [tips, setTips] = useState<LiveReadNote[] | null>(null);

  useEffect(() => {
    let alive = true;
    getMediaNow().then((out) => {
      if (!alive || getActiveClientId() !== clientId) return;
      setItems(out.campaigns); setSpend7(out.spend_7d);
      const judgeable = new Set(out.campaigns.filter((c) => c.recomendavel).map((c) => c.id));
      if (showRecommendations && judgeable.size) {
        // Recomendação da IA só sobre campanha ativa com dado suficiente; no máximo 3.
        getLiveRead().then((read) => { if (alive) setTips((read.melhorias || []).filter((n) => judgeable.has(n.id)).slice(0, 3)); })
          .catch(() => { if (alive) setTips([]); });
      } else setTips([]);
    }).catch((cause) => { if (alive) setError(cause instanceof Error ? cause.message : "Não foi possível ler as campanhas agora."); });
    return () => { alive = false; };
  }, [clientId, showRecommendations]);

  const attention = (items || []).filter((c) => c.sinal === "atencao").length;
  return <>
    <section className="ds-section mediaNow" aria-labelledby="media-now-title">
      <div className="mediaNowHead"><h2 id="media-now-title">Sua mídia agora</h2>
        <small>Só campanhas no ar · Meta ao vivo e Google pela última sincronização</small></div>
      {error ? <p role="alert" className="studioError">{error}</p> : null}
      {items === null && !error ? <p className="libHint" role="status">Lendo as campanhas no ar…</p> : null}
      {items && !items.length ? <p className="mediaNowEmpty">Nenhuma campanha no ar agora.</p> : null}
      {items && items.length ? <>
        <div className="mediaNowTotals">
          <div><span>No ar</span><strong>{items.length}</strong></div>
          <div><span>Investido nos últimos 7 dias</span><strong>{brl(spend7)}</strong></div>
          <div><span>Pedem atenção</span><strong className={attention ? "is-warn" : ""}>{attention}</strong></div>
        </div>
        <ul className="mediaNowList">{items.map((c) => {
          const s = SIGNAL[c.sinal];
          return <li key={c.id} className={s.tone}>
            <div className="mediaNowName"><b>{c.campanha}</b><small>{c.canal} · {c.objetivo}{c.verba_diaria ? ` · ${brl(c.verba_diaria)}/dia` : ""}</small></div>
            <dl>
              <div><dt>Investido</dt><dd>{brl(c.investido)}</dd></div>
              <div><dt>{cap(c.resultado.label)}</dt><dd>{int(c.resultado.value)}</dd></div>
              <div><dt>{cap(c.resultado.cost_label)}</dt><dd>{brl(c.resultado.cost)}</dd></div>
              {c.resultado.roas != null ? <div><dt>ROAS</dt><dd>{c.resultado.roas.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}</dd></div> : null}
            </dl>
            <p className="mediaNowSignal" title={c.motivo}><span aria-hidden="true">{s.icon}</span> <b>{s.label}</b> · {c.motivo}</p>
          </li>;
        })}</ul>
      </> : null}
    </section>
    {showRecommendations && tips && tips.length ? <section className="ds-section mediaNowTips" aria-labelledby="media-now-tips">
      <h2 id="media-now-tips">O que a Mugô recomenda</h2>
      <small>Só sobre campanhas no ar há pelo menos 7 dias e com investimento suficiente para julgar.</small>
      <ol>{tips.map((t) => <li key={`${t.id}:${t.texto}`}><b>{t.campanha}</b> <small>({t.canal})</small>: {t.texto}</li>)}</ol>
    </section> : null}
  </>;
}
