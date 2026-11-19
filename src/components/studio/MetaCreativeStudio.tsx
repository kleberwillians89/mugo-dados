import { useEffect, useMemo, useRef, useState } from "react";
import { listLibrary, previewKind, uploadLibraryFile, type LibraryItem } from "../../app/library";
import { getActiveClientId } from "../../app/activeClient";
import type { CalendarItem } from "../../app/studio";
import { MAX_AD_CARDS, type AdCard, type AdFormat, type AdPayload, type InstagramCreativePost } from "../../app/metaAds";
import { listInstagramCreativePosts } from "../../app/metaAds";
import "./MetaCreativeStudio.css";

export type CreativePreviewFormat = "feed" | "portrait" | "story";
const FORMATS: { id: CreativePreviewFormat; title: string; ratio: string; hint: string }[] = [
  { id: "feed", title: "Feed quadrado", ratio: "1:1", hint: "1080 × 1080" },
  { id: "portrait", title: "Feed vertical", ratio: "4:5", hint: "1080 × 1350" },
  { id: "story", title: "Stories / Reels", ratio: "9:16", hint: "1080 × 1920" },
];
const MODES: { id: "single" | "carousel"; title: string; hint: string }[] = [
  { id: "single", title: "Imagem ou vídeo único", hint: "Uma imagem ou um vídeo neste anúncio" },
  { id: "carousel", title: "Carrossel", hint: "2 a 10 imagens neste anúncio, que a pessoa desliza no feed e nos stories" },
];
const image = (value: string) => /\.(jpe?g|png|webp|gif)(\?.*)?$/i.test(value) || value.includes("/storage/v1/object/public/");
const firstArt = (item: CalendarItem) => String(item.art_url || "").split("\n")[0].trim();
type Asset = { id: string; title: string; url: string; source: "library" | "calendar" | "instagram"; itemId?: string | null; selectable?: boolean; permalink?: string | null; kind?: string; videoUrl?: string | null };
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
  const [igPosts, setIgPosts] = useState<InstagramCreativePost[]>([]);
  const [igLoading, setIgLoading] = useState(false);
  const [igError, setIgError] = useState("");

  const [libraryError, setLibraryError] = useState("");
  const [format, setFormat] = useState<CreativePreviewFormat>("portrait");
  const [source, setSource] = useState<"all" | "library" | "calendar" | "instagram">("all");
  const [query, setQuery] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const mode: AdFormat = ad.format === "carousel" ? "carousel" : "single";
  const cards: AdCard[] = ad.cards || [];
  const many = mode !== "single";
  const [slide, setSlide] = useState(0);
  const setCards = (next: AdCard[]) => onChoose({ cards: next, media_type: "image", video_url: "", instagram_post_id: null,
    image_url: next[0]?.image_url || "", calendar_item_id: null });
  const toggleCard = (url: string) => {
    const at = cards.findIndex((c) => c.image_url === url);
    if (at >= 0) setCards(cards.filter((_, i) => i !== at));
    else if (cards.length < MAX_AD_CARDS) setCards([...cards, { image_url: url }]);
  };
  const editCard = (i: number, patch: Partial<AdCard>) => setCards(cards.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const moveCard = (from: number, to: number) => {
    if (to < 0 || to >= cards.length) return;
    const next = [...cards]; const [item] = next.splice(from, 1); next.splice(to, 0, item); setCards(next);
  };
  const changeMode = (next: AdFormat) => {
    if (next === mode) return;
    if (next === "single") onChoose({ format: "single", image_url: cards[0]?.image_url || ad.image_url });
    else onChoose({ format: next, media_type: "image", video_url: "", instagram_post_id: null,
      cards: cards.length ? cards : ad.image_url && ad.media_type !== "video" ? [{ image_url: ad.image_url }] : [] });
    setSlide(0);
  };

  const assets = useMemo<Asset[]>(() => {
    const saved: Asset[] = [...library].map((item) =>
      ({ id: "lib:" + item.id, title: item.title, url: item.url, source: "library" as const }));
    const approved: Asset[] = calendar.map((item) => ({
      id: "cal:" + item.id, title: item.title || "Post do calendário", url: firstArt(item),
      source: "calendar" as const, itemId: item.id,
    }));
    const instagram: Asset[] = igPosts.map((post) => ({
      id: "ig:" + post.id,
      title: post.caption?.trim().slice(0, 80) || "Publicação do Instagram",
      url: post.preview_url,
      source: "instagram" as const,
      selectable: post.selectable,
      permalink: post.permalink,
      kind: post.media_type,
      videoUrl: post.video_url,
    }));
    const unique = new Set<string>();
    return [...saved, ...approved, ...instagram].filter((item) => {
      if (!item.url || (item.source !== "instagram" && !image(item.url) && !item.url.includes("/storage/"))) return false;
      if (unique.has(item.url)) return false;
      unique.add(item.url);
      return (source === "all" || source === item.source) &&
        (!query.trim() || item.title.toLowerCase().includes(query.toLowerCase()));
    });
  }, [library, calendar, igPosts, source, query]);

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

  useEffect(() => {
    let active = true;
    setIgPosts([]); setIgError(""); setIgLoading(true);
    listInstagramCreativePosts().then((result) => {
      if (active && getActiveClientId() === clientId) setIgPosts(result.posts || []);
    }).catch((cause) => {
      if (active && getActiveClientId() === clientId) setIgError(
        cause instanceof Error ? cause.message : "Não foi possível consultar as publicações do Instagram.");
    }).finally(() => { if (active) setIgLoading(false); });
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
      if (many) { if (cards.length < MAX_AD_CARDS) setCards([...cards, { image_url: result.item.url }]); }
      else onChoose({ image_url: result.item.url, media_type: "image", video_url: "", instagram_post_id: null, calendar_item_id: null });
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
      <div><h3>Estúdio de criativos</h3><p>{many ? `Clique nas imagens na ordem em que devem aparecer (até ${MAX_AD_CARDS}).` : "Selecione uma imagem da Biblioteca da empresa ou envie uma nova."}</p></div>
      <button type="button" className="ds-button" disabled={disabled || uploading}
        onClick={() => fileRef.current?.click()}>{uploading ? `Enviando ${uploadProgress ?? 0}%…` : "+ Adicionar imagem"}</button>
      <input ref={fileRef} type="file" hidden accept="image/png,image/jpeg,image/webp"
        onChange={(event) => void upload(event.currentTarget.files?.[0])} />
    </div>
    {libraryError ? <p className="studioError" role="alert">{libraryError}</p> : null}
    {igError && source === "instagram" ? <p className="studioError" role="alert">{igError}</p> : null}
    {source === "instagram" ? <p className="ds-caption">Publicações sincronizadas da empresa ativa. Imagens e capas entram como foto única; vídeos com arquivo disponível podem ser enviados como anúncio de vídeo. Carrossel completo exige integração adicional.</p> : null}
    <div className="metaCreativeModes" role="radiogroup" aria-label="Formato do anúncio">
      {MODES.map((m) => <label key={m.id} className={mode === m.id ? "is-active" : ""}>
        <input type="radio" name="metaCreativeMode" checked={mode === m.id} disabled={disabled} onChange={() => changeMode(m.id)} />
        <span><b>{m.title}</b><small>{m.hint}</small></span></label>)}
    </div>
    <div className="metaCreativeStudioColumns">
      <div className="metaCreativeAssets">
        <div className="metaCreativeFilters">
          <label className="metaCreativeSearch">Buscar imagem<input type="search" placeholder="Buscar na biblioteca…" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
          <label className="metaCreativeSearch">Origem<select value={source} onChange={(e) => setSource(e.target.value as typeof source)}>
            <option value="all">Todas</option><option value="library">Biblioteca</option><option value="calendar">Calendário {month}</option><option value="instagram">Publicações do Instagram</option>
          </select></label>
        </div>
        <div className="metaCreativeAssetToolbar"><b>{assets.length} imagens encontradas</b>
          <button type="button" className="ds-link" disabled={libraryLoading} onClick={() => void refresh()}>
            {libraryLoading ? "Atualizando…" : "Atualizar Biblioteca"}</button></div>
        <div className="metaCreativeAssetGrid">
          {assets.map((asset) => {
            const order = cards.findIndex((c) => c.image_url === asset.url);
            const chosen = many ? order >= 0 : ad.media_type === "video" ? ad.video_url === asset.videoUrl && Boolean(asset.videoUrl) : ad.image_url === asset.url;
            const blocked = asset.selectable === false || (many && (asset.kind === "VIDEO" || (order < 0 && cards.length >= MAX_AD_CARDS)));
            return <button type="button" key={asset.id} disabled={disabled || blocked}
              className={`metaCreativeAsset${chosen ? " is-selected" : ""}`} aria-pressed={chosen} title={asset.title}
              onClick={() => many ? toggleCard(asset.url)
                : asset.kind === "VIDEO" && asset.videoUrl
                  ? onChoose({ media_type: "video", video_url: asset.videoUrl, image_url: asset.url, instagram_post_id: asset.id.replace("ig:", ""), calendar_item_id: null })
                  : onChoose({ media_type: "image", video_url: "", instagram_post_id: null, image_url: asset.url, calendar_item_id: asset.itemId || null })}>
              {many && order >= 0 ? <i className="metaCreativeOrder" aria-label={`Posição ${order + 1}`}>{order + 1}</i> : null}
              <img src={asset.url} alt={asset.title} loading="lazy" />
              <span>{asset.title}</span><small>{asset.source === "library" ? "Biblioteca" : asset.source === "calendar" ? "Calendário" : asset.kind === "VIDEO" ? asset.videoUrl ? "Vídeo Instagram" : "Vídeo sem arquivo disponível" : asset.kind === "CAROUSEL_ALBUM" ? "Capa de carrossel" : "Instagram · imagem"}</small>
            </button>;
          })}
        </div>
        {!assets.length ? <p className="metaCreativeEmpty">{libraryLoading || igLoading ? "Buscando imagens…" : "Nenhuma imagem nesta seleção. Confira a sincronização do Instagram ou envie uma nova imagem."}</p> : null}
        {many ? <div className="metaCreativeCards" aria-label="Imagens escolhidas">
          <b>{cards.length} de {MAX_AD_CARDS} imagens{cards.length < 2 ? " · escolha pelo menos 2" : ""}</b>
          {cards.length ? <ol>{cards.map((card, i) => <li key={card.image_url}>
            <img src={card.image_url} alt="" />
            {mode === "carousel" ? <span className="metaCreativeCardFields">
              <b>Cartão {i + 1}</b>
              <label><span className="ds-srOnly">Título do cartão {i + 1}</span>
                <input maxLength={45} placeholder={ad.headline ? `Título: ${ad.headline}` : "Título (até 45 caracteres)"} value={card.headline || ""} disabled={disabled}
                  onChange={(e) => editCard(i, { headline: e.target.value })} /></label>
              <label><span className="ds-srOnly">Descrição do cartão {i + 1}</span>
                <input maxLength={20} placeholder="Descrição (opcional, até 20)" value={card.description || ""} disabled={disabled}
                  onChange={(e) => editCard(i, { description: e.target.value })} /></label>
              <label><span className="ds-srOnly">Link do cartão {i + 1}</span>
                <input type="url" maxLength={500} placeholder={ad.link ? `Link: ${ad.link}` : "https://… (opcional)"} value={card.link || ""} disabled={disabled}
                  onChange={(e) => editCard(i, { link: e.target.value })} /></label>
            </span>
              : <span className="metaCreativeCardTitle">Imagem {i + 1}</span>}
            <span className="metaCreativeCardMove">
              <button type="button" className="ds-link" disabled={disabled || i === 0} aria-label={`Mover imagem ${i + 1} para antes`} onClick={() => moveCard(i, i - 1)}>↑</button>
              <button type="button" className="ds-link" disabled={disabled || i === cards.length - 1} aria-label={`Mover imagem ${i + 1} para depois`} onClick={() => moveCard(i, i + 1)}>↓</button>
              <button type="button" className="ds-link" disabled={disabled} aria-label={`Tirar imagem ${i + 1}`} onClick={() => setCards(cards.filter((_, j) => j !== i))}>Tirar</button>
            </span>
          </li>)}</ol> : null}
        </div> : <>
        <label className="ds-field">Ou cole um link HTTPS direto da imagem
          <input type="url" maxLength={1000} placeholder="https://…/imagem.jpg" value={ad.image_url}
            disabled={disabled} onChange={(e) => onChoose({ image_url: e.target.value, media_type: "image", video_url: "", instagram_post_id: null, calendar_item_id: null })} />
        </label>
        </>}
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
            {many && cards.length ? <div className="metaCreativeSlides">
              <img src={cards[Math.min(slide, cards.length - 1)].image_url} alt={`Imagem ${Math.min(slide, cards.length - 1) + 1} de ${cards.length}`} />
              <span className="metaCreativeSlideCount">{Math.min(slide, cards.length - 1) + 1}/{cards.length}</span>
              <button type="button" className="metaCreativeSlidePrev" aria-label="Imagem anterior" disabled={slide <= 0} onClick={() => setSlide((n) => Math.max(0, n - 1))}>‹</button>
              <button type="button" className="metaCreativeSlideNext" aria-label="Próxima imagem" disabled={slide >= cards.length - 1} onClick={() => setSlide((n) => Math.min(cards.length - 1, n + 1))}>›</button>
            </div> : ad.media_type === "video" && ad.video_url ? <video src={ad.video_url} poster={ad.image_url} controls playsInline preload="metadata" aria-label={`Prévia em vídeo ${shape.ratio}`} /> : ad.image_url ? <img src={ad.image_url} alt={`Prévia em ${shape.ratio}`} /> :
              <div className="metaCreativeNoImage">Selecione uma imagem para pré-visualizar</div>}
          </div>
          <div className="metaCreativeDeviceCaption"><div><small>{ad.link ? (() => { try { return new URL(ad.link).hostname; } catch { return "Site da marca"; } })() : "Site da marca"}</small>
            <b>{(many && cards[Math.min(slide, cards.length - 1)]?.headline) || ad.headline || "Título do anúncio"}</b><span>{(many && cards[Math.min(slide, cards.length - 1)]?.description) || ad.description || "Descrição do anúncio"}</span></div>
            <span className="metaCreativeFakeCta">{ad.cta ? ad.cta.replaceAll("_", " ") : "Saiba mais"}</span></div>
        </div>
        <p className="metaCreativeDisclaimer">Prévia ilustrativa de recorte {shape.ratio} ({shape.hint}). A seleção de posicionamentos é feita na etapa Público. O recorte exibido é ilustrativo: a Meta pode recusar vídeos ou imagens incompatíveis e não são geradas versões diferentes automaticamente.</p>
      </div>
    </div>
  </section>;
}
