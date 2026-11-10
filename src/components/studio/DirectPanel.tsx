import { useCallback, useEffect, useState, type FormEvent } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { getDirect, saveDirectSettings, type DirectOverview, type DirectSettings } from "../../app/engagement";

const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const STATUS: Record<string, string> = {
  respondido: "Respondido", simulado: "Respondido (modo teste)", revisao: "IA pediu a equipe", falhou: "Falhou",
  pendente: "Na fila", processando: "Respondendo…", equipe_respondendo: "Equipe respondendo", nao_segue: "Não segue (sem oi)",
  desligado: "Automação desligada", fora_da_janela_24h: "Passou de 24 h", ignorado: "Sem resposta automática",
};
const SUBSCRIBE_ERRORS: Record<string, string> = {
  IG_PERMISSION_MISSING: "Falta permissão no login do Meta (instagram_manage_messages e pages_manage_metadata): reconecte o Instagram em Integrações.",
  IG_PAGE_NOT_FOUND: "Não achei a página do Facebook ligada a este Instagram: reconecte em Integrações.",
  IG_NOT_CONNECTED: "Instagram não conectado: conecte em Integrações.",
};

/** Comentários > Direct: oi no primeiro Direct e IA respondendo o Direct, sem ManyChat. */
export default function DirectPanel() {
  const clientId = getActiveClientId();
  const [data, setData] = useState<DirectOverview | null>(null);
  const [draft, setDraft] = useState<DirectSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const out = await getDirect();
      if (getActiveClientId() !== clientId) return;
      setData(out);
      setDraft(out.settings);
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível carregar o Direct.");
    }
  }, [clientId]);
  useEffect(() => { void load(); }, [load]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      const out = await saveDirectSettings({ ...draft, welcome_content: draft.welcome_content || "" });
      setDraft(out.settings);
      if (out.subscribed && out.subscribed !== "ok") setError(SUBSCRIBE_ERRORS[out.subscribed] || "Salvo, mas não consegui ligar o Direct desta página no app do Meta.");
      else setNotice("Salvo.");
      await load();
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível salvar.");
    } finally {
      setBusy(false);
    }
  }

  if (!data || !draft) return <>{error ? <p className="clipWarn" role="alert">{error}</p> : <p>Carregando…</p>}</>;
  const c = data.counts;
  return <div className="directPanel">
    <p className="libHint">O Instagram não avisa quem acabou de seguir. O oi sai quando a pessoa manda a primeira mensagem no Direct da marca; com “só para quem segue”, o MUGOVERSO confere se ela segue o perfil e agradece por seguir.</p>
    {!data.autoreply_enabled ? <p className="clipWarn">Direct em <b>modo teste</b>: as respostas ficam registradas como “modo teste” e nada é enviado até liberar o envio (<code>IG_AUTOREPLY_ENABLED=true</code>).</p> : null}
    {error ? <p className="clipWarn" role="alert">{error}</p> : null}
    {notice ? <p className="libHint" role="status">{notice}</p> : null}

    <form className="studioForm directForm" onSubmit={submit}>
      <label className="studioCheck"><input type="checkbox" checked={draft.welcome_enabled} onChange={(e) => setDraft({ ...draft, welcome_enabled: e.target.checked })} /> <b>Oi no primeiro Direct</b> (no tom da marca, feito pela IA)</label>
      <label className="studioCheck"><input type="checkbox" checked={draft.welcome_followers_only} disabled={!draft.welcome_enabled} onChange={(e) => setDraft({ ...draft, welcome_followers_only: e.target.checked })} /> Só para quem segue o perfil (agradece por seguir)</label>
      <label>O que o oi precisa levar (link, cupom; opcional)<textarea rows={3} maxLength={1000} value={draft.welcome_content || ""} disabled={!draft.welcome_enabled} placeholder="Entra no nosso grupo de splits: https://chat.whatsapp.com/…" onChange={(e) => setDraft({ ...draft, welcome_content: e.target.value })} /></label>
      <label className="studioCheck"><input type="checkbox" checked={draft.ai_enabled} onChange={(e) => setDraft({ ...draft, ai_enabled: e.target.checked })} /> <b>IA responde o Direct</b> (perguntas sobre produto, preço, frete; reclamação e pedido ficam para a equipe)</label>
      <p className="libHint">Se a equipe responder pelo app do Instagram, a IA para naquela conversa por 12 horas.</p>
      <div className="studioActions"><button className="ds-button is-primary" disabled={busy}>{busy ? "Salvando…" : "Salvar"}</button></div>
    </form>

    <p className="engRuleStats"><b>Últimos 30 dias:</b> {c.conversations} conversas · {c.oi} oi enviados · {c.ia} respostas da IA · {c.review} para a equipe · {c.followers} seguidores</p>
    {!data.threads.length ? <div className="studioEmpty"><p>Nenhuma mensagem no Direct ainda. Elas aparecem aqui assim que o webhook do Instagram estiver ligado.</p></div> : null}
    <ul className="engList">{data.threads.map((t) => <li key={t.sender_id} className="engItem">
      <div className="engRuleHead"><b>{t.username ? `@${t.username}` : "Pessoa sem @"}</b>
        <span className={`studioChip${t.status === "respondido" ? " is-on" : ""}`}>{STATUS[t.status || ""] || t.status || "—"}</span></div>
      <p className="libHint">{t.follows ? "Segue o perfil" : t.follows === false ? "Não segue" : "Seguir: não sei"} · {when(t.last_at)}</p>
      {[...t.messages].reverse().map((m, i) => <p key={i}><small>{m.direction === "in" ? "Pessoa" : m.by_app ? "MUGOVERSO" : "Equipe"}:</small> {m.text || "—"}</p>)}
    </li>)}</ul>
  </div>;
}
