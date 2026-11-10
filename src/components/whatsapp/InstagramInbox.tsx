import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { getInstagramInbox, getInstagramThread, replyInstagram, type IgInbox, type IgThread } from "../../app/whatsapp";

type Filter = "all" | "waiting" | "review" | "followers";
const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Todas" }, { key: "waiting", label: "Sem resposta" },
  { key: "review", label: "IA pediu a equipe" }, { key: "followers", label: "Seguidores" },
];

function when(iso: string) {
  const d = new Date(iso), now = new Date();
  if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}
const fullWhen = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const name = (username: string | null) => (username ? `@${username}` : "Pessoa sem @");
const error = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);

/** Direct do Instagram da marca: lista, conversa e resposta da equipe (a IA para 12 h na conversa respondida). */
export default function InstagramInbox() {
  const clientId = getActiveClientId();
  const [inbox, setInbox] = useState<{ data: IgInbox | null; error: string | null }>({ data: null, error: null });
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [thread, setThread] = useState<{ data: IgThread | null; loading: boolean; error: string | null }>({ data: null, loading: false, error: null });
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const opened = useRef<string | null>(null);

  const loadInbox = useCallback(async () => {
    try {
      const data = await getInstagramInbox();
      if (getActiveClientId() === clientId) setInbox({ data, error: null });
    } catch (cause) {
      setInbox({ data: null, error: error(cause, "Não foi possível carregar o Direct agora.") });
    }
  }, [clientId]);

  const openThread = useCallback(async (senderId: string) => {
    opened.current = senderId;
    setOpenId(senderId); setSendError(null); setDraft("");
    setThread((t) => ({ data: t.data?.sender_id === senderId ? t.data : null, loading: true, error: null }));
    try {
      const data = await getInstagramThread(senderId);
      if (opened.current === senderId) setThread({ data, loading: false, error: null });
    } catch (cause) {
      if (opened.current === senderId) setThread({ data: null, loading: false, error: error(cause, "Não foi possível abrir esta conversa.") });
    }
  }, []);

  useEffect(() => { void loadInbox(); }, [loadInbox]);

  const threads = useMemo(() => {
    const q = query.trim().toLowerCase().replace(/^@/, "");
    return (inbox.data?.threads || []).filter((t) =>
      (filter === "all" || (filter === "waiting" && t.waiting) || (filter === "review" && t.review) || (filter === "followers" && t.follows))
      && (!q || (t.username || "").toLowerCase().includes(q) || t.last_text.toLowerCase().includes(q)));
  }, [inbox.data, filter, query]);

  async function send(event: FormEvent) {
    event.preventDefault();
    if (!openId || !draft.trim()) return;
    setSending(true); setSendError(null);
    try {
      await replyInstagram(openId, draft.trim());
      setDraft("");
      await Promise.all([openThread(openId), loadInbox()]);
    } catch (cause) {
      setSendError(error(cause, "Não foi possível enviar agora."));
    } finally {
      setSending(false);
    }
  }

  const open = thread.data && thread.data.sender_id === openId ? thread.data : null;
  const c = inbox.data?.counts;
  return (
    <section className="waCard waInbox" aria-labelledby="ig-inbox">
      <div className="waInboxList">
        <div className="waInboxTools">
          <h2 id="ig-inbox">Direct do Instagram</h2>
          {c ? <p className="waMuted waSmall">{c.conversations} conversas · {c.waiting} sem resposta · {c.review} para a equipe (30 dias)</p> : null}
          <label className="waSearch">Buscar
            <input type="search" placeholder="@ ou texto da mensagem" value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <div className="waChips" role="group" aria-label="Filtrar conversas do Instagram">
            {FILTERS.map((item) => (
              <button key={item.key} type="button" className={filter === item.key ? "is-active" : ""} aria-pressed={filter === item.key}
                onClick={() => setFilter(item.key)}>{item.label}</button>
            ))}
          </div>
        </div>
        {inbox.error ? <p className="waMuted waPad" role="alert">{inbox.error}</p> : null}
        {!inbox.data && !inbox.error ? <p className="waMuted waPad" role="status">Carregando conversas…</p> : null}
        {inbox.data && !inbox.data.threads.length ? <p className="waMuted waPad">Nenhuma mensagem no Direct ainda. Elas aparecem aqui quando o webhook do Instagram estiver ligado (Comentários → Direct).</p> : null}
        {inbox.data?.threads.length && !threads.length ? <p className="waMuted waPad">Nenhuma conversa com esse filtro.</p> : null}
        <ul className="waConvList">
          {threads.map((t) => (
            <li key={t.sender_id} className={t.sender_id === openId ? "is-open" : ""}>
              <button type="button" onClick={() => void openThread(t.sender_id)} aria-current={t.sender_id === openId ? "true" : undefined}>
                <span className="waConvTop"><b>{name(t.username)}</b><small>{when(t.last_at)}</small></span>
                <span className="waConvPreview">{t.last_direction === "out" ? (t.last_by_app ? "IA: " : "Você: ") : ""}{t.last_text || "—"}</span>
                <span className="waTags">
                  {t.follows ? <span className="waTag is-bought">Segue</span> : null}
                  {t.review ? <span className="waTag is-waiting">IA pediu a equipe</span> : t.waiting ? <span className="waTag is-waiting">Aguardando resposta</span> : null}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="waThread">
        {openId ? (
          <>
            <header className="waThreadHead">
              <div><b>{name(open?.username ?? null)}</b><small>{open?.follows ? "Segue o perfil" : open?.follows === false ? "Não segue" : "Instagram Direct"}</small></div>
              {open ? <span className={open.window_open ? "waTag is-bought" : "waTag"}>{open.window_open ? "Janela de 24h aberta" : "Fora da janela de 24h"}</span> : null}
            </header>
            <ol className="waMessages">
              {thread.loading && !open ? <li className="waEvent is-plain">Carregando…</li> : null}
              {thread.error ? <li className="waEvent is-plain">{thread.error}</li> : null}
              {(open?.messages || []).map((m) => (
                <li key={m.id} className={`waBubble${m.direction === "out" ? " is-out" : ""}${m.status === "falhou" ? " is-failed" : ""}`}>
                  <p>{m.text || "—"}</p>
                  <small>{fullWhen(m.at)}
                    {m.direction === "out" ? (m.by_app ? (m.reply_kind === "oi" ? " · oi automático" : " · IA") : " · equipe") : ""}
                    {m.direction === "out" && m.status === "simulado" ? " · modo teste (não enviado)" : ""}
                    {m.direction === "in" && m.status === "revisao" ? ` · IA pediu a equipe${m.note ? `: ${m.note}` : ""}` : ""}
                  </small>
                </li>
              ))}
            </ol>
            {open ? (
              open.window_open ? (
                <form className="waComposer" onSubmit={send}>
                  <label className="waSrOnly" htmlFor="ig-reply">Responder no Direct</label>
                  <textarea id="ig-reply" rows={2} maxLength={1000} value={draft} placeholder="Responder no Direct…" onChange={(e) => setDraft(e.target.value)} />
                  <button type="submit" className="ds-button is-primary" disabled={sending || !draft.trim()}>{sending ? "Enviando…" : "Enviar"}</button>
                  {sendError ? <p className="waMuted waSmall" role="alert">{sendError}</p> : <p className="waMuted waSmall">Sai pelo Direct da marca. Respondendo aqui, a IA para nesta conversa por 12 horas.</p>}
                </form>
              ) : <p className="waMuted waPad">Passou de 24 h desde a última mensagem da pessoa: o Instagram só deixa responder pelo app.</p>
            ) : null}
          </>
        ) : <p className="waMuted waPad">Escolha uma conversa.</p>}
      </div>
    </section>
  );
}
