import { useEffect, useState } from "react";
import { listMessages, type ApprovalCreated, type MessageLog } from "../../app/studio";

const STEP: Record<string, string> = { accepted: "Enviado", sent: "Enviado", delivered: "Entregue", read: "Lido", failed: "Falhou" };

/**
 * Depois de "Enviar para o cliente aprovar": a mensagem exata que saiu (como balão do WhatsApp) e o status
 * de cada destinatário (cliente e equipe Mugô), atualizado a cada 5 s por 2 min. Entregue/lido dependem
 * do CRM repassar os status da Meta (/api/hooks/crm, message_status).
 */
export default function ApprovalDelivery({ sent }: { sent: ApprovalCreated }) {
  const [rows, setRows] = useState<MessageLog[]>([]);
  useEffect(() => {
    let alive = true, ticks = 0;
    const load = () => listMessages(sent.request_id).then((d) => { if (alive) setRows(d.messages || []); }).catch(() => undefined);
    void load();
    const timer = window.setInterval(() => { ticks += 1; if (ticks > 24) window.clearInterval(timer); else void load(); }, 5000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [sent.request_id]);
  const text = sent.whatsapp && "text" in sent.whatsapp ? sent.whatsapp.text : rows.find((r) => r.preview?.text)?.preview.text;
  if (!text && !rows.length) return null;
  return <div className="approvalDelivery">
    {text ? <div className="waBubble"><p>{text}</p><span className="waButton">Ver e aprovar</span></div> : null}
    {rows.length ? <ul aria-label="Quem recebeu">{rows.map((r) => {
      const step = r.status === "falhou" ? "Falhou" : r.delivery_status ? STEP[r.delivery_status] : r.status === "enviado" ? "Enviado" : r.status;
      return <li key={r.id}><span>{r.contact_name || "—"} <small>{r.phone_masked}</small></span>
        <b className={`waStep is-${(r.delivery_status || r.status || "").toLowerCase()}`}>{step}{r.error_code ? ` · ${r.error_code}` : ""}</b></li>;
    })}</ul> : null}
    <small className="libHint">Cliente e equipe recebem o mesmo link: todo mundo vê e comenta na mesma página de aprovação.</small>
  </div>;
}
