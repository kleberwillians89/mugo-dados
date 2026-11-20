import { useCallback, useEffect, useState } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { deliverySummary } from "./metaLiveSummary";
import { activateAdDraft, pauseAdDraft, readAdResults, readMetaLiveDeliveryStatus,
  type AdDraft, type MetaCampaignResults, type MetaLiveDeliveryStatus } from "../../app/metaAds";

const brl = (v: number) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const int = (v: number) => v.toLocaleString("pt-BR");
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const PERIODS: { id: MetaCampaignResults["period"]; label: string }[] = [
  { id: "today", label: "Hoje" }, { id: "yesterday", label: "Ontem" }, { id: "last_7d", label: "7 dias" }, { id: "maximum", label: "Desde o início" },
];

/**
 * Campanha já criada na Meta: estado real, ligar/pausar e números de resultado, tudo sem sair do MUGOVERSO.
 * Ligar pede confirmação explícita da verba (é quando começa a gastar). Pausar é imediato.
 */
export default function MetaLiveCampaign({ draft, adsCount }: { draft: AdDraft; adsCount: number }) {
  const [status, setStatus] = useState<MetaLiveDeliveryStatus | null>(null);
  const [results, setResults] = useState<MetaCampaignResults | null>(null);
  const [period, setPeriod] = useState<MetaCampaignResults["period"]>("maximum");
  const [busy, setBusy] = useState<"load" | "on" | "off" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [approved, setApproved] = useState(false);
  const joined = Boolean(draft.joined || draft.meta_ids?.joined);
  const clientId = getActiveClientId();
  const p = draft.payload;

  const load = useCallback(async (which: MetaCampaignResults["period"]) => {
    setBusy("load"); setError(null);
    try {
      const [s, r] = await Promise.all([readMetaLiveDeliveryStatus(draft.id), readAdResults(draft.id, which).catch(() => null)]);
      if (getActiveClientId() !== clientId) return;
      setStatus(s); setResults(r);
    } catch (cause) {
      if (getActiveClientId() === clientId) setError(message(cause, "Não foi possível consultar a Meta agora."));
    } finally { setBusy(null); }
  }, [draft.id, clientId]);
  useEffect(() => { void load(period); }, [load, period]);

  async function turnOn() {
    setBusy("on"); setError(null);
    try {
      setStatus(await activateAdDraft(draft.id, joined ? undefined : p.daily_budget));
      setConfirming(false); setApproved(false);
    } catch (cause) { setError(message(cause, "A Meta não deixou ativar agora.")); }
    finally { setBusy(null); }
  }
  async function turnOff() {
    setBusy("off"); setError(null);
    try { setStatus(await pauseAdDraft(draft.id)); }
    catch (cause) { setError(message(cause, "Não foi possível pausar. Pause pelo Gerenciador.")); }
    finally { setBusy(null); }
  }

  const summary = deliverySummary(status);
  // The saved last action is audit history, not current Meta delivery.
  const running = summary.tone === "ok";
  const period_label = PERIODS.find((x) => x.id === period)?.label;
  return <section className="metaLive" aria-label={`Na Meta: ${p.name}`}>
    <div className={`metaLiveHead is-${summary.tone}`} role="status">
      <span className="metaLiveDot" aria-hidden="true" />
      <div><b>{summary.title}</b>{summary.detail ? <small>{summary.detail}</small> : null}</div>
      <span className="metaLiveActions">
        {status && (running
          ? <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void turnOff()}>{busy === "off" ? "Pausando…" : "Pausar"}</button>
          : <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => setConfirming(true)}>Ativar na Meta</button>)}
        <button type="button" className="ds-link" disabled={Boolean(busy)} onClick={() => void load(period)}>{busy === "load" ? "Atualizando…" : "Atualizar"}</button>
      </span>
    </div>

    {confirming && !running ? <div className="metaLiveConfirm" role="dialog" aria-label="Confirmar ativação">
      <b>Ativar e começar a gastar?</b>
      {joined ? <p>Liga só este anúncio, dentro da campanha original. A verba é a da campanha original.</p>
        : <ul>
          <li>Verba: <b>até {brl(p.daily_budget)} por dia</b>, de {p.start_date.split("-").reverse().join("/")} a {p.end_date.split("-").reverse().join("/")} (no máximo cerca de {brl(p.daily_budget * Math.max(1, Math.round((Date.parse(p.end_date) - Math.max(Date.parse(p.start_date), Date.now())) / 86_400_000) + 1))} no período).</li>
          <li>{adsCount} anúncio{adsCount === 1 ? "" : "s"} no mesmo conjunto. A cobrança vai no cartão da conta de anúncios do cliente.</li>
          <li>Começa assim que a Meta aprovar os anúncios. Dá para pausar aqui a qualquer momento.</li>
        </ul>}
      <label className="metaAdsCheck"><input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} />
        Confirmo que o cliente aprovou esta campanha{joined ? "" : " e a verba"}.</label>
      <span className="metaLiveActions">
        <button type="button" className="ds-button" disabled={busy === "on"} onClick={() => { setConfirming(false); setApproved(false); }}>Cancelar</button>
        <button type="button" className="ds-button is-primary" disabled={!approved || busy === "on"} onClick={() => void turnOn()}>
          {busy === "on" ? "Ativando…" : "Ativar agora"}</button>
      </span>
    </div> : null}

    {error ? <p className="studioError" role="alert">{error}</p> : null}

    <div className="metaLiveResults">
      <div className="metaLivePeriods" role="group" aria-label="Período dos resultados">
        {PERIODS.map((x) => <button key={x.id} type="button" aria-pressed={period === x.id} className={period === x.id ? "is-active" : ""}
          disabled={busy === "load"} onClick={() => setPeriod(x.id)}>{x.label}</button>)}
      </div>
      {results ? <>
        <p className="metaLiveHeadline">{results.spend > 0
          ? `${period_label}: ${brl(results.spend)} investidos${results.results ? `, ${int(results.results)} ${results.result_label.toLowerCase()}${results.cost_per_result ? ` (${brl(results.cost_per_result)} cada)` : ""}` : ", ainda sem resultados"}.`
          : `${period_label}: nada gasto ainda.`}</p>
        <dl className="metaLiveGrid">
          <div><dt>Investido</dt><dd>{brl(results.spend)}</dd></div>
          <div><dt>{results.result_label}</dt><dd>{int(results.results)}</dd></div>
          <div><dt>Custo por resultado</dt><dd>{results.cost_per_result != null ? brl(results.cost_per_result) : "—"}</dd></div>
          <div><dt>Pessoas alcançadas</dt><dd>{int(results.reach)}</dd></div>
          <div><dt>Cliques</dt><dd>{int(results.clicks)}</dd></div>
          <div><dt>Taxa de cliques</dt><dd>{results.ctr.toLocaleString("pt-BR")}%</dd></div>
        </dl>
        <small className="metaLiveFoot">Números da Meta · atualizado {new Date(results.checked_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}. A Meta pode levar algumas horas para fechar os números do dia.
          {status?.delivery ? ` ${status.delivery.state === "ativa" ? "Ativada" : "Pausada"} por ${status.delivery.by} em ${new Date(status.delivery.at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}.` : ""}</small>
      </> : busy === "load" ? <p className="ds-caption">Buscando os números na Meta…</p> : null}
    </div>
  </section>;
}
