import { useCallback, useEffect, useMemo, useState } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { listAdAudiences, type AccountAudience, type AccountAudiences, type AdPayload, type AudienceRef } from "../../app/metaAds";
import MetaAudienceCreator from "./MetaAudienceCreator";

type Audience = AdPayload["audience"];
const ref = (a: AccountAudience): AudienceRef => ({ id: a.id, name: a.name });
// Lista lida da conta do Meta fica guardada por empresa enquanto a página estiver aberta.
const cache = new Map<string, AccountAudiences>();

/**
 * Públicos que já existem na conta de anúncios do cliente: escolhe um público salvo (substitui idade, locais e
 * interesses) e soma ou exclui públicos personalizados e semelhantes, em vez de escrever o público à mão.
 */
export default function MetaAudiencePicker({ audience, onChange, disabled }: {
  audience: Audience; onChange: (patch: Partial<Audience>) => void; disabled?: boolean;
}) {
  const clientId = getActiveClientId() || "";
  const [data, setData] = useState<AccountAudiences | null>(() => cache.get(clientId) || null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const load = useCallback(async (force = false) => {
    if (!force && cache.has(clientId)) { setData(cache.get(clientId)!); return; }
    setLoading(true); setError(null);
    try {
      const list = await listAdAudiences();
      if (getActiveClientId() !== clientId) return;
      cache.set(clientId, list); setData(list);
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível ler os públicos da conta de anúncios.");
    } finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { void load(); }, [load]);

  const included = useMemo(() => new Set((audience.custom_audiences || []).map((a) => a.id)), [audience.custom_audiences]);
  const excluded = useMemo(() => new Set((audience.excluded_audiences || []).map((a) => a.id)), [audience.excluded_audiences]);
  const foreignPicked = (data?.custom || []).filter((a) => a.foreign && (included.has(a.id) || excluded.has(a.id)));
  const custom = (data?.custom || []).filter((a) => !query.trim() || a.name.toLowerCase().includes(query.trim().toLowerCase()));

  function toggle(a: AccountAudience, side: "include" | "exclude", on: boolean) {
    const inc = (audience.custom_audiences || []).filter((x) => x.id !== a.id);
    const exc = (audience.excluded_audiences || []).filter((x) => x.id !== a.id);
    if (on && side === "include") inc.push(ref(a));
    if (on && side === "exclude") exc.push(ref(a));
    onChange({ custom_audiences: inc, excluded_audiences: exc });
  }

  return <section className="metaAudPicker" aria-labelledby="meta-aud-title">
    <div className="metaAudHead">
      <div><strong id="meta-aud-title">Públicos da conta de anúncios</strong>
        <p className="ds-caption">Os que já foram criados no Meta para esta marca. Escolha aqui em vez de escrever o público.</p></div>
      <button type="button" className="ds-button" disabled={disabled || loading} onClick={() => void load(true)}>{loading ? "Buscando…" : "Atualizar lista"}</button>
    </div>
    <MetaAudienceCreator sources={data?.custom || []} disabled={disabled} onCreated={(made) => {
      onChange({ custom_audiences: [...(audience.custom_audiences || []).filter((x) => x.id !== made.id), made] });
      void load(true);
    }} />
    {foreignPicked.length ? <p className="ds-caption metaAdsMissing" role="alert">
      {foreignPicked.map((a) => a.name).join(", ")}: criado com o perfil de outra conta (um parceiro, por exemplo). O Meta recusa esse público
      em anúncio da marca. Desmarque e, se precisar, crie um igual em "+ Criar público".</p> : null}
    {error ? <p className="ds-caption metaAdsMissing" role="alert">{error}</p> : null}
    {!data && loading ? <p className="ds-caption">Buscando os públicos no Meta…</p> : null}
    {data ? <>
      <label className="ds-field">Público salvo (opcional)
        <select value={audience.saved_audience?.id || ""} disabled={disabled}
          onChange={(e) => { const a = data.saved.find((x) => x.id === e.target.value); onChange({ saved_audience: a ? ref(a) : null }); }}>
          <option value="">Nenhum: usar idade, locais e interesses abaixo</option>
          {data.saved.map((a) => <option key={a.id} value={a.id}>{a.name} · {a.size}</option>)}
        </select>
      </label>
      {!data.saved.length ? <small className="ds-caption">Nenhum público salvo nesta conta.</small> : null}

      <div className="metaAudList">
        <div className="metaAudListHead">
          <span>Personalizados e semelhantes ({data.custom.length})</span>
          {data.custom.length > 6 ? <input type="search" value={query} placeholder="Buscar público" aria-label="Buscar público"
            onChange={(e) => setQuery(e.target.value)} /> : null}
        </div>
        {!data.custom.length ? <p className="ds-caption">Nenhum público personalizado nesta conta ainda.</p> : <ul>
          {custom.map((a) => <li key={a.id} className={!a.ready ? "is-off" : ""}>
            <div><b>{a.name}</b><small>{a.kind_label} · {a.size}{a.status ? ` · ${a.status}` : ""}</small></div>
            <label className="metaAdsCheck"><input type="checkbox" checked={included.has(a.id)} disabled={disabled || (!a.ready && !included.has(a.id))}
              onChange={(e) => toggle(a, "include", e.target.checked)} />Incluir</label>
            <label className="metaAdsCheck"><input type="checkbox" checked={excluded.has(a.id)} disabled={disabled || (a.foreign && !excluded.has(a.id))}
              onChange={(e) => toggle(a, "exclude", e.target.checked)} />Excluir</label>
          </li>)}
          {!custom.length ? <li><small>Nenhum público com esse nome.</small></li> : null}
        </ul>}
      </div>
    </> : null}
  </section>;
}
