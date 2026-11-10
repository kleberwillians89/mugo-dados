import { useCallback, useEffect, useState, type FormEvent } from "react";
import RepliedPosts from "../components/studio/RepliedPosts";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  deleteRule, getInbox, listRules, refreshInbox, runRules, saveEngagementSettings, saveReplyTone, saveRule, sendReply, suggestReply,
  type EngagementRule, type EngagementSettings, type RuleStats, type InboxComment, type LastAiRun, type RuleInput,
} from "../app/engagement";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import Drawer from "../components/Drawer";
import { TRIGGER_TEMPLATES, type TriggerTemplate } from "../components/studio/triggerTemplates";
import "../styles/studio.css";

type Tab = "caixa" | "respondidos" | "gatilhos";
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const KIND: Record<string, string> = { resposta_publica: "Resposta automática", direct: "Direct", resposta_manual: "Resposta da equipe",
  resposta_ia: "Resposta da IA", revisao: "IA pediu revisão da equipe" };
const hasLinkPlaceholder = (rule: { dm_message?: string | null; public_reply?: string | null }) =>
  /\{LINK\}/i.test(`${rule.dm_message || ""} ${rule.public_reply || ""}`);
/** "{https://…}" → "https://…": as chaves iriam junto no Direct e quebram o link. */
const unwrapLinks = (text: string) => text.replace(/\{\s*(https?:\/\/[^\s{}]+)\s*\}/gi, "$1");
const hasWrappedLink = (text?: string | null) => /\{\s*https?:\/\//i.test(text || "");
/** Palavras comuns demais: o gatilho dispararia em quase todo comentário ("eu amei", "que lindo"). */
const BROAD_WORDS = new Set(["eu", "e", "a", "o", "que", "de", "sim", "amei", "lindo", "linda", "top"]);
const broadKeywords = (keywords: string[]) =>
  keywords.filter((k) => BROAD_WORDS.has(k.trim().toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "")));
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
function statsLine(s: RuleStats | undefined): string {
  if (!s || !s.comments) return "Ainda não disparou.";
  const parts = [`Disparou para ${plural(s.comments, "pessoa", "pessoas")}`, `Direct: ${s.direct_sent} enviado${s.direct_sent === 1 ? "" : "s"}`];
  if (s.direct_simulated) parts.push(`${s.direct_simulated} em modo teste`);
  if (s.direct_failed) parts.push(`${s.direct_failed} falh${s.direct_failed === 1 ? "ou" : "aram"}`);
  return `${parts.join(" · ")}${s.last_at ? ` · último em ${when(s.last_at)}` : ""}`;
}
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
  const [stats, setStats] = useState<Record<string, RuleStats>>({});
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
    try { const data = await listRules(); if (getActiveClientId() === clientId) { setRules(data.rules); setStats(data.stats || {}); setLive(data.autoreply_enabled); } }
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
      public_reply: unwrapLinks(editing.public_reply?.trim() || "") || null, dm_message: unwrapLinks(editing.dm_message?.trim() || "") || null, ai_greeting: Boolean(editing.ai_greeting), active: editing.active };
    const ok = await run("rule", () => saveRule(input, editing.id), "Não foi possível salvar o gatilho.");
    if (ok) { setEditing(null); await loadRules(); }
  }

  function applyTemplate(template: TriggerTemplate) {
    setEditing({ ...EMPTY_RULE, ...template.rule, keywordsText: template.rule.keywords.join(", ") });
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
      <details className="engHowTo" open={rules !== null && !rules.length}>
        <summary>Como o gatilho dispara</summary>
        <ol>
          <li>Escolha um modelo abaixo (ou <b>+ Gatilho</b>), troque o <code>{"{LINK}"}</code> pelo seu link e marque <b>Ligado</b>.</li>
          <li>No post ou na legenda, peça a palavra: <i>"Comenta QUERO que eu te mando o link"</i>. Para valer só em um post, cole o ID dele no gatilho.</li>
          <li>A cada 5 minutos o MUGOVERSO lê os comentários novos. Achou a palavra: responde no post e manda o Direct.</li>
          <li>Teste comentando de outra conta. O Instagram só deixa mandar Direct até 7 dias depois do comentário, uma vez por pessoa.</li>
        </ol>
        <p className="libHint"><b>"Acabou de seguir":</b> a Meta só libera o Direct automático para novo seguidor num beta exclusivo do ManyChat; a API aberta, que o MUGOVERSO usa, não avisa quem seguiu. Aqui o jeito é o modelo <b>Siga e comente</b>: a legenda pede para seguir e comentar, e o comentário dispara o oi com o link. Dá para usar o ManyChat só para o "seguiu → oi" junto com os gatilhos daqui (use palavras diferentes nos dois).</p>
      </details>
      {canManage ? <div className="engTemplates" aria-label="Modelos prontos">
        {TRIGGER_TEMPLATES.map((t) => <div key={t.id} className="engTemplate">
          <b>{t.title}</b>
          <p>{t.summary}</p>
          <p className="libHint">Na legenda: “{t.caption}”</p>
          <button type="button" className="ds-button" onClick={() => applyTemplate(t)}>Usar modelo</button>
        </div>)}
      </div> : null}
      {!rules ? <p>Carregando…</p> : !rules.length ? <div className="studioEmpty"><p>Nenhum gatilho ainda. Comece por um modelo acima.</p></div> : null}
      <ul className="engList">{(rules || []).map((r) => <li key={r.id} className="engItem">
        <div className="engRuleHead"><b>{r.name}</b><span className={`studioChip${r.active ? " is-on" : ""}`}>{r.active ? "Ligado" : "Desligado"}</span></div>
        <p className="engRuleStats"><b>{statsLine(stats[r.id])}</b></p>
        <p>Palavras: {r.keywords.join(", ")}{r.media_id ? ` · só no post ${r.media_id}` : " · todos os posts"}</p>
        {broadKeywords(r.keywords).length ? <p className="clipWarn">“{broadKeywords(r.keywords).join("”, “")}” é comum demais: o gatilho dispara em quase todo comentário (ex.: “eu amei”). Edite e deixe só a palavra da legenda.</p> : null}
        {hasWrappedLink(r.dm_message) || hasWrappedLink(r.public_reply) ? <p className="clipWarn">O link está entre chaves {"{ }"} e vai assim no Direct. Clique em Editar e salve de novo: o MUGOVERSO tira as chaves.</p> : null}
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
        {broadKeywords(editing.keywordsText.split(/[,\n]/)).length ? <p className="clipWarn" role="status">“{broadKeywords(editing.keywordsText.split(/[,\n]/)).join("”, “")}” é comum demais e dispara em quase todo comentário. Use só a palavra que a legenda pede.</p> : null}
        {hasLinkPlaceholder(editing) ? <p className="clipWarn" role="status">Troque <code>{"{LINK}"}</code> pelo link de verdade antes de salvar.</p> : null}
        <label className="studioCheck"><input type="checkbox" checked={editing.active} onChange={(e) => setEditing({ ...editing, active: e.target.checked })} /> Ligado</label>
        <div className="studioActions"><button type="button" className="ds-button" onClick={() => setEditing(null)}>Cancelar</button>
          <button className="ds-button is-primary" disabled={Boolean(busy) || hasLinkPlaceholder(editing)}>{busy === "rule" ? "Salvando…" : "Salvar"}</button></div>
      </form> : null}
    </Drawer>
  </div></Shell>;
}
