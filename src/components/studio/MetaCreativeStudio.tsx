import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../../app/activeClient";
import { listLibrary, previewKind, uploadLibraryFile, type LibraryItem } from "../../app/library";
import type { CalendarItem } from "../../app/studio";
import type { AdPayload } from "../../app/metaAds";
import "./MetaCreativeStudio.css";

type Asset = { id: string; title: string; url: string; source: "biblioteca" | "calendario"; calendarId: string | null };
type Format = "feed" | "portrait" | "story" | "wide";
export const PREVIEW_FORMATS: { id: Format; label: string; ratio: string; description: string }[] = [
  { id: "feed", label: "Feed quadrado", ratio: "1:1", description: "Feed do Facebook e Instagram" },
  { id: "portrait", label: "Feed vertical", ratio: "4:5", description: "Feed Instagram vertical" },
  { id: "story", label: "Stories / Reels", ratio: "9:16", description: "Tela cheia, corte vertical" },
  { id: "wide", label: "Horizontal", ratio: "1,91:1", description: "Superfícies horizontais" },
];

export function combinedCreativeAssets(library: LibraryItem[], approved: LibraryItem[], calendar: CalendarItem[]): Asset[] {
  const seen = new Set<string>();
  const out: Asset[] = [];
  for (const item of [...library, ...approved]) {
    if (previewKind(item) !== "image" || !/^https:\/\//i.test(item.url)) continue;
    const url = item.url.trim();
    if (seen.has(url)) continue;
    seen.add(url);
    out.push({ id: "lib:" + item.id, title: item.title, url, source: "biblioteca", calendarId: item.kind === "post" ? item.item_id || null : null });
  }
  for (const item of calendar) {
    const url = String(item.art_url || "").split("\n")[0].trim();
    if (!/^https:\/\//i.test(url) || seen.has(url) || !(/\.(jpe?g|png|webp)(\?|$)/i.test(url) || url.includes("/storage/v1/object/public/"))) continue;
    seen.add(url);
    out.push({ id: "cal:" + item.id, title: item.title, url, source: "calendario", calendarId: item.id });
  }
  return out;
}

type Props = {
  ad: AdPayload["ad"];
  calendar: CalendarItem[];
  disabled: boolean;
  onChange: (patch: Partial<AdPayload["ad"]>) => void;
};

export default function MetaCreativeStudio({ ad, calendar, disabled, onChange }: Props) {
  const tenant = getActiveClientId();
  const brand = getActiveClientName() || "Marca";
  const [library, setLibrary] = useState<LibraryItem[]>([]);
  const [approved, setApproved] = useState<LibraryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [query, setQuery] = useState("");
  const [source, setSource] = useState<"all" | "biblioteca" | "calendario">("all");
  const [format, setFormat] = useState<Format>("portrait");
  const fileInput = useRef<HTMLInputElement | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const result = await listLibrary();
      if (getActiveClientId() !== tenant) return;
      setLibrary(result.items);
      setApproved(result.approved);
    } catch (cause) {
      if (getActiveClientId() === tenant) setError(cause instanceof Error ? cause.message : "Não foi possível carregar a biblioteca da marca.");
    } finally {
      if (getActiveClientId() === tenant) setLoading(false);
    }
  }, [tenant]);

  useEffect(() => { void refresh(); }, [refresh]);
  const assets = useMemo(() => combinedCreativeAssets(library, approved, calendar), [library, approved, calendar]);
  const visible = useMemo(() => assets.filter(a =>
    (source === "all" || a.source === source) &&
    (!query.trim() || a.title.toLocaleLowerCase("pt-BR").includes(query.trim().toLocaleLowerCase("pt-BR")))
  ), [assets, source, query]);
  const selectedFormat = PREVIEW_FORMATS.find(x => x.id === format)!;

  async function upload(file: File | undefined) {
    if (!file || disabled || uploading) return;
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setError("Para anúncios, envie uma imagem JPG, PNG ou WEBP."); return;
    }
    if (file.size > 20 * 1024 * 1024) {
      setError("Imagem acima de 20 MB. Reduza o arquivo antes de enviar."); return;
    }
    setUploading(true); setProgress(0); setError("");
    try {
      const result = await uploadLibraryFile(file, "foto", setProgress, file.name, "Criativo para anúncios");
      if (getActiveClientId() !== tenant) return;
      onChange({ image_url: result.item.url, calendar_item_id: null });
      await refresh();
    } catch (cause) {
      if (getActiveClientId() === tenant) setError(cause instanceof Error ? cause.message : "Não foi possível enviar a imagem.");
    } finally { setUploading(false); if (fileInput.current) fileInput.current.value = ""; }
  }

  return <section className="mcs" aria-label="Estúdio de criativos da campanha">
    <header className="mcsHead">
      <div><span className="mcsEyebrow">ESTÚDIO DE CRIATIVOS</span>
        <h3>Escolha uma arte. Veja antes de publicar.</h3>
        <p>Use imagens já salvas na Biblioteca da marca, artes do Calendário ou envie uma nova.</p></div>
      <div className="mcsHeadActions">
        <button type="button" className="ds-button" onClick={() => void refresh()} disabled={loading || uploading}>Atualizar</button>
        <button type="button" className="ds-button is-primary" disabled={disabled || uploading} onClick={() => fileInput.current?.click()}>
          {uploading ? `Enviando ${progress}%` : "+ Enviar imagem"}
        </button>
        <input ref={fileInput} type="file" hidden accept="image/jpeg,image/png,image/webp" onChange={e => void upload(e.target.files?.[0])} />
      </div>
    </header>
    {error ? <p className="studioError" role="alert">{error}</p> : null}
    <div className="mcsWorkspace">
      <div className="mcsLibrary">
        <div className="mcsFilters">
          <label className="mcsSearch">Buscar criativo<input aria-label="Buscar criativo" value={query} onChange={e => setQuery(e.target.value)} placeholder="Nome da arte ou campanha" /></label>
          <label className="mcsSearch">Origem<select aria-label="Filtrar criativos por origem" value={source} onChange={e => setSource(e.target.value as typeof source)}>
            <option value="all">Todas</option><option value="biblioteca">Biblioteca da marca</option><option value="calendario">Calendário</option>
          </select></label>
        </div>
        <div className="mcsCount">{loading ? "Carregando acervo da marca…" : `${visible.length} criativo(s) disponíveis`}</div>
        {visible.length ? <div className="mcsAssets" aria-label="Imagens disponíveis">
          {visible.map(item => <button type="button" key={item.id} title={item.title}
            aria-pressed={ad.image_url === item.url} disabled={disabled}
            className={`mcsAsset${ad.image_url === item.url ? " is-selected" : ""}`}
            onClick={() => onChange({ image_url: item.url, calendar_item_id: item.calendarId })}>
            <img src={item.url} alt={item.title} loading="lazy" />
            <span>{item.title}</span><small>{item.source === "biblioteca" ? "Biblioteca" : "Calendário"}</small>
          </button>)}
        </div> : !loading ? <p className="mcsEmpty">Nenhuma imagem nesta seleção. Envie um JPG/PNG/WEBP ou escolha outro filtro.</p> : null}
        <label className="mcsExternal">Ou cole o endereço HTTPS de uma imagem já hospedada
          <input type="url" value={ad.image_url} maxLength={1000} disabled={disabled} placeholder="https://.../criativo.jpg"
            onChange={e => onChange({ image_url: e.target.value, calendar_item_id: null })} />
        </label>
      </div>
      <div className="mcsPreviewSide">
        <div className="mcsPreviewTop"><b>Prévia por formato</b><span>{selectedFormat.ratio}</span></div>
        <div className="mcsFormats" role="group" aria-label="Visualizar formatos">
          {PREVIEW_FORMATS.map(item => <button type="button" aria-pressed={format === item.id} key={item.id}
            className={format === item.id ? "is-active" : ""} onClick={() => setFormat(item.id)}>{item.ratio}<small>{item.label}</small></button>)}
        </div>
        <div className={`mcsStage is-${format}`}>
          <div className="mcsAdMock">
            <div className="mcsMockHead"><span className="mcsBrandDot">{brand.charAt(0).toUpperCase()}</span><span><b>{brand}</b><small>Patrocinado · prévia</small></span></div>
            <p className="mcsMockCopy">{ad.primary_text || "Seu texto principal aparecerá aqui."}</p>
            <div className={`mcsImage is-${format}`}>
              {ad.image_url ? <img src={ad.image_url} alt="Prévia do criativo selecionado" /> : <div className="mcsNoImage">Selecione uma imagem na biblioteca</div>}
            </div>
            <div className="mcsMockFooter"><span><b>{ad.headline || "Título do anúncio"}</b><small>{ad.description || "Descrição do anúncio"}</small></span><span className="mcsMockCta">{ad.cta.replace(/_/g, " ") || "Saiba mais"}</span></div>
          </div>
        </div>
        <p className="mcsFormatInfo">{selectedFormat.description}. A imagem é simulada com recorte automático, sem alterar o arquivo original.</p>
        <p className="mcsWarning"><b>Importante:</b> estas são prévias de enquadramento, não posicionamentos ativos nem variantes independentes. Esta versão do envio à Meta usa uma imagem por anúncio. Confira o resultado final no Gerenciador antes de ativar.</p>
      </div>
    </div>
  </section>;
}
