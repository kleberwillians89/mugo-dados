import { useEffect, useState } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { getClientDataHealth } from "../../app/api";
import { getChannels } from "../../app/channels";
import { SOURCE_LABELS, type DataHealthSource } from "../../app/dataHealth";
import { getPathForRoute } from "../../app/routes";
import "../../styles/home.css";

type Pill = { key: string; label: string; tone: "ok" | "bad" | "wait" | "off" };
const TONE: Record<DataHealthSource["state"], Pill["tone"]> = {
  synced: "ok", updating: "wait", stale: "wait", attention: "bad", reauth_required: "bad", no_data: "off",
};
const TONE_TEXT: Record<Pill["tone"], string> = { ok: "coletando", bad: "precisa de atenção", wait: "atualizando ou aguardando", off: "sem dados / não conectado" };

/** Faixa "Seus canais" do Início: uma bolinha por fonte, com a cor do estado (mesma leitura da Saúde dos dados). */
export default function HomeChannels() {
  const clientId = getActiveClientId();
  const [pills, setPills] = useState<Pill[] | null>(null);
  useEffect(() => {
    let alive = true;
    const end = new Date(); const start = new Date(end.getTime() - 6 * 86_400_000);
    const iso = (d: Date) => d.toISOString().slice(0, 10);
    void Promise.allSettled([getClientDataHealth(clientId, { start: iso(start), end: iso(end) }), getChannels()]).then(([health, channels]) => {
      if (!alive) return;
      const out: Pill[] = [];
      if (health.status === "fulfilled") {
        for (const s of health.value.sources || []) {
          if (!s.connected) continue;
          out.push({ key: s.provider, label: SOURCE_LABELS[s.provider] || s.provider, tone: TONE[s.state] || "off" });
        }
      }
      if (channels.status === "fulfilled") {
        for (const c of channels.value.channels || []) {
          const tone: Pill["tone"] = c.status === "connected" ? "ok" : ["reauth_required", "sync_error", "token_expired"].includes(c.status) ? "bad" : !c.app_configured ? "wait" : "off";
          out.push({ key: c.provider, label: c.label, tone });
        }
      }
      setPills(out);
    });
    return () => { alive = false; };
  }, [clientId]);

  if (!pills || !pills.length) return null;
  return <section className="homeChannels" aria-label="Seus canais">
    <h2>Seus canais</h2>
    <ul>{pills.map((p) => <li key={p.key} className={`is-${p.tone}`} title={TONE_TEXT[p.tone]}><span aria-hidden="true" />{p.label}<span className="homeSr"> · {TONE_TEXT[p.tone]}</span></li>)}</ul>
    <a href={getPathForRoute("integrations")}>Ver integrações</a>
  </section>;
}
