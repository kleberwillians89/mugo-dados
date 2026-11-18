import { useEffect, useMemo, useRef, useState } from "react";
import { listLibrary, previewKind, uploadLibraryFile, type LibraryItem } from "../../app/library";
import { getActiveClientId } from "../../app/activeClient";
import type { CalendarItem } from "../../app/studio";
import type { AdPayload } from "../../app/metaAds";
import "./MetaCreativeStudio.css";

export type CreativePreviewFormat = "feed" | "portrait" | "story";
const FORMATS: { id: CreativePreviewFormat; title: string; ratio: string; hint: string }[] = [
  { id: "feed", title: "Feed quadrado", ratio: "1:1", hint: "1080 × 1080" },
  { id: "portrait", title: "Feed vertical", ratio: "4:5", hint: "1080 × 1350" },
  { id: "story", title: "Stories / Reels", ratio: "9:16", hint: "1080 × 1920" },
];
const image = (value: string) => /\.(jpe?g|png|webp|gif)(\?.*)?$/i.test(value) || value.includes("/storage/v1/object/public/");
const firstArt = (item: CalendarItem) => String(item.art_url || "").split("\n")[0].trim();
type Asset = { id: string; title: string; url: string; source: "library" | "calendar"; itemId?: string | null };
type Props = {
  clientId: string;
  month: string;
  calendar: CalendarItem[];
  ad: AdPayload["ad"];
  disabled?: boolean;
  onChoose: (patch: Partial<AdPayload["ad"]>) => void;
};

export default function MetaCreativeStudio({ clientId, month, calendar, ad, disabled, onChoose }: Props) {
  const [library, setLibrary] = useState<LibraryItem[]>([]);
  const [libraryLoading, setLibraryLoading] = useState(false);

  const [libraryError, setLibraryError] = useState("");
  const [format, setFormat] = useState<CreativePreviewFormat>("portrait");
  const [source, setSource] = useState<"all" | "library" | "calendar">("all");
  const [query, setQuery] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const assets = useMemo<Asset[]>(() => {
    const saved: Asset[] = [...library].map((item) =>
      ({ id: "lib:" + item.id, title: item.title, url: item.url, source: "library" as const }));
    const approved: Asset[] = calendar.map((item) => ({
      id: "cal:" + item.id, title: item.title || "Post do calendário", url: firstArt(item),
      source: "calendar" as const, itemId: item.id,
    }));
    const unique = new Set<string>();
    return [...saved, ...approved].filter((item) => {
      if (!item.url || (!image(item.url) && !item.url.includes("/storage/"))) return false;
      if (unique.has(item.url)) return false;
      unique.add(item.url);
      return (source === "all" || source === item.source) &&
        (!query.trim() || item.title.toLowerCase().includes(query.toLowerCase()));
    });
  }, [library, calendar, source, query]);

  async function refresh() {
    if (!clientId) return;
    setLibraryLoading(true); setLibraryError("");
    try {
      const result = await listLibrary();
      if (getActiveClientId() !== clientId) return;
      setLibrary([...result.items, ...result.approved].filter((item) => previewKind(item) === "image"));
    } catch (e) {
      if (getActiveClientId() === clientId) setLibraryError(e instanceof Error ? e.message : "Não foi possível carregar a Biblioteca.");
    } finally { if (getActiveClientId() === clientId) setLibraryLoading(false); }
  }

  useEffect(() => {
    let active = true;
    setLibraryLoading(true); setLibraryError("");
    listLibrary().then((result) => {
      if (!active || getActiveClientId() !== clientId) return;
      setLibrary([...result.items, ...result.approved].filter((item) => previewKind(item) === "image"));
    }).catch((cause) => {
      if (active && getActiveClientId() === clientId)
        setLibraryError(cause instanceof Error ? cause.message : "Não foi possível carregar imagens.");
    }).finally(() => { if (active && getActiveClientId() === clientId) setLibraryLoading(false); });
    return () => { active = false; };
  }, [clientId]);

  async function upload(file: File | undefined) {
    if (!file || uploading) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
      setLibraryError("Escolha uma imagem JPG, PNG ou WebP.");
      return;
    }
    setUploading(true); setLibraryError(""); setUploadProgress(0);
    try {
      const result = await uploadLibraryFile(file, "foto", setUploadProgress, file.name, "Criativo de mídia paga");
      if (getActiveClientId() !== clientId) return;
      setLibrary((old) => [result.item, ...old]);
      onChoose({ image_url: result.item.url, calendar_item_id: null });
      setSource("all");
    } catch (cause) {
      if (getActiveClientId() === clientId) setLibraryError(cause instanceof Error ? cause.message : "Não foi possível enviar a imagem.");
    } finally {
      setUploading(false); setUploadProgress(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const shape = FORMATS.find((x) => x.id === format)!;
  return <section className="metaCreativeStudio" aria-label="Estúdio de criativos">
    <div className="metaCreativeStudioTitle">
      <div><h3>Estúdio de criativos</h3><p>Selecione uma imagem da Biblioteca da empresa ou envie uma nova.</p></div>
      <button type="button" className="ds-button" disabled={disabled || uploading}
        onClick={() => fileRef.current?.click()}>{uploading ? `Enviando ${uploadProgress ?? 0}%…` : "+ Adicionar imagem"}</button>
      <input ref={fileRef} type="file" hidden accept="image/png,image/jpeg,image/webp"
        onChange={(event) => void upload(event.currentTarget.files?.[0])} />
    </div>
    {libraryError ? <p className="studioError" role="alert">{libraryError}</p> : null}
    <div className="metaCreativeStudioColumns">
      <div className="metaCreativeAssets">
        <div className="metaCreativeFilters">
          <label className="metaCreativeSearch">Buscar imagem<input type="search" placeholder="Buscar na biblioteca…" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
          <label className="metaCreativeSearch">Origem<select value={source} onChange={(e) => setSource(e.target.value as typeof source)}>
            <option value="all">Todas</option><option value="library">Biblioteca</option><option value="calendar">Calendário {month}</option>
          </select></label>
        </div>
        <div className="metaCreativeAssetToolbar"><b>{assets.length} imagens encontradas</b>
          <button type="button" className="ds-link" disabled={libraryLoading} onClick={() => void refresh()}>
            {libraryLoading ? "Atualizando…" : "Atualizar Biblioteca"}</button></div>
        <div className="metaCreativeAssetGrid">
          {assets.map((asset) => <button type="button" key={asset.id} disabled={disabled}
            className={`metaCreativeAsset${ad.image_url === asset.url ? " is-selected" : ""}`}
            aria-pressed={ad.image_url === asset.url} title={asset.title}
            onClick={() => onChoose({ image_url: asset.url, calendar_item_id: asset.itemId || null })}>
            <img src={asset.url} alt={asset.title} loading="lazy" />
            <span>{asset.title}</span><small>{asset.source === "library" ? "Biblioteca" : "Calendário"}</small>
          </button>)}
        </div>
        {!assets.length ? <p className="metaCreativeEmpty">{libraryLoading ? "Buscando imagens…" : "Nenhuma imagem nesta seleção. Adicione uma nova ou confira a Biblioteca desta empresa."}</p> : null}
        <label className="ds-field">Ou cole um link HTTPS direto da imagem
          <input type="url" maxLength={1000} placeholder="https://…/imagem.jpg" value={ad.image_url}
            disabled={disabled} onChange={(e) => onChoose({ image_url: e.target.value, calendar_item_id: null })} />
        </label>
      </div>
      <div className="metaCreativePreview">
        <div className="metaCreativePreviewHeader"><b>Prévia visual</b><span>{shape.ratio}</span></div>
        <div className="metaCreativeFormats" role="group" aria-label="Visualizar proporções de anúncio">
          {FORMATS.map((f) => <button key={f.id} type="button" className={format === f.id ? "is-active" : ""}
            aria-pressed={format === f.id} onClick={() => setFormat(f.id)}><b>{f.title}</b><small>{f.ratio}</small></button>)}
        </div>
        <div className={`metaCreativeDevice is-${format}`}>
          <div className="metaCreativeDeviceTop"><span className="metaCreativeAvatar">R</span><div><strong>Anúncio da marca</strong><small>Patrocinado · Prévia</small></div><span>•••</span></div>
          <div className="metaCreativeDeviceText">{ad.primary_text || "O texto principal aparecerá aqui."}</div>
          <div className="metaCreativeDevicePhoto">
            {ad.image_url ? <img src={ad.image_url} alt={`Prévia em ${shape.ratio}`} /> :
              <div className="metaCreativeNoImage">Selecione uma imagem para pré-visualizar</div>}
          </div>
          <div className="metaCreativeDeviceCaption"><div><small>{ad.link ? (() => { try { return new URL(ad.link).hostname; } catch { return "Site da marca"; } })() : "Site da marca"}</small>
            <b>{ad.headline || "Título do anúncio"}</b><span>{ad.description || "Descrição do anúncio"}</span></div>
            <span className="metaCreativeFakeCta">{ad.cta ? ad.cta.replaceAll("_", " ") : "Saiba mais"}</span></div>
        </div>
        <p className="metaCreativeDisclaimer">Prévia ilustrativa de recorte {shape.ratio} ({shape.hint}). A API atual publica uma única imagem; a escolha da proporção aqui não cria versões adicionais nem muda posicionamentos no Meta.</p>
      </div>
    </div>
  </section>;
}
