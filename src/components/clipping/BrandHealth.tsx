import { useCallback, useEffect, useState } from "react";
import { getActiveClientId } from "../../app/activeClient";
import {
  GRAIN_NAME, SENTIMENT_NAME, analyzeBrandHealth, SENTIMENT_ORDER, SOURCE_CHIP, SOURCE_NAME, bucketLabel, getBrandHealth, presetRange,
  type BrandHealth as Health, type Grain, type HealthSentiment, type Preset, type Source, type Split,
} from "../../app/brandHealth";
import DateRangePicker from "./DateRangePicker";
import HealthIndexCard from "./HealthIndexCard";
import WordCloud from "../WordCloud";
import "../../styles/brandHealth.css";
import PageSkeleton from "../data/PageSkeleton";
import SegmentedControl from "../data/SegmentedControl";

const GRAINS: Grain[] = ["day", "week", "month", "quarter", "year"];
const SOURCES: Source[] = ["news", "comments", "direct"];
const nf = new Intl.NumberFormat("pt-BR");
const pct = (v: number) => `${nf.format(Math.abs(v))}%`;
const signed = (v: number) => (v > 0 ? `+${v}` : String(v));

function Delta({ value, unit = "", goodWhenUp = true }: { value: number | null | undefined; unit?: string; goodWhenUp?: boolean }) {
  if (value == null || value === 0) return <span className="bhFlat">{value === 0 ? "= " : "— "}</span>;
  const good = value > 0 === goodWhenUp;
  return <span className={good ? "bhUp" : "bhDown"}>{value > 0 ? "▲" : "▼"} {nf.format(Math.abs(value))}{unit}</span>;
}

function StackBar({ split, width = 140 }: { split: Split; width?: number }) {
  const total = SENTIMENT_ORDER.reduce((s, k) => s + split[k], 0);
  if (!total) return <span className="bhMuted">sem análise</span>;
  return <span className="bhStack" style={{ width }} role="img"
    aria-label={SENTIMENT_ORDER.map((k) => `${SENTIMENT_NAME[k]} ${Math.round(split[k] / total * 100)}%`).join(", ")}>
    {SENTIMENT_ORDER.map((k) => split[k] ? <i key={k} className={`is-${k}`} style={{ flexGrow: split[k] }} /> : null)}
  </span>;
}

const W = 760, L = 44, R = 12, T = 12, B = 30;

function VolumeChart({ data }: { data: Health }) {
  const [hover, setHover] = useState<number | null>(null);
  const series = data.series;
  const max = Math.max(4, ...series.map((s) => s.total));
  const step = Math.pow(10, Math.floor(Math.log10(max))) * (max / Math.pow(10, Math.floor(Math.log10(max))) > 5 ? 2 : 1);
  const top = Math.ceil(max / step) * step, H = 240, plotH = H - T - B, bw = (W - L - R) / Math.max(series.length, 1);
  const y = (v: number) => T + plotH - (v / top) * plotH;
  const every = Math.ceil(series.length / 10);
  const h = hover != null ? series[hover] : null;
  return <div className="bhChart">
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Menções por período, separadas por sentimento" onMouseLeave={() => setHover(null)}>
      {Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step).map((v) => <g key={v}>
        <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="bhGridLine" />
        <text x={L - 8} y={y(v) + 4} className="bhAxis" textAnchor="end">{nf.format(v)}</text></g>)}
      {series.map((s, i) => {
        const x = L + i * bw + bw * 0.18, w = Math.max(bw * 0.64, 2);
        let acc = 0;
        const parts = [...SENTIMENT_ORDER, "sem_analise" as const].filter((k) => s[k]);
        return <g key={s.bucket}>
          {parts.map((k, j) => {
            const y1 = y(acc + s[k]), y0 = y(acc); acc += s[k];
            const last = j === parts.length - 1;
            return <rect key={k} x={x} y={y1 + (j ? 1 : 0)} width={w} height={Math.max(y0 - y1 - (j ? 1 : 0), 1)} rx={last ? Math.min(4, w / 2) : 0} className={`bhFill is-${k}`} />;
          })}
          {hover === i ? <rect x={x - 3} y={T - 2} width={w + 6} height={plotH + 4} rx={4} className="bhHoverBox" /> : null}
          {i % every === 0 ? <text x={x + w / 2} y={H - 10} className="bhAxis" textAnchor="middle">{bucketLabel(s.bucket, data.period.grain)}</text> : null}
          <rect x={L + i * bw} y={T} width={bw} height={plotH} fill="transparent" onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} tabIndex={0}
            aria-label={`${bucketLabel(s.bucket, data.period.grain, true)}: ${s.total} menções`} />
        </g>;
      })}
    </svg>
    {h ? <div className="bhTip" style={{ left: `${Math.min(78, ((L + (hover! + 0.5) * bw) / W) * 100)}%` }}>
      <b>{bucketLabel(h.bucket, data.period.grain, true)}</b>
      <span>{nf.format(h.total)} menções{h.net != null ? ` · líquido ${signed(h.net)}` : ""}</span>
      {SENTIMENT_ORDER.map((k) => <span key={k}><i className={`bhDot is-${k}`} />{SENTIMENT_NAME[k]} {nf.format(h[k])}</span>)}
      {h.sem_analise ? <span><i className="bhDot is-sem_analise" />Sem análise {nf.format(h.sem_analise)}</span> : null}
    </div> : null}
  </div>;
}

function NetChart({ data }: { data: Health }) {
  const [hover, setHover] = useState<number | null>(null);
  const series = data.series;
  const values = series.map((s) => s.net).filter((v): v is number => v != null);
  if (!values.length) return <p className="bhMuted">Ainda sem menções analisadas neste período.</p>;
  const lo = Math.max(-100, Math.min(-20, Math.floor((Math.min(...values) - 10) / 20) * 20));
  const hi = Math.min(100, Math.max(20, Math.ceil((Math.max(...values) + 10) / 20) * 20));
  const H = 200, plotH = H - T - B, bw = (W - L - R) / Math.max(series.length, 1);
  const y = (v: number) => T + plotH - ((v - lo) / (hi - lo)) * plotH;
  const pts = series.map((s, i) => (s.net == null ? null : [L + (i + 0.5) * bw, y(s.net)] as const));
  const path = pts.reduce((d, p, i) => (p ? `${d}${d && pts[i - 1] ? " L" : " M"}${p[0].toFixed(1)},${p[1].toFixed(1)}` : d), "");
  const every = Math.ceil(series.length / 10);
  const ticks = Array.from({ length: (hi - lo) / 20 + 1 }, (_, i) => lo + i * 20);
  const h = hover != null ? series[hover] : null;
  return <div className="bhChart">
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Sentimento líquido por período" onMouseLeave={() => setHover(null)}>
      {ticks.map((v) => <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className={v === 0 ? "bhZero" : "bhGridLine"} />
        <text x={L - 8} y={y(v) + 4} className="bhAxis" textAnchor="end">{signed(v)}</text></g>)}
      {hover != null ? <line x1={L + (hover + 0.5) * bw} x2={L + (hover + 0.5) * bw} y1={T} y2={T + plotH} className="bhCross" /> : null}
      <path d={path} className="bhLine" />
      {pts.map((p, i) => p ? <circle key={i} cx={p[0]} cy={p[1]} r={hover === i ? 5 : 4} className={series[i].net! < 0 ? "bhPoint is-neg" : "bhPoint"} /> : null)}
      {series.map((s, i) => <g key={s.bucket}>
        {i % every === 0 ? <text x={L + (i + 0.5) * bw} y={H - 10} className="bhAxis" textAnchor="middle">{bucketLabel(s.bucket, data.period.grain)}</text> : null}
        <rect x={L + i * bw} y={T} width={bw} height={plotH} fill="transparent" onMouseEnter={() => setHover(i)} />
      </g>)}
    </svg>
    {h ? <div className="bhTip" style={{ left: `${Math.min(78, ((L + (hover! + 0.5) * bw) / W) * 100)}%` }}>
      <b>{bucketLabel(h.bucket, data.period.grain, true)}</b>
      <span>{h.net == null ? "Sem menções analisadas" : `Sentimento líquido ${signed(h.net)}`}</span>
      <span>{nf.format(h.positivo)} positivas · {nf.format(h.negativo)} negativas</span>
    </div> : null}
  </div>;
}

function Donut({ split, net }: { split: Split; net: number | null }) {
  const total = SENTIMENT_ORDER.reduce((s, k) => s + split[k], 0);
  let a = -Math.PI / 2;
  const gap = total ? 0.03 : 0;
  const arcs = SENTIMENT_ORDER.filter((k) => split[k]).map((k) => {
    const b = a + (split[k] / total) * 2 * Math.PI, r = 70, ri = 48, e = Math.max(b - gap, a + 0.001), large = e - a > Math.PI ? 1 : 0;
    const d = `M${Math.cos(a) * r} ${Math.sin(a) * r} A${r} ${r} 0 ${large} 1 ${Math.cos(e) * r} ${Math.sin(e) * r} L${Math.cos(e) * ri} ${Math.sin(e) * ri} A${ri} ${ri} 0 ${large} 0 ${Math.cos(a) * ri} ${Math.sin(a) * ri}Z`;
    a = b;
    return <path key={k} d={d} className={`bhFill is-${k}`} />;
  });
  return <svg viewBox="0 0 260 170" className="bhDonut" role="img" aria-label="Divisão do sentimento no período">
    <g transform="translate(130,85)">{total ? arcs : <circle r={59} className="bhEmptyRing" />}</g>
    <text x="130" y="84" textAnchor="middle" className="bhDonutValue">{net == null ? "—" : signed(net)}</text>
    <text x="130" y="104" textAnchor="middle" className="bhAxis">líquido</text>
  </svg>;
}

const ALERT_KIND: Record<string, string> = { termo: "Termo", queda_indice: "Queda do índice", negativas: "Negativas no dia" };

/** Painel "Saúde da marca": filtros em uma linha, números do período, evolução, canais, assuntos e alertas. */
export default function BrandHealth({ canManage, onOpenAlerts }: { canManage: boolean; onOpenAlerts?: () => void }) {
  const clientId = getActiveClientId();
  const [grain, setGrain] = useState<Grain>("week");
  const [range, setRange] = useState<{ start: string; end: string; preset: Preset }>(() => ({ ...presetRange("3m"), preset: "3m" }));
  const [sources, setSources] = useState<Source[]>(SOURCES);
  const [result, setResult] = useState<{ key: string; data: Health | null; error: string | null }>({ key: "", data: null, error: null });

  const tooManyDays = grain === "day" && (new Date(range.end).getTime() - new Date(range.start).getTime()) / 864e5 > 400;
  const [nonce, setNonce] = useState(0);
  const requestKey = `${clientId}|${range.start}|${range.end}|${grain}|${sources.join(",")}|${nonce}`;
  const load = useCallback(async (key: string) => {
    try {
      const data = await getBrandHealth({ start: range.start, end: range.end, grain, sources });
      if (getActiveClientId() === clientId) setResult({ key, data, error: null });
    } catch (cause) {
      setResult((prev) => ({ key, data: prev.data, error: cause instanceof Error && cause.message ? cause.message : "Não foi possível carregar a saúde da marca." }));
    }
  }, [clientId, range.start, range.end, grain, sources]);
  useEffect(() => { if (!tooManyDays) void load(requestKey); }, [load, requestKey, tooManyDays]);
  const state = { data: result.data, error: result.key === requestKey ? result.error : null, loading: !tooManyDays && result.key !== requestKey };

  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeNote, setAnalyzeNote] = useState<string | null>(null);
  async function analyzeNow() {
    setAnalyzing(true); setAnalyzeNote(null);
    try {
      const out = await analyzeBrandHealth();
      const parts = [`${nf.format(out.classified)} comentários/Direct`, `${nf.format(out.news_analyzed)} matérias`];
      setAnalyzeNote(`Analisados agora: ${parts.join(" e ")}.${out.news_pending ? ` Faltam ${nf.format(out.news_pending)} matérias: clique de novo ou espere a rodada de hora em hora.` : ""}${out.failed ? " A IA não respondeu para parte deles; tenta de novo na próxima rodada." : ""}`);
      setNonce((n) => n + 1);
    } catch (cause) {
      setAnalyzeNote(cause instanceof Error && cause.message ? cause.message : "Não foi possível analisar agora.");
    } finally {
      setAnalyzing(false);
    }
  }
  const toggleSource = (s: Source) => setSources((cur) => (cur.includes(s) ? (cur.length > 1 ? cur.filter((x) => x !== s) : cur) : SOURCES.filter((x) => x === s || cur.includes(x))));
  const d = state.data, k = d?.kpis;
  const analyzed = d ? SENTIMENT_ORDER.reduce((s, key) => s + d.split[key], 0) : 0;

  return <div className="bhPage">
    <div className="bhFilters" role="group" aria-label="Período e canais">
      <span className="bhLabel">Ver por</span>
      <SegmentedControl ariaLabel="Agrupar por" value={grain} onSelect={(id) => setGrain(id as typeof grain)} options={GRAINS.map((g) => ({ id: g, label: GRAIN_NAME[g] }))} />
      <DateRangePicker value={range} onChange={setRange} />
      <span className="bhMuted">vs período anterior</span>
      <div className="bhChips">{SOURCES.map((s) => <button key={s} type="button" aria-pressed={sources.includes(s)} className={sources.includes(s) ? "is-on" : ""} onClick={() => toggleSource(s)}>{SOURCE_CHIP[s]}</button>)}</div>
    </div>
    {canManage && k && k.unanalyzed > 0 ? <div className="bhPending" role="status">
      <span><b>{nf.format(k.unanalyzed)}</b> menções ainda sem análise da IA (entram só no volume, não no sentimento).</span>
      <button type="button" className="ds-button is-primary" disabled={analyzing} onClick={() => void analyzeNow()}>{analyzing ? "Analisando… (até 2 min)" : "Analisar agora"}</button>
    </div> : null}
    {analyzeNote ? <p className="studioOk" role="status">{analyzeNote}</p> : null}
    {tooManyDays ? <p className="clipWarn">Por dia, escolha até 13 meses. Para períodos maiores, veja por semana ou mês.</p> : null}
    {state.error ? <p className="studioError" role="alert">{state.error}</p> : null}
    {state.loading && !d ? <PageSkeleton label="Carregando a saúde da marca…" /> : null}

    {!tooManyDays ? <HealthIndexCard start={range.start} end={range.end} /> : null}
    {d?.words?.length ? <section className={state.loading ? "bhCard bhWords is-loading" : "bhCard bhWords"} aria-labelledby="bh-words">
      <h2 id="bh-words">Palavras mais citadas</h2>
      <p className="bhSub">Notícias, comentários e Direct do período. Tamanho = quantas vezes aparece; cor = sentimento que predomina. Passe o mouse para ver a divisão.</p>
      <WordCloud words={d.words} />
    </section> : null}

    {d && k ? <div className={state.loading ? "bhBody is-loading" : "bhBody"} aria-busy={state.loading}>
      <div className="bhKpis">
        <div className="bhCard bhIndex">
          <div className="bhKl">Saúde da conversa</div>
          <div className="bhGauge">
            <svg width="96" height="56" viewBox="0 0 96 56" aria-hidden="true"><path d="M8 50 A40 40 0 0 1 88 50" className="bhGaugeBg" />
              {k.index != null ? <path d="M8 50 A40 40 0 0 1 88 50" className={`bhGaugeFg ${k.index >= 70 ? "is-positivo" : k.index >= 50 ? "is-misto" : "is-negativo"}`}
                pathLength={100} strokeDasharray={`${k.index} 100`} /> : null}</svg>
            <div><div className="bhKv">{k.index ?? "—"}<small>/100</small></div>
              <div className="bhKs">{k.index != null && k.index_previous != null ? <><Delta value={k.index - k.index_previous} /> vs anterior · </> : null}<b>{k.index_label || "Sem menções analisadas"}</b></div></div>
          </div>
        </div>
        <div className="bhCard"><div className="bhKl">Menções</div><div className="bhKv">{nf.format(k.mentions)}</div>
          <div className="bhKs">{k.mentions_change != null ? <><Delta value={k.mentions_change} unit="%" /> vs anterior</> : `anterior: ${nf.format(k.mentions_previous)}`}</div></div>
        <div className="bhCard"><div className="bhKl">Sentimento líquido</div><div className="bhKv">{k.net == null ? "—" : signed(k.net)}</div>
          <div className="bhKs">% positivas − % negativas{k.net != null && k.net_previous != null ? <> · <Delta value={k.net - k.net_previous} /></> : null}</div></div>
        <div className="bhCard"><div className="bhKl">Negativas</div><div className="bhKv">{nf.format(k.negative)}</div>
          <div className="bhKs">{k.negative_share != null ? `${pct(k.negative_share)} das analisadas` : "—"}
            {k.negative_share != null && k.negative_share_previous != null ? <> · <Delta value={Math.round((k.negative_share - k.negative_share_previous) * 10) / 10} unit=" p.p." goodWhenUp={false} /></> : null}</div></div>
        {canManage ? <button type="button" className="bhCard bhAlertKpi" onClick={onOpenAlerts}><div className="bhKl">Alertas abertos</div>
          <div className={`bhKv${k.alerts_open ? " is-alert" : ""}`}>{k.alerts_open ?? 0}</div>
          <div className="bhKs">{k.alerts_open ? `${k.alerts_high} alto · ${(k.alerts_open || 0) - (k.alerts_high || 0)} médio` : "nenhum agora"}</div></button>
          : <div className="bhCard"><div className="bhKl">Analisadas pela IA</div><div className="bhKv">{nf.format(analyzed)}</div><div className="bhKs">{nf.format(k.unanalyzed)} ainda sem análise</div></div>}
      </div>

      <div className="bhRow">
        <section className="bhCard" aria-labelledby="bh-vol">
          <h2 id="bh-vol">Evolução do volume de menções</h2>
          <p className="bhSub">Menções por {GRAIN_NAME[d.period.grain].toLowerCase()}, separadas por sentimento</p>
          <div className="bhLegend">{SENTIMENT_ORDER.map((s) => <span key={s}><i className={`bhDot is-${s}`} />{SENTIMENT_NAME[s]}</span>)}{k.unanalyzed ? <span><i className="bhDot is-sem_analise" />Sem análise</span> : null}</div>
          <VolumeChart data={d} />
        </section>
        <section className="bhCard" aria-labelledby="bh-split">
          <h2 id="bh-split">Sentimento do período</h2><p className="bhSub">{nf.format(analyzed)} menções analisadas</p>
          <Donut split={d.split} net={k.net} />
          <table className="bhTable"><tbody>{SENTIMENT_ORDER.map((s: HealthSentiment) => <tr key={s}>
            <td><i className={`bhDot is-${s}`} />{SENTIMENT_NAME[s]}</td><td><b>{nf.format(d.split[s])}</b></td>
            <td>{analyzed ? pct(Math.round(d.split[s] / analyzed * 1000) / 10) : "—"}</td></tr>)}</tbody></table>
        </section>
      </div>

      <div className="bhRow">
        <section className="bhCard" aria-labelledby="bh-net">
          <h2 id="bh-net">Evolução do sentimento</h2>
          <p className="bhSub">Sentimento líquido por {GRAIN_NAME[d.period.grain].toLowerCase()} (−100 a +100). Abaixo de 0 = mais negativas que positivas</p>
          <NetChart data={d} />
        </section>
        {canManage ? <section className="bhCard bhAlerts" aria-labelledby="bh-alerts">
          <h2 id="bh-alerts">Alertas de termos sensíveis</h2><p className="bhSub">Só a equipe Mugô vê e recebe no WhatsApp</p>
          {!d.alerts.length ? <p className="bhMuted">Nenhum alerta aberto.</p> : d.alerts.map((a) => <div key={a.id} className={`bhAlert is-${a.severity}`}>
            <div className="bhAlertHead"><b>{a.kind === "termo" ? `“${a.term}” — ${a.mentions} ${a.mentions === 1 ? "menção" : "menções"}` : ALERT_KIND[a.kind]}</b>
              <span className={`bhSev is-${a.severity}`}>{a.severity === "alto" ? "Alto" : "Médio"}</span></div>
            <small>{a.detail}{a.sources.length ? ` · ${a.sources.map((s) => SOURCE_CHIP[s]).join(", ")}` : ""}</small>
          </div>)}
          <button type="button" className="studioLink" onClick={onOpenAlerts}>Ver alertas e termos monitorados →</button>
        </section> : null}
      </div>

      <div className="bhRow is-half">
        <section className="bhCard" aria-labelledby="bh-ch">
          <h2 id="bh-ch">De onde vêm as menções</h2><p className="bhSub">Volume e sentimento por canal</p>
          <table className="bhTable"><thead><tr><th>Canal</th><th>Menções</th><th>Variação</th><th>Sentimento</th></tr></thead>
            <tbody>{d.channels.map((c) => <tr key={c.source}><td>{SOURCE_NAME[c.source]}</td><td><b>{nf.format(c.mentions)}</b></td>
              <td>{c.change != null ? <Delta value={Math.round(c.change)} unit="%" /> : <span className="bhMuted">novo</span>}</td><td><StackBar split={c.split} /></td></tr>)}</tbody></table>
        </section>
        <section className="bhCard" aria-labelledby="bh-th">
          <h2 id="bh-th">Assuntos que mais cresceram</h2><p className="bhSub">Temas citados nas menções, vs período anterior</p>
          {!d.themes.length ? <p className="bhMuted">Os assuntos aparecem quando a IA analisar as menções.</p> :
            <table className="bhTable"><thead><tr><th>Assunto</th><th>Menções</th><th>Variação</th><th>Tom</th></tr></thead>
              <tbody>{d.themes.map((t) => <tr key={t.theme}><td>{t.theme}</td><td><b>{nf.format(t.mentions)}</b></td>
                <td>{t.change != null ? <Delta value={Math.round(t.change)} unit="%" /> : <span className="bhMuted">novo</span>}</td>
                <td>{t.tone ? <span className={`bhTone is-${t.tone}`}>{SENTIMENT_NAME[t.tone].toLowerCase()}</span> : "—"}</td></tr>)}</tbody></table>}
        </section>
      </div>
      <p className="bhMuted bhFoot">Saúde da conversa = 80% sentimento líquido + 20% alertas abertos (é o pilar "Conversa" do índice MUGOVERSO). Comentários e Direct são analisados pela IA a cada hora; notícias, na busca diária do clipping.
        {k.unanalyzed ? ` ${nf.format(k.unanalyzed)} menções ainda sem análise contam só no volume.` : ""}</p>
    </div> : null}
  </div>;
}
