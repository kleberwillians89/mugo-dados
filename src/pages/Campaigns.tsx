import { useCallback, useEffect, useState, type FormEvent } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  CHANNEL_LABEL, CHANNEL_ORDER, campaignToCalendar, createCampaign, editPiece, getCampaign, listCampaigns, pieceText,
  regeneratePiece, setCampaignStatus, type Briefing, type Campaign, type Channel, type LimitCheck, type Piece,
} from "../app/contentOps";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import BrandContextPanel from "../components/studio/BrandContextPanel";
import Drawer from "../components/Drawer";
import "../styles/studio.css";

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const emptyBriefing: Briefing = { name: "", objective: "", offer: "", audience: "", start: "", end: "", notes: "", channels: ["post", "reels", "stories", "meta_ads", "google_ads"] };
const FIELD_LABEL: Record<string, string> = {
  texto_principal: "Texto principal", titulo: "Título", descricao: "Descrição", cta: "CTA", angulo: "Ângulo", titulos: "Títulos",
  descricoes: "Descrições", legenda: "Legenda", ideia_visual: "Ideia visual", duracao_segundos: "Duração (s)", gancho: "Gancho",
  texto_capa: "Texto da capa", cenas: "Cenas", segundos: "Tempo", visual: "Visual", texto_tela: "Texto na tela", narracao: "Narração",
  quadro: "Quadro", texto: "Texto", acao: "Ação", mensagem: "Mensagem", assunto: "Assunto", preheader: "Pré-cabeçalho", corpo: "Corpo",
};
type Json = string | number | boolean | null | Json[] | { [k: string]: Json };

/** Editor estruturado de uma peça: cada texto vira um campo, com contador quando há limite. */
function Field({ value, path, limits, onChange }: { value: Json; path: (string | number)[]; limits: LimitCheck[]; onChange: (v: Json) => void }) {
  const key = String([...path].reverse().find((p) => typeof p === "string") ?? "");
  const index = typeof path[path.length - 1] === "number" ? (path[path.length - 1] as number) : typeof path[path.length - 2] === "number" ? (path[path.length - 2] as number) : null;
  if (Array.isArray(value)) {
    return <ol className="pieceList">{value.map((v, i) => <li key={i}><Field value={v} path={[...path, i]} limits={limits} onChange={(nv) => onChange(value.map((x, j) => (j === i ? nv : x)))} /></li>)}</ol>;
  }
  if (value && typeof value === "object") {
    return <div className="pieceObject">{Object.entries(value).map(([k, v]) => <div key={k} className="pieceField">
      {typeof v === "object" && v !== null ? <span className="pieceLabel">{FIELD_LABEL[k] || k}</span> : null}
      <Field value={v} path={[...path, k]} limits={limits} onChange={(nv) => onChange({ ...value, [k]: nv })} />
    </div>)}</div>;
  }
  const limit = limits.find((l) => l.field === key && (l.index === null || l.index === index));
  const text = value === null ? "" : String(value);
  const long = text.length > 90 || ["corpo", "legenda", "texto_principal", "mensagem", "narracao", "visual"].includes(key);
  return <label className="pieceInput">
    {key ? <span className="pieceLabel">{typeof path[path.length - 1] === "number" ? "" : FIELD_LABEL[key] || key}{limit ? <em className={text.length > limit.limit ? "is-over" : ""}>{text.length}/{limit.limit}</em> : null}</span> : null}
    {typeof value === "number" ? <input type="number" value={text} onChange={(e) => onChange(Number(e.target.value) || 0)} />
      : long ? <textarea rows={Math.min(8, Math.max(2, Math.ceil(text.length / 70)))} value={text} onChange={(e) => onChange(e.target.value)} />
        : <input value={text} onChange={(e) => onChange(e.target.value)} />}
  </label>;
}

function PieceCard({ campaignId, piece, busy, onSaved, run }: {
  campaignId: string; piece: Piece; busy: string | null;
  onSaved: (c: Campaign) => void; run: <T>(key: string, fn: () => Promise<T>, fallback: string) => Promise<T | null>;
}) {
  const [draft, setDraft] = useState<Json>(piece.content as Json);
  const [ask, setAsk] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const dirty = JSON.stringify(draft) !== JSON.stringify(piece.content);
  const over = piece.limits.filter((l) => l.over).length;
  async function copy() {
    try { await navigator.clipboard.writeText(pieceText(piece.channel, draft)); setCopied(true); window.setTimeout(() => setCopied(false), 2000); } catch { /* texto continua na tela */ }
  }
  return <section className="pieceCard" aria-label={CHANNEL_LABEL[piece.channel]}>
    <header><h3>{CHANNEL_LABEL[piece.channel]}{piece.edited ? <span className="studioChip">editado</span> : null}</h3>
      <div className="studioActions">
        <button type="button" className="ds-button" onClick={() => void copy()}>{copied ? "Copiado ✓" : "Copiar"}</button>
        <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => setAsk(ask === null ? "" : null)}>Regenerar</button>
      </div></header>
    {over ? <p className="studioError">{over} texto(s) acima do limite da plataforma. Ajuste antes de subir.</p> : null}
    {piece.flags.length ? <p className="clipWarn">Revise: {piece.flags.join(", ")}</p> : null}
    {ask !== null ? <div className="pieceAsk">
      <input placeholder="O que mudar? (opcional, ex.: mais direto, citar o frete grátis)" value={ask} maxLength={600} onChange={(e) => setAsk(e.target.value)} />
      <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => void run(`r:${piece.channel}`, () => regeneratePiece(campaignId, piece.channel, ask), "Não foi possível regenerar.").then((r) => { if (r) { onSaved(r.campaign); setAsk(null); } })}>
        {busy === `r:${piece.channel}` ? "Gerando…" : "Gerar outra versão"}</button>
    </div> : null}
    <Field value={draft} path={[]} limits={piece.limits} onChange={setDraft} />
    {dirty ? <div className="studioActions">
      <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => void run(`e:${piece.channel}`, () => editPiece(campaignId, piece.channel, draft), "Não foi possível salvar.").then((r) => r && onSaved(r.campaign))}>Salvar</button>
      <button type="button" className="ds-button" onClick={() => setDraft(piece.content as Json)}>Descartar</button>
    </div> : null}
  </section>;
}

/** Redação de campanha: briefing -> pacote de peças pela IA com os dados da marca. Só a equipe Mugô. */
export default function Campaigns() {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "empresa";
  const [list, setList] = useState<Campaign[]>([]);
  const [current, setCurrent] = useState<Campaign | null>(null);
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const data = await listCampaigns();
      if (getActiveClientId() !== clientId) return;
      setList(data.campaigns || []);
    } catch (cause) { setError(message(cause, "Não foi possível carregar as campanhas.")); }
    finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { void load(); }, [load]);

  const run = useCallback(async <T,>(key: string, fn: () => Promise<T>, fallback: string): Promise<T | null> => {
    setBusy(key); setError(null); setNotice(null);
    try { return await fn(); } catch (cause) { setError(message(cause, fallback)); return null; } finally { setBusy(null); }
  }, []);

  async function open(id: string) {
    const r = await run(`o:${id}`, () => getCampaign(id), "Não foi possível abrir a campanha.");
    if (r) setCurrent(r.campaign);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!briefing) return;
    const r = await run("generate", () => createCampaign(briefing), "Não foi possível gerar a campanha.");
    if (r) { setBriefing(null); setCurrent(r.campaign); await load(); }
  }

  async function toCalendar() {
    if (!current) return;
    const r = await run("calendar", () => campaignToCalendar(current.id), "Não foi possível mandar para o Calendário.");
    if (r) { setNotice(r.already ? "Esta campanha já está no Calendário." : `${r.created} pauta(s) criada(s) como rascunho no Calendário. Elas seguem a aprovação normal.`); setCurrent({ ...current, calendar_item_ids: r.calendar_item_ids }); }
  }

  const pieces = current?.package?.pieces || {};
  const toggle = (c: Channel) => briefing && setBriefing({ ...briefing, channels: briefing.channels.includes(c) ? briefing.channels.filter((x) => x !== c) : [...briefing.channels, c] });

  return <Shell title="Redação" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={clientName} title="Redação de campanha" controls={<div className="studioControls">
      {current ? <button type="button" className="ds-button" onClick={() => setCurrent(null)}>Campanhas</button> : null}
      <button type="button" className="ds-button is-primary" onClick={() => setBriefing({ ...emptyBriefing })} disabled={Boolean(busy)}>Nova campanha</button>
    </div>} />
    <BrandContextPanel clientId={getActiveClientId()} />
    <p className="libHint">A IA escreve com o Perfil de Marca e os dados reais da conta (o que alcançou, o que vendeu, Origem das vendas). Limites de caracteres conferidos pelo sistema. Só a equipe Mugô vê esta tela; posts, Reels e Stories vão para o Calendário e seguem a aprovação do cliente.</p>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {notice ? <p className="studioOk">{notice}</p> : null}
    {busy === "generate" ? <p className="studioOk">Escrevendo a campanha com os dados da marca… (até 2 minutos)</p> : null}

    {!current ? <>
      {loading ? <p>Carregando…</p> : null}
      {!loading && !list.length ? <div className="studioEmpty"><p>Nenhuma campanha ainda. Clique em <b>Nova campanha</b> (ex.: Black Friday).</p></div> : null}
      <ul className="campaignList">{list.map((c) => <li key={c.id}><button type="button" onClick={() => void open(c.id)} disabled={Boolean(busy)}>
        <b>{c.name}</b><small>{c.briefing?.objective}</small>
        <span className="studioChip">{c.status === "pronta" ? "Pronta" : "Rascunho"}</span>{c.calendar_item_ids?.length ? <span className="studioChip">no Calendário</span> : null}
      </button></li>)}</ul>
    </> : <>
      <section className="campaignConcept">
        <h2>{current.package?.concept?.nome || current.name}</h2>
        <p>{current.package?.concept?.ideia}</p>
        {current.package?.concept?.por_que ? <p className="libHint">Por que funciona: {current.package.concept.por_que}</p> : null}
        {current.package?.titles?.length ? <ul className="campaignTitles">{current.package.titles.map((t) => <li key={t}>{t}</li>)}</ul> : null}
        <div className="studioActions">
          <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || Boolean(current.calendar_item_ids?.length)} onClick={() => void toCalendar()}>{current.calendar_item_ids?.length ? "Já está no Calendário" : busy === "calendar" ? "Mandando…" : "Mandar pro Calendário"}</button>
          <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void run("status", () => setCampaignStatus(current.id, current.status === "pronta" ? "rascunho" : "pronta"), "Não foi possível atualizar.").then((r) => r && setCurrent(r.campaign))}>{current.status === "pronta" ? "Voltar para rascunho" : "Marcar como pronta"}</button>
          <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => { if (window.confirm("Arquivar esta campanha?")) void run("archive", () => setCampaignStatus(current.id, "arquivada"), "Não foi possível arquivar.").then((r) => { if (r) { setCurrent(null); void load(); } }); }}>Arquivar</button>
        </div>
      </section>
      {CHANNEL_ORDER.filter((c) => pieces[c]).map((c) => <PieceCard key={`${c}:${current.updated_at}`} campaignId={current.id} piece={pieces[c] as Piece} busy={busy} run={run} onSaved={setCurrent} />)}
    </>}

    <Drawer open={Boolean(briefing)} title="Nova campanha" description="Quanto mais concreto o briefing (oferta, prazo, público), melhor a campanha." width="lg" onClose={() => { if (busy !== "generate") setBriefing(null); }}>
      {briefing ? <form className="studioForm" onSubmit={submit}>
        <label>Nome<input required maxLength={160} value={briefing.name} onChange={(e) => setBriefing({ ...briefing, name: e.target.value })} placeholder="Black Friday 2026" /></label>
        <label>Objetivo<input required maxLength={400} value={briefing.objective} onChange={(e) => setBriefing({ ...briefing, objective: e.target.value })} placeholder="Vender o kit Oud na semana da Black Friday" /></label>
        <label>Oferta ou produto<textarea rows={2} maxLength={600} value={briefing.offer} onChange={(e) => setBriefing({ ...briefing, offer: e.target.value })} placeholder="20% no kit Oud + frete grátis acima de R$ 299 (só o que for real)" /></label>
        <label>Público<input maxLength={400} value={briefing.audience} onChange={(e) => setBriefing({ ...briefing, audience: e.target.value })} placeholder="Quem já comprou + quem visitou o site" /></label>
        <div className="studioRow">
          <label>Início<input type="date" value={briefing.start} onChange={(e) => setBriefing({ ...briefing, start: e.target.value })} /></label>
          <label>Fim<input type="date" value={briefing.end} onChange={(e) => setBriefing({ ...briefing, end: e.target.value })} /></label>
        </div>
        <fieldset><legend>Peças</legend>{CHANNEL_ORDER.map((c) => <label key={c} className="studioCheck"><input type="checkbox" checked={briefing.channels.includes(c)} onChange={() => toggle(c)} />{CHANNEL_LABEL[c]}</label>)}</fieldset>
        <label>Observações<textarea rows={3} maxLength={1000} value={briefing.notes} onChange={(e) => setBriefing({ ...briefing, notes: e.target.value })} placeholder="O que não pode faltar, o que evitar, referência…" /></label>
        <div className="studioActions"><button type="button" className="ds-button" disabled={busy === "generate"} onClick={() => setBriefing(null)}>Cancelar</button>
          <button className="ds-button is-primary" disabled={Boolean(busy) || !briefing.channels.length}>{busy === "generate" ? "Gerando… (até 2 min)" : "Gerar campanha"}</button></div>
      </form> : null}
    </Drawer>
  </div></Shell>;
}
