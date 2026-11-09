import { useCallback, useEffect, useState, type FormEvent } from "react";
import RepliedPosts from "../components/studio/RepliedPosts";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  deleteRule, getInbox, listRules, refreshInbox, runRules, saveEngagementSettings, saveReplyTone, saveRule, sendReply, suggestReply,
  type EngagementRule, type EngagementSettings, type InboxComment, type LastAiRun, type RuleInput,
} from "../app/engagement";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import Drawer from "../components/Drawer";
import "../styles/studio.css";

type Tab = "caixa" | "respondidos" | "gatilhos";
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const KIND: Record<string, string> = { resposta_publica: "Resposta automática", direct: "Direct", resposta_manual: "Resposta da equipe",
  resposta_ia: "Resposta da IA", revisao: "IA pediu revisão da equipe" };
const EMPTY_RULE: RuleInput = { name: "", keywords: [], media_id: null, public_reply: "Te mandei no Direct, {nome}! 💌", dm_message: "", ai_greeting: false, active: false };

/**
 * Comentários do Instagram: a IA responde sozinha no tom da marca (pode desligar), gatilhos por palavra-chave
 * (comentou → recebe no Direct) e resposta manual. Cliente vê a caixa da própria marca; gatilhos: equipe Mugô e admin da empresa.
 */
export default function Engagement({ isAgency = true, canManage = true }: { isAgency?: boolean; canManage?: boolean }) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "empresa";
  const [tab, setTab] = useState<Tab>("caixa");
  const [openOnly, setOpenOnly] = useState(true);
  const [items, setItems] = useState<InboxComment[] | null>(null);
  const [rules, setRules] = useState<EngagementRule[] | null>(null);
  const [live, setLive] = useState(false);
  const [settings, setSettings] = useState<EngagementSettings | null>(null);
  const [lastRun, setLastRun] = useState<LastAiRun | null>(null);
  const [toneDraft, setToneDraft] = useState<string | null>(null);
  const [can, setCan] = useState<{ reply: boolean; direct: boolean } | null>(null);
  const [drafts, setDrafts] = useState<Record<string, { text: string; direct: boolean; hint?: string }>>({});
  const [editing, setEditing] = useState<(RuleInput & { id?: string; keywordsText: string }) | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function run<T>(key: string, fn: () => Promise<T>, fallback: string): Promise<T | null> {
    setBusy(key); setError(null); setNotice(null);
    try { return await fn(); } catch (cause) { setError(message(cause, fallback)); return null; } finally { setBusy(null); }
  }

  const loadInbox = useCallback(async () => {
    try {
      const data = await getInbox(openOnly);
      if (getActiveClientId() !== clientId) return;
      setItems(data.items); setLive(data.autoreply_enabled); setSettings(data.settings || null); setLastRun(data.last_ai_run || null);
    } catch (cause) { setError(message(cause, "Não foi possível carregar os comentários.")); }
  }, [openOnly, clientId]);
  const loadRules = useCallback(async () => {
    try { const data = await listRules(); if (getActiveClientId() === clientId) { setRules(data.rules); setLive(data.autoreply_enabled); } }
    catch (cause) { setError(message(cause, "Não foi possível carregar os gatilhos.")); }
  }, [clientId]);
  useEffect(() => { if (tab === "caixa") void loadInbox(); else if (tab === "gatilhos") void loadRules(); }, [tab, loadInbox, loadRules]);

  async function refresh() {
    const out = await run("refresh", refreshInbox, "Não foi possível buscar os comentários no Instagram.");
    if (out) { setCan(out.can); setNotice(`${out.comments} comentário(s) lidos dos posts recentes.`); await loadInbox(); }
  }

  async function suggest(c: InboxComment) {
    const out = await run(`s:${c.comment_id}`, () => suggestReply(c.comment_id), "A IA não respondeu agora.");
    if (out) setDrafts((d) => ({ ...d, [c.comment_id]: { text: out.reply, direct: d[c.comment_id]?.direct || false,
      hint: [out.needs_human ? `Atenção: ${out.reason || "melhor a equipe responder com cuidado."}` : "", ...out.guard.map((g) => g.fix)].filter(Boolean).join(" ") } }));
  }

  async function send(c: InboxComment) {
    const draft = drafts[c.comment_id];
    if (!draft?.text.trim()) return;
    const out = await run(`r:${c.comment_id}`, () => sendReply(c.comment_id, draft.text.trim(), draft.direct), "Não foi possível enviar.");
    if (out) {
      setNotice(draft.direct ? "Direct enviado." : "Resposta publicada no comentário.");
      setDrafts((d) => { const next = { ...d }; delete next[c.comment_id]; return next; });
      await loadInbox();
    }
  }

  async function submitRule(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    const keywords = editing.keywordsText.split(/[,\n]/).map((k) => k.trim()).filter(Boolean).slice(0, 20);
    const input: RuleInput = { name: editing.name, keywords, media_id: editing.media_id?.trim() || null,
      public_reply: editing.public_reply?.trim() || null, dm_message: editing.dm_message?.trim() || null, ai_greeting: Boolean(editing.ai_greeting), active: editing.active };
    const ok = await run("rule", () => saveRule(input, editing.id), "Não foi possível salvar o gatilho.");
    if (ok) { setEditing(null); await loadRules(); }
  }

  async function toggle(rule: EngagementRule) {
    // Só os campos do gatilho: a linha do banco traz client_id/created_at, que o backend recusa.
    const { id, name, keywords, media_id, public_reply, dm_message, ai_greeting } = rule;
    const input: RuleInput = { name, keywords, media_id, public_reply, dm_message, ai_greeting: Boolean(ai_greeting), active: !rule.active };
    const ok = await run(`t:${id}`, () => saveRule(input, id), "Não foi possível alterar.");
    if (ok) await loadRules();
  }

  async function remove(rule: EngagementRule) {
    const ok = await run(`d:${rule.id}`, () => deleteRule(rule.id), "Não foi possível excluir.");
    if (ok) await loadRules();
  }

  async function runNow() {
    const out = await run("run", runRules, "Não foi possível rodar os gatilhos.");
    if (out) setNotice(out.live ? `${out.sent} envio(s) feitos agora${out.failed ? `, ${out.failed} falha(s)` : ""}.`
      : `Modo teste: ${out.simulated} resposta(s) simulada(s), nada foi enviado.`);
  }

  return <Shell title="Comentários" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={clientName} title="Comentários do Instagram" controls={<div className="studioControls">
      <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void refresh()}>{busy === "refresh" ? "Buscando…" : "Buscar agora"}</button>
      {canManage && tab === "gatilhos" ? <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => setEditing({ ...EMPTY_RULE, keywordsText: "" })}>+ Gatilho</button> : null}
    </div>} />
    {settings ? <div className="engageAi">
      <div><b>IA respondendo sozinha</b> <span className={settings.ai_autoreply ? "studioOk" : "libHint"}>{settings.ai_autoreply ? "ligada" : "desligada"}</span>
        <small>Todo dia às 16h, os comentários sem resposta dos últimos 3 dias recebem uma resposta curta no tom do perfil da marca (até 30 por dia): resposta aumenta o alcance. Reclamação, dado pessoal ou texto fora da marca não sai: vira "revisão" aqui para a equipe responder.</small>
        {settings.ai_autoreply && lastRun ? <p className={`engageLastRun is-${lastRun.status}`} role={lastRun.status === "error" ? "alert" : undefined}>
          <b>Última rodada · {new Date(lastRun.at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}:</b> {lastRun.summary}
        </p> : null}</div>
      {canManage ? <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={async () => {
        const out = await run("ai", () => saveEngagementSettings(!settings.ai_autoreply), "Não foi possível alterar.");
        if (out) setSettings(out);
      }}>{settings.ai_autoreply ? "Desligar IA" : "Ligar IA"}</button> : null}
    </div> : null}
    {settings && canManage ? <div className="engageTone">
      <label><b>Tom das respostas nos comentários</b>
        <small>Separado do tom das legendas. Vazio: a IA segue o jeito das legendas da marca. Ex.: "próximo e leve, como conversa; sem 'prezado' nem jargão; no máximo 1 emoji".</small>
        <textarea rows={2} maxLength={500} value={toneDraft ?? settings.reply_tone ?? ""} placeholder="Como a marca fala nos comentários"
          onChange={(e) => setToneDraft(e.target.value)} /></label>
      <button type="button" className="ds-button" disabled={Boolean(busy) || toneDraft === null || toneDraft === (settings.reply_tone ?? "")} onClick={async () => {
        const out = await run("tone", () => saveReplyTone(toneDraft ?? ""), "Não foi possível salvar o tom.");
        if (out) { setSettings(out); setToneDraft(null); setNotice("Tom salvo: as próximas respostas e sugestões da IA já usam."); }
      }}>{busy === "tone" ? "Salvando…" : "Salvar tom"}</button>
    </div> : null}
    <p className="libHint">Responda os comentários daqui (a IA sugere no tom da marca) e crie gatilhos: quem comenta a palavra-chave recebe uma resposta e uma mensagem no Direct. O Instagram só permite Direct até 7 dias depois do comentário, uma vez por pessoa.</p>
    {!live ? <p className="clipWarn">Gatilhos em <b>modo teste</b>: tudo fica registrado como "simulado" e nada é enviado{isAgency ? <> até ligar <code>IG_AUTOREPLY_ENABLED=true</code></> : " até a equipe Mugô liberar o envio"}. Respostas enviadas por aqui saem de verdade.</p> : null}
    {can && (!can.reply || !can.direct) ? <p className="clipWarn">Falta permissão no Meta para {[!can.reply ? "responder comentários" : "", !can.direct ? "enviar Direct" : ""].filter(Boolean).join(" e ")}. Reconecte o Instagram desta marca em Integrações.</p> : null}
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {notice ? <p className="studioOk">{notice}</p> : null}

    <div className="studioTabs" role="tablist" aria-label="Seção">
      {((canManage ? [["caixa", "Caixa"], ["respondidos", "Respondidos por post"], ["gatilhos", "Gatilhos"]] : [["caixa", "Caixa"], ["respondidos", "Respondidos por post"]]) as [Tab, string][]).map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "is-active" : ""} onClick={() => setTab(k)}>{l}</button>)}
    </div>

    {tab === "respondidos" ? <RepliedPosts /> : null}

    {tab === "caixa" ? <>
      <div className="studioTabs" role="tablist" aria-label="Filtro">
        {([[true, "Sem resposta"], [false, "Todos"]] as [boolean, string][]).map(([v, l]) => <button key={l} role="tab" aria-selected={openOnly === v} className={openOnly === v ? "is-active" : ""} onClick={() => setOpenOnly(v)}>{l}</button>)}
      </div>
      {!items ? <p>Carregando…</p> : !items.length ? <div className="studioEmpty"><p>Nenhum comentário {openOnly ? "sem resposta" : ""} nos últimos 30 dias. Clique em <b>Buscar agora</b> para ler os posts recentes.</p></div> : null}
      <ul className="engList">{(items || []).map((c) => {
        const draft = drafts[c.comment_id];
        return <li key={c.comment_id} className={`engItem${c.answered ? " is-done" : ""}`}>
          <div className="engMeta">
            {c.media?.thumb ? <img src={c.media.thumb} alt="" loading="lazy" /> : null}
            <div><b>@{c.username}</b> <small>{when(c.timestamp)}</small>
              {c.media?.permalink ? <> · <a href={c.media.permalink} target="_blank" rel="noreferrer noopener">ver post ↗</a></> : null}
              <p>{c.text}</p></div>
          </div>
          {c.actions.length ? <ul className="engActions">{c.actions.map((a, i) => <li key={i} className={`is-${a.status}`}>{KIND[a.kind]} · {a.status}: {a.text}</li>)}</ul> : null}
          {draft ? <div className="studioForm">
            <textarea rows={2} maxLength={draft.direct ? 1000 : 300} value={draft.text} onChange={(e) => setDrafts((d) => ({ ...d, [c.comment_id]: { ...draft, text: e.target.value } }))} />
            {draft.hint ? <p className="clipWarn">{draft.hint}</p> : null}
            <label className="studioCheck"><input type="checkbox" checked={draft.direct} disabled={!c.direct_open} onChange={(e) => setDrafts((d) => ({ ...d, [c.comment_id]: { ...draft, direct: e.target.checked } }))} />
              Enviar no Direct em vez de responder no post{!c.direct_open ? " (passou de 7 dias)" : ""}</label>
            <div className="studioActions">
              <button type="button" className="studioLink" onClick={() => setDrafts((d) => { const n = { ...d }; delete n[c.comment_id]; return n; })}>Cancelar</button>
              <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || !draft.text.trim()} onClick={() => void send(c)}>{busy === `r:${c.comment_id}` ? "Enviando…" : "Enviar"}</button>
            </div>
          </div> : <div className="studioActions">
            <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void suggest(c)}>{busy === `s:${c.comment_id}` ? "Pensando…" : "✦ Sugerir resposta"}</button>
            <button type="button" className="studioLink" onClick={() => setDrafts((d) => ({ ...d, [c.comment_id]: { text: "", direct: false } }))}>Responder</button>
          </div>}
        </li>;
      })}</ul>
    </> : <>
      <div className="studioActions"><button type="button" className="ds-button" disabled={Boolean(busy) || !rules?.some((r) => r.active)} onClick={() => void runNow()}>{busy === "run" ? "Rodando…" : "Rodar gatilhos agora"}</button>
        <span className="libHint">Rodam sozinhos a cada 5 minutos.</span></div>
      {!rules ? <p>Carregando…</p> : !rules.length ? <div className="studioEmpty"><p>Nenhum gatilho. Exemplo: quem comentar <b>QUERO</b> recebe o link no Direct.</p>
        <button type="button" className="ds-button is-primary" onClick={() => setEditing({ ...EMPTY_RULE, name: "Quero o link", keywordsText: "quero, link, eu quero" })}>Criar esse gatilho</button></div> : null}
      <ul className="engList">{(rules || []).map((r) => <li key={r.id} className="engItem">
        <div className="engRuleHead"><b>{r.name}</b><span className={`studioChip${r.active ? " is-on" : ""}`}>{r.active ? "Ligado" : "Desligado"}</span></div>
        <p>Palavras: {r.keywords.join(", ")}{r.media_id ? ` · só no post ${r.media_id}` : " · todos os posts"}</p>
        {r.public_reply ? <p><small>Resposta no post:</small> {r.public_reply}</p> : null}
        {r.ai_greeting ? <p><small>Direct:</small> ✦ oi feito pela IA no tom do perfil{r.dm_message ? <> + {r.dm_message}</> : null}</p>
          : r.dm_message ? <p><small>Direct:</small> {r.dm_message}</p> : null}
        <div className="studioActions">
          <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void toggle(r)}>{r.active ? "Desligar" : "Ligar"}</button>
          <button type="button" className="studioLink" onClick={() => setEditing({ ...r, keywordsText: r.keywords.join(", ") })}>Editar</button>
          <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => void remove(r)}>Excluir</button>
        </div>
      </li>)}</ul>
    </>}

    <Drawer open={Boolean(editing)} title={editing?.id ? "Editar gatilho" : "Novo gatilho"} description="Quem comentar uma das palavras recebe a resposta no post e/ou a mensagem no Direct. Use {nome} para chamar a pessoa pelo @." onClose={() => { if (!busy) setEditing(null); }}>
      {editing ? <form className="studioForm" onSubmit={submitRule}>
        <label>Nome<input required maxLength={80} value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} placeholder="Quero o link" /></label>
        <label>Palavras-chave (separadas por vírgula; maiúscula e acento não importam)<input required value={editing.keywordsText} onChange={(e) => setEditing({ ...editing, keywordsText: e.target.value })} placeholder="quero, link, preço" /></label>
        <label>Só neste post (ID do post; vazio = todos)<input value={editing.media_id || ""} pattern="[0-9]{5,40}" onChange={(e) => setEditing({ ...editing, media_id: e.target.value })} /></label>
        <label>Resposta no comentário (pública, curta)<textarea rows={2} maxLength={300} value={editing.public_reply || ""} onChange={(e) => setEditing({ ...editing, public_reply: e.target.value })} /></label>
        <label className="studioCheck"><input type="checkbox" checked={Boolean(editing.ai_greeting)} onChange={(e) => setEditing({ ...editing, ai_greeting: e.target.checked })} /> ✦ Oi feito pela IA no Direct (a IA escreve o oi no tom do perfil da marca, ligado ao comentário e ao post)</label>
        <label>{editing.ai_greeting ? "O que o Direct precisa levar (opcional: link, cupom; a IA escreve o oi em volta)" : "Mensagem no Direct"}<textarea rows={4} maxLength={1000} value={editing.dm_message || ""} onChange={(e) => setEditing({ ...editing, dm_message: e.target.value })} placeholder={editing.ai_greeting ? "https://…" : "Oi {nome}! Aqui está o link: https://…"} /></label>
        <label className="studioCheck"><input type="checkbox" checked={editing.active} onChange={(e) => setEditing({ ...editing, active: e.target.checked })} /> Ligado</label>
        <div className="studioActions"><button type="button" className="ds-button" onClick={() => setEditing(null)}>Cancelar</button>
          <button className="ds-button is-primary" disabled={Boolean(busy)}>{busy === "rule" ? "Salvando…" : "Salvar"}</button></div>
      </form> : null}
    </Drawer>
  </div></Shell>;
}
