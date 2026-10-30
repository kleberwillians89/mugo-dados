import { useEffect, useState } from "react";
import { STUDIO_FORMATS, decidePublicApproval, getPublicApproval, localParts, type PublicApproval, type PublicApprovalItem } from "../app/studio";
import "../styles/studio.css";

/** Página pública: o cliente aprova ou pede ajuste nas pautas, sem login. O token do link é a credencial. */
export default function ClientApproval({ token }: { token: string }) {
  const [data, setData] = useState<PublicApproval | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [adjusting, setAdjusting] = useState<{ id: string; comment: string } | null>(null);
  const [name, setName] = useState("");

  useEffect(() => {
    getPublicApproval(token).then((d) => { setData(d); setName(d.contact_name || ""); }).catch((e) => setError(e instanceof Error ? e.message : "Link indisponível."));
  }, [token]);

  async function decide(item: PublicApprovalItem, action: "aprovado" | "ajuste_solicitado", comment?: string) {
    if (busy) return;
    setBusy(item.id); setError(null);
    try {
      await decidePublicApproval(token, item.id, { action, comment, reviewer_name: name || undefined });
      setData((d) => d && { ...d, items: d.items.map((i) => (i.id === item.id ? { ...i, decision: action, comment: comment || null } : i)) });
      setAdjusting(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Não foi possível registrar. Tente de novo."); }
    finally { setBusy(null); }
  }

  if (!data) return <main className="approvalPage"><h1>Aprovação de conteúdo</h1>{error ? <p role="alert" className="studioError">{error}</p> : <p>Carregando…</p>}</main>;

  const pending = data.items.filter((i) => !i.decision).length;
  return <main className="approvalPage">
    <p className="approvalBrand">Mugô · {data.client_name}</p>
    <h1>Pautas para sua aprovação</h1>
    <p>{pending ? `Faltam ${pending} de ${data.items.length}. Aprove ou peça ajuste em cada pauta.` : "Tudo respondido. Obrigado! A equipe Mugô já recebeu suas respostas."}</p>
    <label className="approvalName">Seu nome<input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} placeholder="Para a equipe saber quem aprovou" /></label>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    <div className="approvalList">{data.items.map((item) => {
      const when = localParts(item.scheduled_at);
      return <article key={item.id} className={`studioCard ${item.decision === "aprovado" ? "is-aprovado" : item.decision ? "is-rejeitado" : ""}`}>
        <header><div><strong className="studioDate">{when.weekday.charAt(0).toUpperCase() + when.weekday.slice(1)}, {when.label} · {when.time}</strong>
          <span className="studioChip">{STUDIO_FORMATS[item.format]}</span>{item.pillar ? <span className="studioChip is-pillar">{item.pillar}</span> : null}</div>
          {item.decision ? <span className={`studioStatus ${item.decision === "aprovado" ? "is-aprovado" : "is-rejeitado"}`}>{item.decision === "aprovado" ? "Aprovado" : "Ajuste pedido"}</span> : null}</header>
        <h3>{item.title}</h3>
        {item.hook ? <p className="studioHook">“{item.hook}”</p> : null}
        {item.caption_draft ? <p className="studioCaption">{item.caption_draft}</p> : null}
        {item.comment ? <p className="studioReview">Seu comentário: {item.comment}</p> : null}
        {adjusting?.id === item.id ? <form className="studioForm" onSubmit={(e) => { e.preventDefault(); void decide(item, "ajuste_solicitado", adjusting.comment); }}>
          <label>O que precisa mudar?<textarea rows={3} maxLength={1000} required value={adjusting.comment} onChange={(e) => setAdjusting({ id: item.id, comment: e.target.value })} /></label>
          <div className="studioActions"><button type="button" className="ds-button" onClick={() => setAdjusting(null)}>Cancelar</button><button className="ds-button is-primary" disabled={busy === item.id}>Enviar ajuste</button></div>
        </form> : <footer>
          <button className="is-approve" disabled={busy === item.id} onClick={() => void decide(item, "aprovado")}>{item.decision === "aprovado" ? "Aprovado ✓" : "Aprovar"}</button>
          <button disabled={busy === item.id} onClick={() => setAdjusting({ id: item.id, comment: item.comment || "" })}>Pedir ajuste</button>
        </footer>}
      </article>;
    })}</div>
    <p className="approvalFoot">Link válido até {new Date(data.expires_at).toLocaleDateString("pt-BR")}. Nada é publicado sem a sua aprovação.</p>
  </main>;
}
