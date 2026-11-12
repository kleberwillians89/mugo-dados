import { CloudRain, Snowflake, Sun, TriangleAlert, Wind, type LucideIcon } from "lucide-react";
import { refreshEventRadar, type EventRadar as Radar, type Project } from "../../app/projects";

type Run = <T>(key: string, fn: () => Promise<T>, fallback: string) => Promise<T | null>;
const ALERT_ICON: Record<string, LucideIcon> = { chuva: CloudRain, calor: Sun, frio: Snowflake, vento: Wind };
const fmt = (n?: number | null, unit = "") => (n == null ? "—" : `${Math.round(n)}${unit}`);
const day = (iso?: string | null) => (iso ? new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) : "");

/**
 * Radar do evento: clima do dia (previsão até 15 dias; mais longe, clima típico da época) e notícias da região
 * (chuva, alerta, trânsito, interdição). Os alertas entram no plano da IA (riscos, checklist e plano B).
 */
export default function EventRadar({ project, busy, run, onChange }: { project: Project; busy: string | null; run: Run; onChange: (p: Project) => void }) {
  const radar: Radar = project.radar || {};
  const w = radar.clima || {};
  const location = project.inputs?.location;
  const has = Boolean(radar.atualizado_em);

  async function refresh() {
    const r = await run("radar", () => refreshEventRadar(project.id), "Não foi possível puxar clima e notícias agora.");
    if (r) onChange(r.project);
  }

  return <section className="evRadar" aria-label="Clima e notícias da região">
    <header>
      <div><h3>Clima e notícias da região</h3>
        <small className="libHint">{location ? `${radar.local?.name || location}${radar.local?.region ? `, ${radar.local.region}` : ""}` : "Coloque o local do evento para puxar o clima e as notícias."}
          {has ? ` · atualizado ${new Date(radar.atualizado_em!).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}` : ""}</small></div>
      <button type="button" className="ds-button" disabled={busy !== null || !location} onClick={() => void refresh()}>
        {busy === "radar" ? "Buscando…" : has ? "Atualizar" : "Puxar clima e notícias"}</button>
    </header>
    {has ? <>
      {w.tipo === "previsao" ? <div className="evWeather">
        <b>{fmt(w.max, "°")}<small> / {fmt(w.min, "°")}</small></b>
        <span>Previsão para {day(w.data)}: {w.condicao || "sem descrição"}</span>
        <span>Chuva {fmt(w.chance_chuva, "%")}{w.chuva_mm ? ` (${w.chuva_mm} mm)` : ""} · vento até {fmt(w.vento_kmh, " km/h")}</span>
      </div> : null}
      {w.tipo === "clima_tipico" ? <div className="evWeather is-typical">
        <b>{fmt(w.max, "°")}<small> / {fmt(w.min, "°")}</small></b>
        <span>Clima típico de {day(w.data)} (média de {w.anos} anos; não é previsão)</span>
        <span>Chove em {fmt(w.dias_com_chuva_pct, "%")} dos dias nesta época. A previsão aparece a 15 dias do evento.</span>
      </div> : null}
      {w.tipo === "passou" ? <p className="libHint">A data do evento já passou.</p> : null}
      {radar.alertas?.length ? <ul className="evAlerts">{radar.alertas.map((a) => <li key={a.tipo} className={`is-${a.gravidade}`}>
        {(() => { const Icon = ALERT_ICON[a.tipo] || TriangleAlert; return <Icon className="uiGlyph" size={14} aria-hidden="true" />; })()}{a.texto}</li>)}</ul> : null}
      {radar.noticias?.length ? <details className="evNews" open={Boolean(radar.alertas?.length)}><summary>Notícias da região ({radar.noticias.length}, últimos 7 dias)</summary>
        <ul>{radar.noticias.map((n) => <li key={n.link}><a href={n.link} target="_blank" rel="noreferrer noopener">{n.manchete} ↗</a>
          <small>{[n.fonte, day(n.data), n.tema === "clima" ? "clima" : "cidade"].filter(Boolean).join(" · ")}</small></li>)}</ul></details>
        : <p className="libHint">Nenhuma notícia de chuva, alerta ou trânsito na região nos últimos 7 dias.</p>}
      {radar.avisos?.map((a) => <p key={a} className="libHint">{a}</p>)}
      <p className="libHint">Os alertas entram no plano da IA (riscos, checklist e plano B) quando você gera ou refaz.</p>
    </> : null}
  </section>;
}
