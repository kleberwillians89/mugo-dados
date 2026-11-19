import { useEffect, useMemo, useRef, useState } from "react";
import { listLibrary, previewKind, uploadLibraryFile, type LibraryItem } from "../../app/library";
import { videoCover } from "../../app/videoCover";
import { getActiveClientId } from "../../app/activeClient";
import { searchShopProducts, type CalendarItem, type ShopProduct } from "../../app/studio";
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
type Asset = { id: string; title: string; url: string; source: "library" | "calendar" | "instagram" | "shop"; itemId?: string | null; selectable?: boolean; permalink?: string | null; kind?: string; videoUrl?: string | null; product?: ShopProduct };
/** Produto da loja no anúncio: nome vira título (até 45), preço a descrição (até 20) e o link do produto o destino. */
const fromProduct = (p: ShopProduct) => ({ headline: p.name.slice(0, 45), ...(p.price ? { description: p.price.slice(0, 20) } : {}), ...(p.url ? { link: p.url } : {}) });
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
  const [source, setSource] = useState<"all" | "library" | "calendar" | "instagram" | "shop">("all");
  const [products, setProducts] = useState<ShopProduct[] | null>(null);
  const [shopLoading, setShopLoading] = useState(false);
  const [shopError, setShopError] = useState("");
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
  const toggleCard = (url: string, product?: ShopProduct) => {
    const at = cards.findIndex((c) => c.image_url === url);
    if (at >= 0) setCards(cards.filter((_, i) => i !== at));
    else if (cards.length < MAX_AD_CARDS) setCards([...cards, { image_url: url, ...(product ? fromProduct(product) : {}) }]);
  };

  /** Busca produtos no catálogo da loja da marca (o mesmo usado para marcar produtos no Instagram). */
  async function loadProducts(q = query) {
    if (!clientId) return;
    setShopLoading(true); setShopError("");
    try {
      const result = await searchShopProducts(q.trim());
      if (getActiveClientId() === clientId) setProducts(result.products || []);
    } catch (cause) {
      if (getActiveClientId() === clientId) { setProducts([]); setShopError(cause instanceof Error && cause.message ? cause.message : "Não foi possível consultar os produtos da loja."); }
    } finally { if (getActiveClientId() === clientId) setShopLoading(false); }
  }
  useEffect(() => { setProducts(null); setShopError(""); }, [clientId]);
  useEffect(() => { if (source === "shop" && products === null && !shopLoading) void loadProducts(); }, [source]); // eslint-disable-line react-hooks/exhaustive-deps
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
      previewKind(item) === "video"
        ? { id: "lib:" + item.id, title: item.title, url: item.url, source: "library" as const, kind: "VIDEO", videoUrl: item.url }
        : { id: "lib:" + item.id, title: item.title, url: item.url, source: "library" as const });
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
    const shop: Asset[] = (products || []).filter((p) => p.image_url).map((p) => ({
      id: "shop:" + p.product_id, title: p.name || "Produto da loja", url: p.image_url!, source: "shop" as const, product: p,
    }));
    const unique = new Set<string>();
    return [...saved, ...approved, ...instagram, ...shop].filter((item) => {
      if (!item.url || (item.source !== "instagram" && item.source !== "shop" && !image(item.url) && !item.url.includes("/storage/"))) return false;
      if (unique.has(item.url)) return false;
      unique.add(item.url);
      return (source === "all" || source === item.source) &&
        (!query.trim() || item.title.toLowerCase().includes(query.toLowerCase()));
    });
  }, [library, calendar, igPosts, products, source, query]);

  async function refresh() {
    if (!clientId) return;
    setLibraryLoading(true); setLibraryError("");
    try {
      const result = await listLibrary();
      if (getActiveClientId() !== clientId) return;
      setLibrary([...result.items, ...result.approved].filter((item) => ["image", "video"].includes(previewKind(item))));
    } catch (e) {
      if (getActiveClientId() === clientId) setLibraryError(e instanceof Error ? e.message : "Não foi possível carregar a Biblioteca.");
    } finally { if (getActiveClientId() === clientId) setLibraryLoading(false); }
  }

  useEffect(() => {
    let active = true;
    setLibraryLoading(true); setLibraryError("");
    listLibrary().then((result) => {
      if (!active || getActiveClientId() !== clientId) return;
      setLibrary([...result.items, ...result.approved].filter((item) => ["image", "video"].includes(previewKind(item))));
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
    const isVideo = ["video/mp4", "video/quicktime"].includes(file.type);
    if (!isVideo && !["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
      setLibraryError("Escolha uma imagem JPG, PNG ou WebP, ou um vídeo MP4 ou MOV.");
      return;
    }
    if (isVideo && many) {
      setLibraryError("Carrossel aceita só imagens. Para vídeo, escolha \"Imagem ou vídeo único\".");
      return;
    }
    setUploading(true); setLibraryError(""); setUploadProgress(0);
    try {
      if (isVideo) {
        const result = await uploadLibraryFile(file, "video", setUploadProgress, file.name, "Criativo de mídia paga");
        const blob = await videoCover(file);
        let cover = "";
        if (blob) {
          const name = file.name.replace(/\.[^.]+$/, "") + " (capa).jpg";
          try { cover = (await uploadLibraryFile(new File([blob], name, { type: "image/jpeg" }), "foto", undefined, name, "Capa do vídeo")).item.url; }
          catch { cover = ""; }
        }
        if (getActiveClientId() !== clientId) return;
        setLibrary((old) => [result.item, ...old]);
        onChoose({ media_type: "video", video_url: result.item.url, image_url: cover, instagram_post_id: null, calendar_item_id: null });
        setSource("all");
        return;
      }
      const result = await uploadLibraryFile(file, "foto", setUploadProgress, file.name, "Criativo de mídia paga");
      if (getActiveClientId() !== clientId) return;
      setLibrary((old) => [result.item, ...old]);
      if (many) { if (cards.length < MAX_AD_CARDS) setCards([...cards, { image_url: result.item.url }]); }
      else onChoose({ image_url: result.item.url, media_type: "image", video_url: "", instagram_post_id: null, calendar_item_id: null });
      setSource("all");
    } catch (cause) {
      if (getActiveClientId() === clientId) setLibraryError(cause instanceof Error ? cause.message : "Não foi possível enviar o arquivo.");
    } finally {
      setUploading(false); setUploadProgress(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const shape = FORMATS.find((x) => x.id === format)!;
  return <section className="metaCreativeStudio" aria-label="Estúdio de criativos">
    <div className="metaCreativeStudioTitle">
      <div><h3>Estúdio de criativos</h3><p>{many ? `Clique nas imagens na ordem em que devem aparecer (até ${MAX_AD_CARDS}).` : "Selecione uma imagem ou vídeo da Biblioteca da empresa, ou envie um novo."}</p></div>
      <button type="button" className="ds-button" disabled={disabled || uploading}
        onClick={() => fileRef.current?.click()}>{uploading ? `Enviando ${uploadProgress ?? 0}%…` : "+ Adicionar imagem ou vídeo"}</button>
      <input ref={fileRef} type="file" hidden accept="image/png,image/jpeg,image/webp,video/mp4,video/quicktime,.mov,.mp4"
        onChange={(event) => void upload(event.currentTarget.files?.[0])} />
    </div>
    {libraryError ? <p className="studioError" role="alert">{libraryError}</p> : null}
    {igError && source === "instagram" ? <p className="studioError" role="alert">{igError}</p> : null}
    {source === "shop" ? <p className="ds-caption">Produtos do catálogo da loja da marca. Ao escolher, a foto entra no anúncio e o nome, o preço e o link do produto preenchem título, descrição e destino (dá para editar depois).</p> : null}
    {shopError && source === "shop" ? <p className="studioError" role="alert">{shopError}</p> : null}
    {source === "instagram" ? <p className="ds-caption">Publicações sincronizadas da empresa ativa. Imagens e capas entram como foto única; vídeos com arquivo disponível podem ser enviados como anúncio de vídeo. Carrossel completo exige integração adicional.</p> : null}
    <div className="metaCreativeModes" role="radiogroup" aria-label="Formato do anúncio">
      {MODES.map((m) => <label key={m.id} className={mode === m.id ? "is-active" : ""}>
        <input type="radio" name="metaCreativeMode" checked={mode === m.id} disabled={disabled} onChange={() => changeMode(m.id)} />
        <span><b>{m.title}</b><small>{m.hint}</small></span></label>)}
    </div>
    <div className="metaCreativeStudioColumns">
      <div className="metaCreativeAssets">
        <div className="metaCreativeFilters">
          <label className="metaCreativeSearch">{source === "shop" ? "Buscar produto" : "Buscar imagem"}<input type="search" placeholder={source === "shop" ? "Nome ou SKU do produto…" : "Buscar na biblioteca…"} value={query}
            onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); if (source === "shop") void loadProducts(); } }} /></label>
          <label className="metaCreativeSearch">Origem<select value={source} onChange={(e) => setSource(e.target.value as typeof source)}>
            <option value="all">Todas</option><option value="library">Biblioteca</option><option value="calendar">Calendário {month}</option><option value="instagram">Publicações do Instagram</option><option value="shop">Produtos da loja</option>
          </select></label>
        </div>
        <div className="metaCreativeAssetToolbar"><b>{assets.length} {assets.length === 1 ? "arquivo encontrado" : "imagens e vídeos encontrados"}</b>
          {source === "shop" ? <button type="button" className="ds-link" disabled={shopLoading} onClick={() => void loadProducts()}>
            {shopLoading ? "Buscando produtos…" : "Buscar produtos"}</button>
          : <button type="button" className="ds-link" disabled={libraryLoading} onClick={() => void refresh()}>
            {libraryLoading ? "Atualizando…" : "Atualizar Biblioteca"}</button>}</div>
        <div className="metaCreativeAssetGrid">
          {assets.map((asset) => {
            const order = cards.findIndex((c) => c.image_url === asset.url);
            const chosen = many ? order >= 0 : ad.media_type === "video" ? ad.video_url === asset.videoUrl && Boolean(asset.videoUrl) : ad.image_url === asset.url;
            const blocked = asset.selectable === false || (many && (asset.kind === "VIDEO" || (order < 0 && cards.length >= MAX_AD_CARDS)));
            return <button type="button" key={asset.id} disabled={disabled || blocked}
              className={`metaCreativeAsset${chosen ? " is-selected" : ""}`} aria-pressed={chosen} title={asset.title}
              onClick={() => many ? toggleCard(asset.url, asset.product)
                : asset.product ? onChoose({ media_type: "image", video_url: "", instagram_post_id: null, image_url: asset.url, calendar_item_id: null,
                    ...(!ad.headline ? { headline: asset.product.name.slice(0, 45) } : {}),
                    ...(asset.product.url && !ad.link ? { link: asset.product.url } : {}),
                    ...(asset.product.price && !ad.description ? { description: asset.product.price.slice(0, 20) } : {}) })
                : asset.kind === "VIDEO" && asset.videoUrl
                  ? onChoose(asset.source === "library"
                    ? { media_type: "video", video_url: asset.videoUrl, image_url: "", instagram_post_id: null, calendar_item_id: null }
                    : { media_type: "video", video_url: asset.videoUrl, image_url: asset.url, instagram_post_id: asset.id.replace("ig:", ""), calendar_item_id: null })
                  : onChoose({ media_type: "image", video_url: "", instagram_post_id: null, image_url: asset.url, calendar_item_id: asset.itemId || null })}>
              {many && order >= 0 ? <i className="metaCreativeOrder" aria-label={`Posição ${order + 1}`}>{order + 1}</i> : null}
              {asset.source === "library" && asset.kind === "VIDEO"
                ? <video src={`${asset.url}#t=1`} muted playsInline preload="metadata" aria-label={asset.title} />
                : <img src={asset.url} alt={asset.title} loading="lazy" />}
              <span>{asset.title}</span><small>{asset.source === "shop" ? ["Loja", asset.product?.price].filter(Boolean).join(" · ") : asset.source === "library" ? asset.kind === "VIDEO" ? "Vídeo · Biblioteca" : "Biblioteca" : asset.source === "calendar" ? "Calendário" : asset.kind === "VIDEO" ? asset.videoUrl ? "Vídeo Instagram" : "Vídeo sem arquivo disponível" : asset.kind === "CAROUSEL_ALBUM" ? "Capa de carrossel" : "Instagram · imagem"}</small>
            </button>;
          })}
        </div>
        {!assets.length ? <p className="metaCreativeEmpty">{source === "shop" ? shopLoading ? "Buscando produtos…" : "Nenhum produto com foto nesta busca." : libraryLoading || igLoading ? "Buscando imagens…" : "Nenhuma imagem nesta seleção. Confira a sincronização do Instagram ou envie uma nova imagem."}</p> : null}
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
