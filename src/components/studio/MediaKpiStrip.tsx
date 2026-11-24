import { useMemo, useState } from "react";
import { ArrowRight } from "lucide-react";
import { useDashboardSnapshot } from "../../app/DashboardDataContext";
import { last30Days, mediaKpis, type MediaPlatform } from "../../app/mediaKpis";
import { DataFreshness } from "../data/DataFreshness";
import SegmentedControl from "../data/SegmentedControl";

const PLATFORM: Record<MediaPlatform, { label: string; source: string; route: "meta" | "google"; detail: string }> = {
  meta: { label: "Meta Ads", source: "meta_ads", route: "meta", detail: "Abrir análise da Meta" },
  google: { label: "Google Ads", source: "google_ads", route: "google", detail: "Abrir análise do Google" },
};
const br = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });

/**
 * Resumo compacto dos indicadores da plataforma escolhida, logo abaixo das campanhas (visão operacional).
 * Mesmos dados dos painéis Meta e Google (read model diário); a análise aprofundada fica lá.
 */
export default function MediaKpiStrip({ onOpen }: { onOpen: (route: "meta" | "google") => void }) {
  const range = useMemo(() => last30Days(), []);
  const model = useDashboardSnapshot(range.start, range.end);
  const meta = useMemo(() => mediaKpis("meta", model.daily), [model.daily]);
  const google = useMemo(() => mediaKpis("google", model.daily), [model.daily]);
  const [picked, setPicked] = useState<MediaPlatform | null>(null);
  const platform: MediaPlatform = picked || (!meta.available && google.available ? "google" : "meta");
  const summary = platform === "meta" ? meta : google;
  const info = PLATFORM[platform];

  return <section className="mediaKpiStrip" aria-labelledby="media-kpi-title" data-testid="media-kpi-strip">
    <div className="mediaKpiHead">
      <div><h2 id="media-kpi-title">Indicadores de mídia</h2>
        <small>Últimos 30 dias ({br(range.start)} a {br(range.end)})</small></div>
      <SegmentedControl ariaLabel="Plataforma" value={platform} onSelect={(id) => setPicked(id as MediaPlatform)}
        options={(Object.keys(PLATFORM) as MediaPlatform[]).map((p) => ({ id: p, label: PLATFORM[p].label }))} />
    </div>
    {model.loading && !model.daily.length ? <p className="libHint" role="status">Carregando os indicadores…</p>
      : model.error ? <p className="studioError" role="alert">Não foi possível ler os indicadores agora.</p>
      : !summary.available ? <p className="libHint">Sem dados de {info.label} neste período. Confira a conexão em Configurações ou a análise da plataforma.</p>
      : <dl className="mediaKpiGrid">{summary.kpis.map((k) => <div key={k.key}><dt>{k.label}</dt><dd>{k.value}</dd></div>)}</dl>}
    <div className="mediaKpiFoot">
      <small>Fonte: {info.label} · <DataFreshness provider={info.source} compact />
        {platform === "meta" ? " · Compras e receita atribuídas pela plataforma, não a receita total da loja." : " · Conversões e valor informados pelo Google Ads."}</small>
      <button type="button" className="ds-button" onClick={() => onOpen(info.route)}>{info.detail} <ArrowRight size={15} aria-hidden="true" /></button>
    </div>
  </section>;
}
