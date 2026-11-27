import { openAppRoute } from "../../app/routes";
import { requestWhatsAppArea } from "../../app/newProjectRequest";
import type { MugoIAAction as Action } from "../../app/studio";

/** Abrir: leva direto ao que foi criado (a campanha de e-mail aberta, os Modelos do WhatsApp…). */
export function openCreated(action: Action) {
  const done = action.criado;
  if (!done) return;
  if (action.tipo === "whatsapp_modelo") requestWhatsAppArea("models");
  openAppRoute(done.route, action.tipo === "email" && done.id ? `campanha=${encodeURIComponent(done.id)}` : undefined);
}
