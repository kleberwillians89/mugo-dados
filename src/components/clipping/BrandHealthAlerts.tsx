import { useCallback, useEffect, useState, type FormEvent } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { SOURCE_CHIP, getHealthAlerts, resolveHealthAlert, saveHealthSettings, type HealthAlert, type HealthSettings } from "../../app/brandHealth";
import "../../styles/brandHealth.css";

const KIND: Record<HealthAlert["kind"], string> = { termo: "Termo sensível", queda_indice: "Queda do índice", negativas: "Negativas no dia" };
const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

/** Alertas (só equipe Mugô): lista, resolver e os termos sensíveis monitorados. */
export default function BrandHealthAlerts() {
  const clientId = getActiveClientId();
  const [alerts, setAlerts] = useState<HealthAlert[] | null>(null);
  const [settings, setSettings] = useState<HealthSettings | null>(null);
  const [termInput, setTermInput] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const out = await getHealthAlerts();
      if (getActiveClientId() !== clientId) return;
      setAlerts(out.alerts); setSettings(out.settings);
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível carregar os alertas.");
    }
  }, [clientId]);
  useEffect(() => { void load(); }, [load]);

  async function save(next: Partial<HealthSettings>, message = "Salvo.") {
    if (!settings) return;
    setBusy("settings"); setError(null); setNotice(null);
    try {
      const out = await saveHealthSettings({ sensitive_terms: next.sensitive_terms ?? settings.sensitive_terms,
        index_drop_points: next.index_drop_points ?? settings.index_drop_points, negative_day_pct: next.negative_day_pct ?? settings.negative_day_pct });
      setSettings(out); setNotice(message);
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível salvar.");
    } finally {
      setBusy(null);
    }
  }
  function addTerms(event: FormEvent) {
    event.preventDefault();
    if (!settings) return;
    const fresh = termInput.split(",").map((t) => t.trim()).filter((t) => t.length >= 3);
    if (!fresh.length) return;
    setTermInput("");
    void save({ sensitive_terms: [...settings.sensitive_terms, ...fresh] }, "Termo adicionado. Vale a partir da próxima checagem (a cada hora).");
  }
  async function resolve(alert: HealthAlert) {
    setBusy(alert.id); setError(null);
    try {
      await resolveHealthAlert(alert.id);
      await load();
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível resolver.");
    } finally {
      setBusy(null);
    }
  }

  const open = (alerts || []).filter((a) => a.status === "aberto"), closed = (alerts || []).filter((a) => a.status !== "aberto");
  return <div className="bhPage">
    <p className="libHint">Os alertas vão só para a equipe Mugô (WhatsApp, pela Central de Automações), nunca para o cliente. A checagem roda a cada hora nas notícias, comentários e Direct das últimas 48 h.</p>
    {error ? <p className="studioError" role="alert">{error}</p> : null}
    {notice ? <p className="studioOk" role="status">{notice}</p> : null}

    <div className="bhRow">
      <section className="bhCard" aria-labelledby="bh-open">
        <h2 id="bh-open">Alertas abertos</h2>
        {!alerts ? <p className="bhMuted">Carregando…</p> : !open.length ? <p className="bhMuted">Nenhum alerta aberto.</p> : open.map((a) => <div key={a.id} className={`bhAlert is-${a.severity}`}>
          <div className="bhAlertHead"><b>{a.kind === "termo" ? `“${a.term}” — ${a.mentions} ${a.mentions === 1 ? "menção" : "menções"}` : KIND[a.kind]}</b>
            <span className={`bhSev is-${a.severity}`}>{a.severity === "alto" ? "Alto" : "Médio"}</span></div>
          <small>{KIND[a.kind]} · {a.detail}{a.sources.length ? ` · ${a.sources.map((s) => SOURCE_CHIP[s]).join(", ")}` : ""} · desde {when(a.first_seen_at)}</small>
          {a.sample ? <p className="bhSample">“{a.sample}”</p> : null}
          <button type="button" className="ds-button" disabled={busy === a.id} onClick={() => void resolve(a)}>{busy === a.id ? "Resolvendo…" : "Marcar como resolvido"}</button>
        </div>)}
        {closed.length ? <details className="bhClosed"><summary>Resolvidos ({closed.length})</summary>
          <ul>{closed.map((a) => <li key={a.id}>{a.kind === "termo" ? `“${a.term}”` : KIND[a.kind]} · {a.mentions} · resolvido {a.resolved_at ? when(a.resolved_at) : ""}</li>)}</ul></details> : null}
      </section>

      <section className="bhCard" aria-labelledby="bh-terms">
        <h2 id="bh-terms">Termos sensíveis</h2>
        <p className="bhSub">Sem acento e sem diferença de maiúsculas. Notícia: 1 menção já alerta; comentário ou Direct: a partir de 2. Com 5 ou mais, o alerta é alto.</p>
        {settings ? <>
          <div className="bhTerms">{settings.sensitive_terms.map((t) => <span key={t}>{t}
            <button type="button" aria-label={`Remover ${t}`} disabled={Boolean(busy)} onClick={() => void save({ sensitive_terms: settings.sensitive_terms.filter((x) => x !== t) }, "Termo removido.")}>×</button></span>)}</div>
          <form className="bhTermForm" onSubmit={addTerms}>
            <label className="bhSrOnly" htmlFor="bh-term">Novo termo</label>
            <input id="bh-term" value={termInput} maxLength={200} placeholder="Ex.: vazou, cheiro fraco, troca (separe por vírgula)" onChange={(e) => setTermInput(e.target.value)} />
            <button className="ds-button is-primary" disabled={Boolean(busy) || termInput.trim().length < 3}>Adicionar</button>
          </form>
          <div className="bhLimits">
            <label>Avisar se o índice cair (pontos em 7 dias)
              <input type="number" min={3} max={50} defaultValue={settings.index_drop_points} onBlur={(e) => { const v = Number(e.target.value); if (v !== settings.index_drop_points && v >= 3 && v <= 50) void save({ index_drop_points: v }); }} /></label>
            <label>Avisar se as negativas passarem de (% no dia)
              <input type="number" min={5} max={80} defaultValue={settings.negative_day_pct} onBlur={(e) => { const v = Number(e.target.value); if (v !== settings.negative_day_pct && v >= 5 && v <= 80) void save({ negative_day_pct: v }); }} /></label>
          </div>
        </> : <p className="bhMuted">Carregando…</p>}
      </section>
    </div>
  </div>;
}
