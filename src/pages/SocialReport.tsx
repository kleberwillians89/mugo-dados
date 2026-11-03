import "@fontsource/open-sauce-one/400.css";
import "@fontsource/open-sauce-one/700.css";
import "@fontsource/open-sauce-one/800.css";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  buildSocialReport, capital, compact, contentsNote, draftReportInsights, getSocialReport, lastMonth, meaning, nonFollowerNote,
  pct, plus, postDate, saveReportInsights, shortCaption, viewsLine, watch, type ReportData, type ReportPost, type SocialReport as Report,
} from "../app/socialReport";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import "../styles/studio.css";
import "../styles/social-report.css";

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const W = 1440;

/** Slide 16:9 em 1440x810, reduzido para caber na tela; na impressão sai no tamanho real (1 página por slide). */
function Slide({ children, className = "" }: { children: ReactNode; className?: string }) {
  const outer = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  useLayoutEffect(() => {
    const el = outer.current;
    if (!el) return;
    const fit = () => setScale(Math.min(1, el.clientWidth / W) || 1);
    fit();
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(fit);
    ro?.observe(el);
    return () => ro?.disconnect();
  }, []);
  return <div className="srFrame" ref={outer} style={{ height: 810 * scale }}>
    <section className={`srSlide ${className}`} style={{ transform: `scale(${scale})` }}>{children}</section>
  </div>;
}

function Photo({ src, className }: { src?: string; className: string }) {
  return src ? <img className={`srPhoto ${className}`} src={src} alt="" referrerPolicy="no-referrer" /> : <div className={`srPhoto ${className} is-empty`} />;
}

const Icon = {
  heart: <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" />,
  comment: <path d="M20 11.5a8 8 0 0 1-11.8 7l-4.2 1.2 1.2-4A8 8 0 1 1 20 11.5z" />,
  repost: <><path d="M17 3l3 3-3 3" /><path d="M4 11V9a3 3 0 0 1 3-3h13" /><path d="M7 21l-3-3 3-3" /><path d="M20 13v2a3 3 0 0 1-3 3H4" /></>,
  send: <><path d="M21 3L10 14" /><path d="M21 3l-7 18-4-7-7-4z" /></>,
  save: <path d="M6 3h12v18l-6-5-6 5z" />,
};
const Svg = ({ name, size = 16 }: { name: keyof typeof Icon; size?: number }) =>
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>{Icon[name]}</svg>;

function Person({ woman }: { woman?: boolean }) {
  return <svg width="40" height="87" viewBox="0 0 34 74" aria-hidden><circle cx="17" cy="7" r="6.5" />
    {woman ? <path d="M11 16h12l7 24h-6v-6l3 13h-6v25h-4V48h-2v25h-4V47H5l3-13v6H4z" />
      : <path d="M7 16h20a4 4 0 0 1 4 4v20h-5V24h-1v49h-6V45h-2v28h-6V24H10v16H3V20a4 4 0 0 1 4-4z" />}</svg>;
}

const Month = ({ label, upper }: { label: string; upper?: boolean }) => <p className="srMonth">{upper ? label.toUpperCase() : capital(label)}</p>;

function Cover({ d, brand }: { d: ReportData; brand: string }) {
  return <Slide className="srCover">
    <Month label={d.month_label} />
    <h2 className="srCoverTitle">Social<br />Media<br />Report</h2>
    <p className="srCoverBrand">Mugô.Ag + {brand}</p>
  </Slide>;
}

function Overview({ d, photo }: { d: ReportData; photo?: string }) {
  const o = d.overview;
  return <Slide className="srOverview">
    <div className="srOverviewText">
      <h2 className="srTitle">Overview</h2>
      <div className="srStat"><strong className="is-gold">{plus(compact(o.views))}</strong><p>{viewsLine(o, d.prev_month_label)}</p></div>
      <div className="srStat"><strong>{o.non_follower_pct == null ? "—" : `+${pct(o.non_follower_pct)}`}</strong>
        <p><b>de visualização de não seguidores</b> {nonFollowerNote(o)}</p></div>
      <div className="srStat"><strong>{plus(compact(o.new_followers))}</strong><p><b>novos seguidores</b></p></div>
      <div className="srStat"><strong>{plus(compact(o.contents_total))}</strong><p><b>Conteúdos compartilhados</b> {contentsNote(o)}</p></div>
      <p className="srPlain">{o.profile_views == null ? "Visitas ao perfil: sem dado da Meta" : `${compact(o.profile_views)} visitas ao perfil`}<br />
        {o.link_taps == null ? "Toques no link da Bio: sem dado da Meta" : `${compact(o.link_taps)} toques no link da Bio - indo para o site`}</p>
    </div>
    <Photo src={photo} className="srOverviewPhoto" />
  </Slide>;
}

function Audience({ d, photo }: { d: ReportData; photo?: string }) {
  const a = d.audience;
  return <Slide className="srAudience">
    <Month label={d.month_label} upper />
    <h2 className="srTitle">Audiência &amp;<br />Comportamento</h2>
    <Photo src={photo} className="srAudiencePhoto" />
    <div className="srList srAges"><h3>Idade</h3>
      {a.ages.length ? <table><tbody>{a.ages.map((x) => <tr key={x.label}><td>{x.label}</td><td>{pct(x.pct, 0)}</td></tr>)}</tbody></table> : <p>Sem dado da Meta</p>}</div>
    <div className="srList srCities"><h3>Localização</h3>
      {a.cities.length ? <table><tbody>{a.cities.map((x) => <tr key={x.label}><td>{x.label}</td><td>{pct(x.pct, 0)}</td></tr>)}</tbody></table> : <p>Sem dado da Meta</p>}</div>
    <div className="srGender"><h3>Gênero</h3>
      {a.gender ? <div className="srGenderRow"><figure><Person /><figcaption>Homens ({a.gender.homens}%)</figcaption></figure>
        <figure><Person woman /><figcaption>Mulheres ({a.gender.mulheres}%)</figcaption></figure></div> : <p>Sem dado da Meta</p>}</div>
    <div className="srActive"><h3>Os seguidores estão mais ativos</h3>
      {a.active.length ? a.active.map((s) => <p key={`${s.day}${s.hours}`}>&gt; {capital(s.day)} das {s.hours.replace("-", " as ")}</p>) : <p>Ainda sem histórico suficiente</p>}</div>
  </Slide>;
}

function Card({ label, value, small }: { label: string; value: string; small?: boolean }) {
  return <div className={`srCard${small ? " is-small" : ""}`}><span>{label}</span><strong>{value}</strong></div>;
}

function Highlight({ d, images }: { d: ReportData; images: Record<string, string> }) {
  const h = d.highlight, p = d.prev_highlight;
  const kind = h?.format === "reels" ? "reel" : "post";
  const max = h ? Math.max(h.views, h.typical_views || 0, 1) : 1;
  return <Slide className="srHighlight">
    <Month label={d.month_label} upper />
    <h2 className="srTitle">Conteúdos<br />destaque:</h2>
    {p ? <div className="srPrev"><p>Post do mês anterior</p>
      <div className="srPrevCards"><Card small label="Visualizações" value={compact(p.views)} /><Card small label="Visualizadores" value={compact(p.reach)} />
        <Card small label="Tempo médio de vi…" value={watch(p.avg_watch_ms)} /><Card small label="Seguidores" value={compact(p.follows ?? null)} /></div>
      <Photo src={images[p.media_id]} className="srPrevThumb" /></div> : null}
    {h ? <>
      <div className="srSummary"><h3>Sumário <span aria-hidden>ⓘ</span></h3>
        <div className="srSummaryCards"><Card label="Visualizações" value={compact(h.views)} /><Card label="Visualizadores" value={compact(h.reach)} />
          <Card label="Tempo médio de vi…" value={watch(h.avg_watch_ms)} /><Card label="Seguidores" value={compact(h.follows ?? null)} /></div>
        <p className="srMeaning"><b>O que isso significa?</b> {meaning(h)}</p></div>
      <a className="srHero" href={h.permalink || undefined} target="_blank" rel="noreferrer"><Photo src={images[h.media_id]} className="srHeroImg" /></a>
      <div className="srIcons">
        <span><Svg name="heart" size={22} /><b>{compact(h.likes)}</b></span><span><Svg name="comment" size={22} /><b>{compact(h.comments)}</b></span>
        <span><Svg name="send" size={22} /><b>{compact(h.shares)}</b></span><span><Svg name="save" size={22} /><b>{compact(h.saved)}</b></span>
      </div>
      <div className="srChart">
        {[["Este " + kind, h.views, "is-this"], [`Seu ${kind} típico`, h.typical_views || 0, "is-typical"]].map(([label, value, cls]) =>
          <div key={String(cls)} className={`srBar ${cls}`}><span className="srBarTrack"><i style={{ width: `${(Number(value) / max) * 100}%` }} /></span>
            <span className="srBarValue">{compact(Number(value))}</span><span className="srBarLabel">● {label}</span></div>)}
        <p>Visualizações no mês</p>
      </div>
    </> : <p className="srEmpty">Sem posts com visualizações neste mês.</p>}
  </Slide>;
}

function TopRow({ post, metric, label, image }: { post: ReportPost; metric: number; label: string; image?: string }) {
  return <li className="srTopRow">
    <Photo src={image} className="srTopThumb" />
    <div className="srTopMain"><p><b>{shortCaption(post.caption)}</b> <span>{postDate(post.timestamp)}</span></p>
      <p className="srTopIcons">
        {label !== "Curtidas" ? <span><Svg name="heart" size={12} />{compact(post.likes)}</span> : null}
        <span><Svg name="comment" size={12} />{compact(post.comments)}</span><span><Svg name="send" size={12} />{compact(post.shares)}</span>
        <span><Svg name="save" size={12} />{compact(post.saved)}</span></p></div>
    <div className="srTopValue"><strong>{compact(metric)}</strong><span>{label}</span></div>
  </li>;
}

function Top({ d, images }: { d: ReportData; images: Record<string, string> }) {
  const cols: [string, ReportPost[], (p: ReportPost) => number, string][] = [
    ["Top 5 em curtida", d.top.likes, (p) => p.likes, "Curtidas"],
    ["Top 5 em visualização", d.top.views, (p) => p.views, "Visualizações"],
    ["Converteram seguidores:", d.top.follows, (p) => p.follows || 0, "Seguidores"],
  ];
  return <Slide className="srTop">
    <Month label={d.month_label} upper />
    <h2 className="srTitle">Conteúdos<br />destaque:</h2>
    {cols.map(([title, posts, metric, label], i) => <div key={title} className={`srTopCol is-${i}`}><h3>{title}</h3>
      {posts.length ? <ul>{posts.map((p) => <TopRow key={p.media_id} post={p} metric={metric(p)} label={label} image={images[p.media_id]} />)}</ul>
        : <p className="srEmpty">{i === 2 ? "A Meta não informou seguidores por post neste mês." : "Sem posts no mês."}</p>}</div>)}
  </Slide>;
}

function Insights({ items }: { items: string[] }) {
  return <Slide className="srInsights">
    <h2 className="srTitle">Insights até<br />aqui:</h2>
    <div className="srInsightList">{items.length ? items.map((t, i) => <p key={i}>&gt; {t}</p>) : <p className="srEmpty">Escreva ou gere os insights do mês.</p>}</div>
  </Slide>;
}

/** Os 6 slides do modelo (também usados na prévia e no PDF). */
export function ReportDeck({ d, images, brand, insights }: { d: ReportData; images: Record<string, string>; brand: string; insights: string[] }) {
  const heroImg = d.highlight ? images[d.highlight.media_id] : undefined;
  const second = [...d.top.views, ...d.top.likes].find((p) => p.media_id !== d.highlight?.media_id && images[p.media_id]);
  return <div className="srDeck">
    <Cover d={d} brand={brand} />
    <Overview d={d} photo={heroImg} />
    <Audience d={d} photo={second ? images[second.media_id] : heroImg} />
    <Highlight d={d} images={images} />
    <Top d={d} images={images} />
    <Insights items={insights} />
  </div>;
}

/**
 * Relatório social do mês no modelo da Mugô (6 slides). A equipe gera os números (Meta + posts sincronizados),
 * revisa os insights (rascunho da IA) e baixa o PDF. O cliente vê o relatório pronto.
 */
export default function SocialReport({ isAgency = false }: { isAgency?: boolean }) {
  const clientId = getActiveClientId();
  const brand = getActiveClientName() || "Marca";
  const [month, setMonth] = useState(lastMonth());
  const [report, setReport] = useState<Report | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const apply = useCallback((r: Report) => { setReport(r); setText(r.built ? r.insights.join("\n") : ""); }, []);
  const load = useCallback(async () => {
    setError(null); setReport(null);
    try { const r = await getSocialReport(month); if (getActiveClientId() === clientId) apply(r); }
    catch (cause) { setError(message(cause, "Não foi possível carregar o relatório.")); }
  }, [month, clientId, apply]);
  useEffect(() => { void load(); }, [load]);

  async function run<T>(key: string, fn: () => Promise<T>, fallback: string): Promise<T | null> {
    setBusy(key); setError(null); setNotice(null);
    try { return await fn(); } catch (cause) { setError(message(cause, fallback)); return null; } finally { setBusy(null); }
  }
  const lines = text.split("\n").map((l) => l.replace(/^\s*>\s*/, "").trim()).filter(Boolean);
  const build = async () => { const r = await run("build", () => buildSocialReport(month), "Não foi possível buscar os números agora."); if (r) { apply(r); setNotice("Números atualizados com a Meta."); } };
  const draft = async () => { const r = await run("draft", () => draftReportInsights(month), "A IA não respondeu agora."); if (r) { setText(r.insights.join("\n")); setNotice("Rascunho da IA pronto: revise e salve."); } };
  const save = async () => { const r = await run("save", () => saveReportInsights(month, lines), "Não foi possível salvar os insights."); if (r) { setText(r.insights.join("\n")); setNotice("Insights salvos."); } };

  const built = report?.built ? report : null;
  const d = built ? built.data : null;
  const images = built ? built.images : {};

  return <Shell title="Relatório social" variant="editorial"><div className="ds-page studioPage srPage">
    <PageHeader company={brand} title="Relatório social" controls={<div className="studioControls">
      <label className="srMonthPick">Mês<input type="month" value={month} max={new Date().toISOString().slice(0, 7)} onChange={(e) => e.target.value && setMonth(e.target.value)} /></label>
      {isAgency ? <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void build()}>{busy === "build" ? "Buscando na Meta… (até 2 min)" : d ? "Atualizar números" : "Gerar relatório"}</button> : null}
      <button type="button" className="ds-button is-primary" disabled={!d} onClick={() => window.print()}>Baixar PDF</button>
    </div>} />
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {notice ? <p className="studioNotice" role="status">{notice}</p> : null}
    {!report ? <p className="libHint">Carregando…</p> : !d ? <p className="libHint">{isAgency ? "O relatório deste mês ainda não foi gerado. Clique em \"Gerar relatório\": os números vêm da Meta e dos posts sincronizados." : "O relatório deste mês ainda não está pronto."}</p> : <>
      {isAgency ? <details className="srEditor" open={!built?.insights.length}><summary>Insights do mês ({lines.length})</summary>
        <p className="libHint">Um insight por linha. A IA sugere a partir dos números; a equipe revisa antes de salvar. O cliente vê só o que foi salvo.</p>
        <textarea rows={6} value={text} maxLength={2400} onChange={(e) => setText(e.target.value)} placeholder="O formato podcast tem performado bem…" />
        <div className="studioActions">
          <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void draft()}>{busy === "draft" ? "Escrevendo…" : "Rascunho da IA"}</button>
          <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => void save()}>{busy === "save" ? "Salvando…" : "Salvar insights"}</button>
        </div></details> : null}
      <ReportDeck d={d} images={images} brand={brand} insights={isAgency ? lines : built?.insights || []} />
      <p className="libHint srFoot">Números de {new Date(d.built_at).toLocaleString("pt-BR")}. Métrica que a Meta não devolve aparece como "—" ou "sem dado": nada é estimado.</p>
    </>}
  </div></Shell>;
}
