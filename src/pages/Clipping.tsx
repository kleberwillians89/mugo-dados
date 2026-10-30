import { useCallback, useEffect, useState, type FormEvent } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  SENTIMENT_LABEL, clippingToCalendar, getClipping, refreshClipping, saveClippingSettings, setClippingStatus,
  type Clipping as Item, type ClippingView, type Sentiment,
} from "../app/contentOps";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import Drawer from "../components/Drawer";
import "../styles/studio.css";

type Kind = "" | "marca" | "concorrente";
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }) : "");
const toList = (text: string) => text.split(/[\n,]/).map((t) => t.trim()).filter(Boolean).slice(0, 6);

/** Clipping da marca e dos concorrentes (Google Notícias), com a leitura da IA. Só a equipe Mugô. */
export default function Clipping() {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "empresa";
  const [view, setView] = useState<ClippingView | null>(null);
  const [kind, setKind] = useState<Kind>("");
  const [sentiment, setSentiment] = useState<"" | Sentiment>("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ brand: string; competitors: string; exclude: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const data = await getClipping({ kind, sentiment });
      if (getActiveClientId() !== clientId) return;
      setView(data);
    } catch (cause) { setError(message(cause, "Não foi possível carregar o clipping.")); }
    finally { setLoading(false); }
  }, [kind, sentiment, clientId]);
  useEffect(() => { void load(); }, [load]);

  async function run<T>(key: string, fn: () => Promise<T>, fallback: string): Promise<T | null> {
    setBusy(key); setError(null); setNotice(null);
    try { return await fn(); } catch (cause) { setError(message(cause, fallback)); return null; } finally { setBusy(null); }
  }

  async function refresh() {
    const r = await run("refresh", refreshClipping, "Não foi possível buscar notícias agora.");
    if (r) { setNotice(r.new ? `${r.new} notícia(s) nova(s).` : "Nenhuma notícia nova desde a última busca."); await load(); }
  }

  async function saveSettings(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    const ok = await run("settings", () => saveClippingSettings({ brand_terms: toList(editing.brand), competitor_terms: toList(editing.competitors), exclude_terms: toList(editing.exclude), active: true }), "Não foi possível salvar os termos.");
    if (ok) { setEditing(null); await load(); }
  }

  async function mark(item: Item, status: "lido" | "arquivado") {
    const ok = await run(`s:${item.id}`, () => setClippingStatus(item.id, status), "Não foi possível atualizar.");
    if (ok) setView((v) => v && { ...v, items: status === "arquivado" ? v.items.filter((i) => i.id !== item.id) : v.items.map((i) => (i.id === item.id ? { ...i, status } : i)) });
  }

  async function toCalendar(item: Item) {
    const r = await run(`c:${item.id}`, () => clippingToCalendar(item.id), "Não foi possível criar a pauta.");
    if (r) { setNotice(r.already ? "Essa notícia já tinha virado pauta." : "Pauta criada como rascunho no Calendário."); setView((v) => v && { ...v, items: v.items.map((i) => (i.id === item.id ? { ...i, status: "pauta", calendar_item_id: r.calendar_item_id } : i)) }); }
  }

  const settings = view?.settings;
  const week = view?.week;
  const openSettings = () => setEditing({ brand: (settings?.brand_terms || []).join(", "), competitors: (settings?.competitor_terms || []).join(", "), exclude: (settings?.exclude_terms || []).join(", ") });

  return <Shell title="Clipping" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={clientName} title="Clipping da marca" controls={<div className="studioControls">
      <button type="button" className="ds-button" onClick={openSettings}>Termos</button>
      <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || !settings?.saved} onClick={() => void refresh()}>{busy === "refresh" ? "Buscando…" : "Atualizar agora"}</button>
    </div>} />
    <p className="libHint">Notícias do Google Notícias sobre a marca e os concorrentes, buscadas todo dia às 7h40. A IA lê só a manchete e a fonte. Só a equipe Mugô vê esta tela.{settings?.last_run_at ? ` Última busca: ${new Date(settings.last_run_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}.` : ""}</p>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {notice ? <p className="studioOk">{notice}</p> : null}

    {view && !settings?.saved ? <div className="studioEmpty">
      <p>Configure os termos para começar: o nome da marca, produtos e os concorrentes.</p>
      <button type="button" className="ds-button is-primary" onClick={openSettings}>Configurar termos</button>
    </div> : null}

    {week && settings?.saved ? <section className="clipWeek" aria-label="Resumo da semana">
      <div><b>{week.current.marca}</b><span>menções da marca em 7 dias</span><small className={week.marca_variacao > 0 ? "is-up" : week.marca_variacao < 0 ? "is-down" : ""}>{week.marca_variacao > 0 ? `+${week.marca_variacao}` : week.marca_variacao} vs. semana anterior</small></div>
      <div><b className="is-positivo">{week.current.positivo}</b><span>positivas</span></div>
      <div><b>{week.current.neutro}</b><span>neutras</span></div>
      <div><b className="is-negativo">{week.current.negativo}</b><span>negativas</span></div>
      <div><b>{week.current.concorrente}</b><span>dos concorrentes</span></div>
    </section> : null}

    {settings?.saved ? <div className="studioFilters">
      <div className="studioTabs" role="tablist" aria-label="Origem">
        {([["", "Todas"], ["marca", "Marca"], ["concorrente", "Concorrentes"]] as [Kind, string][]).map(([k, l]) => <button key={k || "all"} role="tab" aria-selected={kind === k} className={kind === k ? "is-active" : ""} onClick={() => setKind(k)}>{l}</button>)}
      </div>
      <div className="studioTabs" role="tablist" aria-label="Sentimento">
        {([["", "Qualquer"], ["positivo", "Positivas"], ["neutro", "Neutras"], ["negativo", "Negativas"]] as ["" | Sentiment, string][]).map(([k, l]) => <button key={k || "any"} role="tab" aria-selected={sentiment === k} className={sentiment === k ? "is-active" : ""} onClick={() => setSentiment(k)}>{l}</button>)}
      </div>
    </div> : null}

    {loading && !view ? <p>Carregando…</p> : null}
    {view && settings?.saved && !view.items.length ? <div className="studioEmpty"><p>Nenhuma notícia com esse filtro ainda. Clique em <b>Atualizar agora</b> para buscar.</p></div> : null}

    <ul className="clipList">{(view?.items || []).map((item) => <li key={item.id} className={`clipItem is-${item.sentiment || "sem"}${item.relevant === false ? " is-irrelevant" : ""}${item.status === "lido" ? " is-read" : ""}`}>
      <div className="clipMeta">
        <span className="studioChip">{item.kind === "marca" ? "Marca" : "Concorrente"} · {item.term}</span>
        {item.sentiment ? <span className={`studioChip clipSentiment is-${item.sentiment}`}>{SENTIMENT_LABEL[item.sentiment]}</span> : <span className="studioChip">Sem leitura da IA</span>}
        <small>{item.source || "Fonte"} · {when(item.published_at || item.created_at)}</small>
      </div>
      <a className="clipTitle" href={item.url} target="_blank" rel="noreferrer noopener">{item.title} ↗</a>
      {item.summary ? <p>{item.summary}</p> : null}
      {item.relevant === false ? <p className="clipWarn">A IA acha que não é sobre a marca (homônimo ou citação de passagem).</p> : null}
      <div className="studioActions">
        {item.status === "pauta" ? <span className="studioOk">Virou pauta no Calendário</span>
          : <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void toCalendar(item)}>{busy === `c:${item.id}` ? "Criando…" : "Virar pauta"}</button>}
        {item.status === "novo" ? <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => void mark(item, "lido")}>Marcar como lida</button> : null}
        <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => void mark(item, "arquivado")}>Arquivar</button>
      </div>
    </li>)}</ul>

    <Drawer open={Boolean(editing)} title="Termos do clipping" description="Até 6 termos em cada campo, separados por vírgula. Use o nome exato (ex.: Curavino, vinho natural Curavino)." onClose={() => { if (!busy) setEditing(null); }}>
      {editing ? <form className="studioForm" onSubmit={saveSettings}>
        <label>Marca, produtos e pessoas da marca<textarea rows={3} required value={editing.brand} onChange={(e) => setEditing({ ...editing, brand: e.target.value })} placeholder="Curavino, Curavino vinhos" /></label>
        <label>Concorrentes<textarea rows={3} value={editing.competitors} onChange={(e) => setEditing({ ...editing, competitors: e.target.value })} placeholder="Wine.com.br, Evino" /></label>
        <label>Ignorar notícias que tenham<textarea rows={2} value={editing.exclude} onChange={(e) => setEditing({ ...editing, exclude: e.target.value })} placeholder="sorteio, vaga de emprego" /></label>
        <div className="studioActions"><button type="button" className="ds-button" onClick={() => setEditing(null)}>Cancelar</button>
          <button className="ds-button is-primary" disabled={Boolean(busy)}>{busy === "settings" ? "Salvando…" : "Salvar"}</button></div>
      </form> : null}
    </Drawer>
  </div></Shell>;
}
