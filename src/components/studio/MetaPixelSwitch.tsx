import { useEffect, useState } from "react";
import { changeAdPixel, readAdPixels, type AdPixels } from "../../app/metaAds";

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const ago = (iso: string | null) => {
  if (!iso) return "nenhum evento recebido";
  const hours = (Date.now() - Date.parse(iso)) / 3_600_000;
  return hours < 1 ? "recebendo eventos agora" : hours < 48 ? `último evento há ${Math.round(hours)} h` : `último evento em ${new Date(iso).toLocaleDateString("pt-BR")}`;
};

/** Mostra e troca o conjunto de dados (pixel) de uma campanha já criada na Meta: conjunto de anúncios + anúncios. */
export default function MetaPixelSwitch({ draftId }: { draftId: string }) {
  const [data, setData] = useState<AdPixels | null>(null);
  const [pick, setPick] = useState("");
  const [busy, setBusy] = useState<"load" | "save" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    readAdPixels(draftId).then((d) => { if (alive) { setData(d); setPick(d.current && d.current !== d.recommended ? d.recommended || d.current : d.current || d.recommended || ""); } })
      .catch((cause) => { if (alive) setError(message(cause, "Não consegui ler os pixels da conta.")); })
      .finally(() => { if (alive) setBusy(null); });
    return () => { alive = false; };
  }, [draftId]);

  if (busy === "load") return <p className="ds-caption">Conferindo o pixel da campanha…</p>;
  if (!data) return error ? <p className="studioError" role="alert">{error}</p> : null;
  const current = data.pixels.find((p) => p.id === data.current);
  const wrong = Boolean(data.recommended && data.current && data.current !== data.recommended && !current?.active);

  async function save() {
    setBusy("save"); setError(null); setDone(null);
    try {
      const next = await changeAdPixel(draftId, pick);
      setData(next);
      const name = next.pixels.find((p) => p.id === pick)?.name || pick;
      setDone(next.ads_not_updated ? `Conjunto trocado para ${name}. ${next.ads_not_updated} anúncio(s) a Meta não deixou atualizar o rastreamento: ajuste no Gerenciador.` : `Pixel trocado para ${name} no conjunto e nos anúncios.`);
    } catch (cause) { setError(message(cause, "A Meta não deixou trocar o pixel agora.")); }
    finally { setBusy(null); }
  }

  return <div className={`metaPixel${wrong ? " is-wrong" : ""}`}>
    <div className="metaPixelHead">
      <b>Conjunto de dados (pixel)</b>
      <span>{current ? `${current.name} · ${ago(current.last_fired_time)}` : "Não identificado"}</span>
    </div>
    {wrong ? <p className="metaPixelWarn">Esta campanha está num pixel que não recebe eventos do site: a Meta não consegue otimizar por cadastros/compras. Troque para o recomendado.</p> : null}
    <div className="metaPixelRow">
      <label><span className="ds-srOnly">Escolher pixel</span>
        <select value={pick} disabled={busy === "save"} onChange={(e) => setPick(e.target.value)}>
          {data.pixels.filter((p) => !p.unavailable).map((p) => <option key={p.id} value={p.id}>
            {p.name}{p.id === data.recommended ? " (recomendado)" : ""} · {ago(p.last_fired_time)}</option>)}
        </select></label>
      <button type="button" className="ds-button" disabled={busy === "save" || !pick || pick === data.current} onClick={() => void save()}>
        {busy === "save" ? "Trocando…" : "Trocar pixel"}</button>
    </div>
    {done ? <p className="studioOk" role="status">{done}</p> : null}
    {error ? <p className="studioError" role="alert">{error}</p> : null}
  </div>;
}
