import { useCallback, useEffect, useState } from "react";
import { getActiveClientId } from "../../app/activeClient";
import {
  PILLAR_ORDER, getHealthIndex, healthTone, saveHealthWeights, weightShares,
  type HealthIndex, type PillarKey,
} from "../../app/brandHealth";
import "../../styles/brandHealth.css";
import HowToRead from "../data/HowToRead";

const nf = new Intl.NumberFormat("pt-BR");

function Gauge({ value }: { value: number | null }) {
  return <svg width="132" height="76" viewBox="0 0 96 56" aria-hidden="true">
    <path d="M8 50 A40 40 0 0 1 88 50" className="bhGaugeBg" />
    {value != null ? <path d="M8 50 A40 40 0 0 1 88 50" className={`bhGaugeFg is-${healthTone(value)}`} pathLength={100} strokeDasharray={`${value} 100`} /> : null}
  </svg>;
}

/** Editor de pesos: a pessoa escolhe quanto cada pilar pesa; peso 0 desliga o pilar. */
function WeightsEditor({ data, onSaved, onCancel }: { data: HealthIndex; onSaved: () => void; onCancel: () => void }) {
  const [draft, setDraft] = useState<Record<PillarKey, number>>({ ...data.weights });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const shares = weightShares(draft);
  const names = Object.fromEntries(data.pillars.map((p) => [p.key, p])) as Record<PillarKey, HealthIndex["pillars"][number]>;
  const allZero = PILLAR_ORDER.every((k) => !draft[k]);

  async function save() {
    setSaving(true); setError(null);
    try {
      await saveHealthWeights(draft);
      onSaved();
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível salvar os pesos.");
    } finally {
      setSaving(false);
    }
  }

  return <div className="hiEditor" role="group" aria-label="Pesos do índice">
    <p className="bhSub">Defina quanto cada pilar pesa na nota. O total vira 100% sozinho; peso 0 tira o pilar da conta.</p>
    {PILLAR_ORDER.map((k) => <label key={k} className="hiWeightRow">
      <span className="hiWeightName"><b>{names[k]?.name ?? k}</b><small>{names[k]?.hint}</small></span>
      <input type="range" min={0} max={100} step={5} value={draft[k]} aria-label={`Peso de ${names[k]?.name ?? k}`}
        onChange={(e) => setDraft((cur) => ({ ...cur, [k]: Number(e.target.value) }))} />
      <span className="hiWeightPct">{shares[k]}%</span>
    </label>)}
    {allZero ? <p className="clipWarn">Deixe pelo menos um pilar com peso.</p> : null}
    {error ? <p className="studioError" role="alert">{error}</p> : null}
    <div className="hiEditorActions">
      <button type="button" className="ds-button" onClick={() => setDraft({ ...data.default_weights })} disabled={saving}>Voltar ao padrão Mugô</button>
      <span className="hiSpacer" />
      <button type="button" className="ds-button" onClick={onCancel} disabled={saving}>Cancelar</button>
      <button type="button" className="ds-button is-primary" onClick={() => void save()} disabled={saving || allZero}>{saving ? "Salvando…" : "Salvar pesos"}</button>
    </div>
  </div>;
}

/** Índice de saúde MUGOVERSO: nota geral 0–100 + os 5 pilares que ligam conversa, atenção, mídia e vendas. */
export default function HealthIndexCard({ start, end }: { start: string; end: string }) {
  const clientId = getActiveClientId();
  const [nonce, setNonce] = useState(0);
  const key = `${clientId}|${start}|${end}|${nonce}`;
  const [state, setState] = useState<{ key: string; data: HealthIndex | null; error: string | null }>({ key: "", data: null, error: null });
  const [editing, setEditing] = useState(false);

  const load = useCallback(async (k: string) => {
    try {
      const data = await getHealthIndex({ start, end });
      if (getActiveClientId() === clientId) setState({ key: k, data, error: null });
    } catch (cause) {
      setState((prev) => ({ key: k, data: prev.data, error: cause instanceof Error && cause.message ? cause.message : "Não foi possível calcular o índice agora." }));
    }
  }, [clientId, start, end]);
  useEffect(() => { void load(key); }, [load, key]);

  const loading = state.key !== key;
  const d = state.data;
  if (!d) {
    return <section className="bhCard hiCard" aria-busy={loading}>
      <h2>Índice de saúde MUGOVERSO</h2>
      {state.error ? <p className="studioError" role="alert">{state.error}</p> : <p className="bhMuted" role="status">Calculando a nota com conversa, Instagram, mídia e vendas…</p>}
    </section>;
  }
  const off = d.pillars.filter((p) => p.score == null && p.weight > 0);

  return <section className={`bhCard hiCard${loading ? " is-loading" : ""}`} aria-labelledby="hi-title" aria-busy={loading}>
    <div className="hiHead">
      <div>
        <h2 id="hi-title">Índice de saúde MUGOVERSO</h2>
        <p className="bhSub">Uma nota que liga tudo: conversa, Instagram, mídia, reputação e vendas{d.custom_weights ? " · pesos personalizados" : " · pesos padrão Mugô"}</p>
      </div>
      {d.can_edit_weights && !editing ? <button type="button" className="ds-button" onClick={() => setEditing(true)}>Editar pesos</button> : null}
    </div>
    {state.error ? <p className="studioError" role="alert">{state.error}</p> : null}

    <div className="hiBody">
      <div className="hiScore">
        <Gauge value={d.index} />
        <div className="hiValue">{d.index ?? "—"}<small>/100</small></div>
        <div className={`hiLabel is-${healthTone(d.index)}`}>{d.label ?? "Sem dados suficientes"}</div>
        {d.coverage && d.coverage < 100 ? <small className="bhMuted">Calculado com {d.coverage}% dos pesos (pilares sem dado ficam de fora)</small> : null}
      </div>
      <ul className="hiPillars">
        {d.pillars.map((p) => <li key={p.key} className={p.weight === 0 ? "is-off" : ""}>
          <div className="hiPillarTop">
            <span className="hiPillarName" title={p.hint}>{p.name}</span>
            <span className="hiPillarWeight">{p.weight === 0 ? "desligado" : p.score == null ? "fora da conta" : `peso ${nf.format(p.effective_weight)}%`}</span>
            <b className="hiPillarScore">{p.score ?? "—"}</b>
          </div>
          <span className="hiBar"><i className={`is-${healthTone(p.score)}`} style={{ width: `${p.score ?? 0}%` }} /></span>
          <small className="bhMuted">{p.score == null ? p.reason : p.detail}</small>
        </li>)}
      </ul>
    </div>

    {editing ? <WeightsEditor data={d} onCancel={() => setEditing(false)} onSaved={() => { setEditing(false); setNonce((n) => n + 1); }} /> : null}
    <HowToRead title="Como ler a nota" intro="Vai de 0 a 100 e junta cinco sinais da marca."
      items={[
        { term: "Conversa", text: "O que as pessoas falam da marca: elogios contra reclamações." },
        { term: "Conversão", text: "Pedidos e faturamento comparados ao período anterior." },
        { term: "Atenção", text: "Quantas pessoas viram e interagiram no Instagram." },
        { term: "Presença", text: "Quanto se fala da marca perto dos concorrentes, nas notícias e no Instagram." },
        { term: "Reputação", text: "Se existe algum alerta aberto." },
      ]}
      note={<>Repetir os números do período anterior vale 60 pontos; cada 1% de crescimento soma quase 1 ponto.
        {off.length ? ` Ainda sem dado para calcular: ${off.map((p) => p.name.toLowerCase()).join(", ")}.` : ""}</>} />
  </section>;
}
