import { useEffect, useState } from "react";
import { Sparkles, X } from "lucide-react";
import { dismissNotice, listNotices, remindClient, type MugoNotice, type NoticeAction } from "../../app/notices";
import type { AppRoute } from "../../app/routes";
import "../../styles/mugo-noticed.css";

type Props = {
  /** Abre a tela do alerta na empresa dele (troca a empresa se precisar). */
  onOpen: (clientId: string, route: AppRoute) => void;
  /** Início: até 3. Minhas Tarefas: todos. */
  limit?: number;
  showCompany?: boolean;
};

/** "A Mugô IA notou": os alertas mais urgentes, cada um com o botão do que fazer. Sem nada relevante, não aparece. */
export default function MugoNoticed({ onOpen, limit = 3, showCompany = true }: Props) {
  const [notices, setNotices] = useState<MugoNotice[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ id: string; text: string; error?: boolean } | null>(null);

  useEffect(() => {
    let alive = true;
    listNotices(limit).then((r) => { if (alive) setNotices(r.notices); }).catch(() => { if (alive) setNotices([]); });
    return () => { alive = false; };
  }, [limit]);

  async function dismiss(n: MugoNotice) {
    setBusy(n.id);
    try {
      await dismissNotice(n.id);
      setNotices((list) => (list || []).filter((x) => x.id !== n.id));
    } catch { setFeedback({ id: n.id, text: "Não foi possível dispensar agora.", error: true }); } finally { setBusy(null); }
  }

  async function act(n: MugoNotice, a: NoticeAction) {
    if (a.kind === "remind" && a.request_id) {
      if (!window.confirm(`Enviar o lembrete de aprovação por WhatsApp para o contato de ${n.client_name}?`)) return;
      setBusy(n.id); setFeedback(null);
      try {
        await remindClient(n.client_id, a.request_id, a.contact_id);
        setFeedback({ id: n.id, text: "Lembrete enviado ao cliente pelo WhatsApp." });
      } catch (cause) {
        setFeedback({ id: n.id, text: cause instanceof Error && cause.message ? cause.message : "Não foi possível enviar o lembrete.", error: true });
      } finally { setBusy(null); }
      return;
    }
    if (a.route) onOpen(n.client_id, a.route);
  }

  if (!notices || !notices.length) return null;
  return <section className="mugoNoticed" aria-labelledby="mugo-noticed-title">
    <h2 id="mugo-noticed-title"><Sparkles size={16} aria-hidden="true" />A Mugô IA notou</h2>
    <ul>
      {notices.map((n) => <li key={n.id} className="mugoNotice" data-kind={n.kind}>
        <span className="mugoNoticeIcon" aria-hidden="true">{n.icon}</span>
        <div className="mugoNoticeBody">
          {showCompany ? <small className="mugoNoticeCompany">{n.client_name}</small> : null}
          <p>{n.message}</p>
          <div className="mugoNoticeActions">
            {n.actions.map((a) => <button key={a.label} type="button" className="ds-button" disabled={busy === n.id} onClick={() => void act(n, a)}>{a.label}</button>)}
            <button type="button" className="ds-link is-quiet" disabled={busy === n.id} onClick={() => void dismiss(n)}>Dispensar</button>
          </div>
          {feedback?.id === n.id ? <p className={feedback.error ? "mugoNoticeFeedback is-error" : "mugoNoticeFeedback"} role="status">{feedback.text}</p> : null}
        </div>
        <button type="button" className="mugoNoticeClose" aria-label="Dispensar" disabled={busy === n.id} onClick={() => void dismiss(n)}><X size={16} /></button>
      </li>)}
    </ul>
  </section>;
}
