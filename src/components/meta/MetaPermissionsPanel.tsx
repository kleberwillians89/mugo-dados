import { useEffect, useState } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { getMetaPermissions, type MetaPermissions } from "../../app/metaLive";
import "../../styles/metaLive.css";

const STATE: Record<string, { label: string; tone: string }> = {
  ok: { label: "Funcionando", tone: "ok" }, missing: { label: "Falta permissão", tone: "bad" },
  unknown: { label: "Reconecte para conferir", tone: "warn" }, not_connected: { label: "Não conectado", tone: "neu" },
};

/**
 * "Meta: o que está liberado": cada função do MUGOVERSO com a permissão que ela precisa. As permissões novas são pedidas
 * na Login Configuration do app na Meta (e aprovadas na revisão do app); depois, é só reconectar a Meta aqui.
 */
export default function MetaPermissionsPanel({ onReconnect }: { onReconnect?: () => void }) {
  const clientId = getActiveClientId();
  const [data, setData] = useState<MetaPermissions | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!clientId) return;
    let alive = true;
    getMetaPermissions().then((p) => { if (alive) setData(p); }).catch(() => { if (alive) setError(true); });
    return () => { alive = false; };
  }, [clientId]);
  if (error) return null;
  if (!data) return <p className="mlMuted" role="status">Conferindo as permissões da Meta…</p>;
  const missing = data.features.filter((f) => f.state === "missing" || f.state === "unknown");
  return <section className="metaLive mlPerms" aria-labelledby="meta-perms">
    <div className="mlRow mlSpread">
      <div><span className="mlLbl">Meta</span><h2 id="meta-perms">O que está liberado</h2>
        <p className="mlMuted">{missing.length ? `${missing.length} função(ões) ainda sem a permissão necessária.` : "Todas as funções do MUGOVERSO estão liberadas na Meta."}</p></div>
      {onReconnect && missing.length ? <button type="button" className="ds-button is-primary" onClick={onReconnect}>Reconectar a Meta</button> : null}
    </div>
    <div className="mlCamps">{data.features.map((f) => <article key={f.key} className="mlCard mlPerm">
      <span className={`mlChip is-${STATE[f.state].tone}`}>{STATE[f.state].label}</span>
      <h3>{f.label}</h3>
      <p className="mlMuted">{f.scopes.join(" · ")}</p>
      {f.state !== "ok" ? <p>{f.effect}</p> : null}
    </article>)}</div>
    <p className="mlMuted mlSmall">Permissão nova entra na Login Configuration do app na Meta e passa pela revisão do app. Depois disso, reconecte aqui.</p>
  </section>;
}
