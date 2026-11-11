import { useState, type MouseEvent } from "react";
import { ShoppingBag, X } from "lucide-react";
import { isArtVideo } from "../../app/artLinks";
import { getShop, searchShopProducts, type ProductTag, type ShopProduct, type ShopStatus, type StudioFormat } from "../../app/studio";

const PER_SLIDE = 5;
const limitFor = (format: StudioFormat) => (format === "reels" || format === "video" ? 30 : 20);

/**
 * Produtos da loja do Instagram (Instagram Shopping) marcados no post. Busca no catálogo da marca, marca até 5 por
 * slide e, na imagem, o ponto da marcação é onde a equipe clica na arte. Publicado junto com o post.
 */
export default function ProductTags({ value, onChange, format, slides, disabled }: {
  value: ProductTag[]; onChange: (next: ProductTag[]) => void; format: StudioFormat; slides: string[]; disabled?: boolean;
}) {
  const [shop, setShop] = useState<ShopStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [catalog, setCatalog] = useState("");
  const [results, setResults] = useState<ShopProduct[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [slide, setSlide] = useState(0);
  const [active, setActive] = useState<string | null>(null);
  const story = format === "stories";
  const carousel = format === "carrossel";
  const video = format === "reels" || format === "video";
  const art = slides[slide] || null;
  const placeable = !video && Boolean(art) && !isArtVideo(art || "");
  const onSlide = value.filter((t) => (carousel ? t.slide === slide : true));

  async function open() {
    setLoading(true); setError(null);
    try { const s = await getShop(); setShop(s); setCatalog(s.catalogs[0]?.id || ""); }
    catch (cause) { setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível consultar a loja agora."); }
    finally { setLoading(false); }
  }

  async function search() {
    setLoading(true); setError(null);
    try { setResults((await searchShopProducts(query.trim(), catalog || undefined)).products); }
    catch (cause) { setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível buscar os produtos."); }
    finally { setLoading(false); }
  }

  function add(p: ShopProduct) {
    const at = carousel ? slide : 0;
    if (value.some((t) => t.product_id === p.product_id && t.slide === at)) { setActive(p.product_id); return; }
    if (value.filter((t) => t.slide === at).length >= PER_SLIDE) { setError(`No máximo ${PER_SLIDE} produtos por ${carousel ? "slide" : "post"}.`); return; }
    if (value.length >= limitFor(format)) { setError(`O Instagram aceita no máximo ${limitFor(format)} produtos neste formato.`); return; }
    setError(null);
    onChange([...value, { product_id: p.product_id, name: p.name, image_url: p.image_url, slide: at, x: 0.5, y: 0.5 }]);
    setActive(p.product_id);
  }

  function place(e: MouseEvent<HTMLDivElement>) {
    if (!active || disabled) return;
    const box = e.currentTarget.getBoundingClientRect();
    if (!box.width || !box.height) return;
    const clamp = (n: number) => Math.round(Math.min(1, Math.max(0.01, n)) * 1000) / 1000;
    const x = clamp((e.clientX - box.left) / box.width), y = clamp((e.clientY - box.top) / box.height);
    onChange(value.map((t) => (t.product_id === active && (!carousel || t.slide === slide) ? { ...t, x, y } : t)));
  }

  return <div className="collab productTags">
    <span className="postArtTitle"><ShoppingBag size={14} aria-hidden="true" /> Produtos da loja <em className="is-muted">Instagram Shopping</em></span>
    {story ? <small className="postArtHint is-pending">Stories não aceitam produto marcado: o Instagram publica sem a marcação.</small> : null}

    {value.length ? <ul className="productTagList">{value.map((t) => {
      const on = active === t.product_id && (!carousel || t.slide === slide);
      return <li key={`${t.product_id}-${t.slide}`} className={on ? "is-active" : ""}>
        <button type="button" className="productTagPick" disabled={disabled} onClick={() => { setActive(t.product_id); if (carousel) setSlide(t.slide); }}>
          {t.image_url ? <img src={t.image_url} alt="" loading="lazy" /> : <ShoppingBag size={16} aria-hidden="true" />}
          <span>{t.name || `Produto ${t.product_id}`}{carousel ? <small>slide {t.slide + 1}</small> : null}</span>
        </button>
        <button type="button" className="productTagRemove" aria-label={`Tirar ${t.name || "produto"}`} disabled={disabled}
          onClick={() => onChange(value.filter((x) => !(x.product_id === t.product_id && x.slide === t.slide)))}><X size={12} /></button>
      </li>;
    })}</ul> : null}

    {!story && shop === null ? <button type="button" className="ds-button" disabled={disabled || loading} onClick={() => void open()}>
      {loading ? "Consultando a loja…" : "Marcar produtos da loja"}</button> : null}

    {shop && !shop.ready ? <small className="postArtHint is-pending">{shop.message || "A loja do Instagram desta marca ainda não está pronta para marcar produtos."}</small> : null}

    {shop?.ready && !story ? <>
      {shop.missing_scopes.length ? <small className="postArtHint is-pending">A conexão ainda não tem todas as permissões de loja ({shop.missing_scopes.join(", ")}). Se a Meta recusar, o post sai sem as marcações.</small> : null}
      {carousel && slides.length > 1 ? <label className="productTagSlide">Slide
        <select value={slide} disabled={disabled} onChange={(e) => { setSlide(Number(e.target.value)); setActive(null); }}>
          {slides.map((_, i) => <option key={i} value={i}>{i + 1}{value.some((t) => t.slide === i) ? ` · ${value.filter((t) => t.slide === i).length} produto(s)` : ""}</option>)}
        </select></label> : null}
      <div className="postArtFromLink">
        {shop.catalogs.length > 1 ? <select aria-label="Catálogo" value={catalog} disabled={disabled} onChange={(e) => setCatalog(e.target.value)}>
          {shop.catalogs.map((c) => <option key={c.id} value={c.id}>{c.name || c.shop_name || c.id}</option>)}</select> : null}
        <input value={query} placeholder="Buscar produto (nome ou SKU)" aria-label="Buscar produto da loja" disabled={disabled}
          onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void search(); } }} />
        <button type="button" className="ds-button" disabled={disabled || loading} onClick={() => void search()}>{loading ? "Buscando…" : "Buscar"}</button>
      </div>
      {results ? (results.length ? <ul className="productResults">{results.map((p) => <li key={p.product_id}>
        <button type="button" disabled={disabled} onClick={() => add(p)}>
          {p.image_url ? <img src={p.image_url} alt="" loading="lazy" /> : <ShoppingBag size={18} aria-hidden="true" />}
          <span>{p.name}{p.sku ? <small>SKU {p.sku}</small> : null}
            {p.review_status && p.review_status !== "approved" ? <small className="is-pending">em revisão na Meta: só aparece no post depois de aprovado</small> : null}</span>
        </button>
      </li>)}</ul> : <small className="libHint">Nenhum produto encontrado.</small>) : null}

      {placeable && onSlide.length ? <div className="productTagStage">
        <small className="libHint">{active ? "Clique na arte para posicionar o produto selecionado." : "Escolha um produto acima e clique na arte para posicionar."}</small>
        <div className="productTagCanvas" role="presentation" onClick={place}>
          <img src={art!} alt="Arte do post" />
          {onSlide.map((t) => <span key={t.product_id} className={`productTagDot${active === t.product_id ? " is-active" : ""}`}
            style={{ left: `${t.x * 100}%`, top: `${t.y * 100}%` }} title={t.name || t.product_id}>{t.name || "Produto"}</span>)}
        </div>
      </div> : null}
      {video && value.length ? <small className="libHint">No Reels o produto aparece no botão de compra do vídeo (sem posição).</small> : null}
    </> : null}

    {error ? <small className="studioError">{error}</small> : null}
    <small className="libHint">Só produtos aprovados no catálogo aparecem no post. Se a Meta recusar as marcações, o post sai sem elas e a equipe é avisada no histórico.</small>
  </div>;
}
