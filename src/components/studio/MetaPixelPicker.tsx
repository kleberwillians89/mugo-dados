import { useEffect, useState } from "react";
import { readAdPixels, type AdPixels } from "../../app/metaAds";

const when = (iso: string | null) => {
  if (!iso) return "nenhum evento recebido";
  const hours = (Date.now() - Date.parse(iso)) / 3_600_000;
  return hours < 1 ? "recebendo eventos agora" : hours < 48 ? `último evento há ${Math.round(hours)} h` : `último evento em ${new Date(iso).toLocaleDateString("pt-BR")}`;
};

/** Escolha do conjunto de dados (pixel) na revisão da campanha. Sem escolha, vale o recomendado (o que recebe eventos). */
export default function MetaPixelPicker({ draftId, value, disabled, onChange }: {
  draftId: string; value: string | null | undefined; disabled?: boolean; onChange: (pixelId: string) => void;
}) {
  const [data, setData] = useState<AdPixels | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    readAdPixels(draftId).then((d) => { if (alive) setData(d); })
      .catch((cause) => { if (alive) setError(cause instanceof Error && cause.message ? cause.message : "Não consegui ler os pixels da conta."); });
    return () => { alive = false; };
  }, [draftId]);

  // Sem escolha ainda: fica o recomendado (também corrige uma criação que parou no meio com o pixel errado).
  useEffect(() => { if (data && !value && data.recommended) onChange(data.recommended); }, [data, value, onChange]);

  if (error) return <p className="studioError" role="alert">{error}</p>;
  if (!data) return <p className="ds-caption">Carregando os pixels da conta…</p>;
  const selected = value || data.recommended || data.current || "";
  const chosen = data.pixels.find((p) => p.id === selected);
  return <div className={`metaPixel${chosen && !chosen.active ? " is-wrong" : ""}`}>
    <div className="metaPixelHead"><b>Pixel da campanha</b><span>Onde a Meta conta os cadastros/compras e otimiza a entrega.</span></div>
    <label className="metaPixelRow"><span className="ds-srOnly">Escolher pixel</span>
      <select value={selected} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {data.pixels.filter((p) => !p.unavailable).map((p) => <option key={p.id} value={p.id}>
          {p.name}{p.id === data.recommended ? " (recomendado)" : ""} · {when(p.last_fired_time)}</option>)}
      </select></label>
    {chosen && !chosen.active ? <p className="metaPixelWarn">Este pixel não recebe eventos do site: a Meta não vai conseguir otimizar. Prefira o recomendado.</p> : null}
  </div>;
}
