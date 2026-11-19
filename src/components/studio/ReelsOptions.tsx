import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { uploadArt } from "../../app/artUpload";
import type { ReelsOptions as Options } from "../../app/studio";
import { formatOffset, frameSrc, isJpeg } from "./reelsOptions.helpers";

/** Momentos sugeridos na faixa de frames (o ajuste fino vai de 0,1 em 0,1 s). */
const STRIP = 6;
const MAX_MS = 15 * 60 * 1000;

type Props = {
  value: Options;
  onChange: (next: Options) => void;
  /** Primeiro arquivo da arte, quando é vídeo (sem ele, a capa por frame fica esperando o vídeo). */
  videoUrl: string | null;
  itemId: string | null;
  disabled?: boolean;
};

/**
 * Capa e opções do Reels no modal do post. Vale só para Reels no Instagram; tudo vai junto na publicação
 * automática (capa por frame = thumb_offset; capa por imagem = cover_url, que vence o frame).
 */
export default function ReelsOptions({ value, onChange, videoUrl, itemId, disabled }: Props) {
  const mode = value.cover_mode || "frame";
  const offset = value.thumb_offset_ms ?? 0;
  const [duration, setDuration] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [coverLink, setCoverLink] = useState("");
  const set = (patch: Partial<Options>) => onChange({ ...value, ...patch });
  const maxMs = Math.min(MAX_MS, duration ? Math.floor(duration * 1000) - 100 : MAX_MS);
  const strip = duration ? Array.from({ length: STRIP }, (_, i) => Math.round((i * Math.max(0, maxMs)) / STRIP / 100) * 100) : [];

  useEffect(() => { setDuration(null); }, [videoUrl]);

  const seek = (ms: number) => set({ cover_mode: "frame", thumb_offset_ms: Math.max(0, Math.min(maxMs, Math.round(ms / 100) * 100)) });

  async function sendCover(file: File | undefined) {
    if (!file) return;
    if (!file.type.startsWith("image/")) { setError("A capa precisa ser uma imagem (JPG ou PNG, que vira JPG)."); return; }
    setError(null); setUploading(true);
    try { set({ cover_mode: "image", cover_url: await uploadArt(itemId, file) }); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível enviar a capa."); }
    finally { setUploading(false); }
  }

  function applyLink() {
    const link = coverLink.trim();
    if (!/^https:\/\/\S+$/.test(link)) { setError("Cole um link https da imagem (arquivo do Drive ou JPG)."); return; }
    if (!isJpeg(link)) { setError("A Meta só aceita capa em JPG: envie o arquivo aqui ou use o link do arquivo no Drive."); return; }
    setError(null); setCoverLink(""); set({ cover_mode: "image", cover_url: link });
  }

  return <div className="reelsOpts">
    <section className="reelsOptsBlock" aria-labelledby="reels-cover-title">
      <span className="postArtTitle" id="reels-cover-title">Capa do Reels</span>
      <div className="reelsSeg" role="group" aria-label="Origem da capa">
        <button type="button" className={mode === "frame" ? "is-on" : ""} aria-pressed={mode === "frame"} disabled={disabled}
          onClick={() => set({ cover_mode: "frame" })}>Frame do vídeo</button>
        <button type="button" className={mode === "image" ? "is-on" : ""} aria-pressed={mode === "image"} disabled={disabled}
          onClick={() => set({ cover_mode: "image" })}>Imagem de capa</button>
      </div>

      {mode === "frame" ? (videoUrl ? <div className="reelsFrame">
        {/* Só lê a duração; os quadros abaixo usam o mesmo link com #t= (o navegador pinta o frame). */}
        <video className="reelsProbe" src={videoUrl} preload="metadata" muted playsInline aria-hidden="true"
          onLoadedMetadata={(e) => setDuration(Number.isFinite(e.currentTarget.duration) ? e.currentTarget.duration : null)} />
        {strip.length ? <div className="reelsStrip">
          {strip.map((ms) => <button type="button" key={ms} className={Math.abs(ms - offset) < 50 ? "is-on" : ""} disabled={disabled}
            aria-label={`Usar o frame em ${formatOffset(ms)}`} onClick={() => seek(ms)}>
            <video src={frameSrc(videoUrl, ms)} preload="metadata" muted playsInline aria-hidden="true" tabIndex={-1} />
            <span>{formatOffset(ms)}</span>
          </button>)}
        </div> : <small className="libHint">Carregando o vídeo…</small>}
        <div className="reelsFine">
          <button type="button" className="ds-button" aria-label="Voltar 0,1 segundo" disabled={disabled || offset <= 0} onClick={() => seek(offset - 100)}><ChevronLeft size={16} /></button>
          <input type="range" min={0} max={Math.max(0, maxMs)} step={100} value={Math.min(offset, Math.max(0, maxMs))} disabled={disabled || !duration}
            aria-label="Momento do vídeo usado como capa" onChange={(e) => seek(Number(e.target.value))} />
          <button type="button" className="ds-button" aria-label="Avançar 0,1 segundo" disabled={disabled || offset >= maxMs} onClick={() => seek(offset + 100)}><ChevronRight size={16} /></button>
        </div>
        <small className="libHint">Capa em <b>{formatOffset(offset)}</b>{value.thumb_offset_ms === undefined ? " (primeiro frame, até você escolher)" : ""}.</small>
      </div> : <small className="libHint">Envie o vídeo do Reels na arte para escolher o frame da capa.</small>) : null}

      {mode === "image" ? <div className="reelsImage">
        {value.cover_url ? <div className="reelsCoverPicked">
          <img src={value.cover_url} alt="Capa escolhida" />
          <div><b>Capa escolhida</b><small className="libHint">Ela vence o frame. Na grade do perfil aparece o centro da imagem.</small>
            <button type="button" className="studioLink" disabled={disabled} onClick={() => set({ cover_url: undefined })}>Tirar a capa</button></div>
        </div> : null}
        <label className={`postArtDrop${uploading ? " is-busy" : ""}`}>
          <b>{uploading ? "Enviando a capa…" : "Arraste a capa aqui ou clique para escolher"}</b>
          <small>JPG 1080 × 1920 (9:16), feito pela equipe. PNG vira JPG antes de subir.</small>
          <input type="file" accept="image/*" disabled={disabled || uploading} onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; void sendCover(f); }} />
        </label>
        <div className="postArtFromLink">
          <input type="url" value={coverLink} placeholder="ou cole o link do arquivo no Drive" aria-label="Link da capa"
            disabled={disabled} onChange={(e) => { setCoverLink(e.target.value); setError(null); }}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); applyLink(); } }} />
          <button type="button" className="ds-button" disabled={disabled || !coverLink.trim()} onClick={applyLink}>Usar link</button>
        </div>
      </div> : null}
      {error ? <small className="studioError" role="alert">{error}</small> : null}
    </section>

    <section className="reelsOptsBlock" aria-labelledby="reels-where-title">
      <span className="postArtTitle" id="reels-where-title">Onde aparece</span>
      <label className="reelsCheck">
        <input type="checkbox" checked={value.share_to_feed ?? true} disabled={disabled} onChange={(e) => set({ share_to_feed: e.target.checked })} />
        Mostrar também no Feed e na grade do perfil
      </label>
      <label className="reelsCheck">
        <input type="checkbox" checked={Boolean(value.trial && value.trial !== "off")} disabled={disabled}
          onChange={(e) => set({ trial: e.target.checked ? "manual" : "off" })} />
        Reels de teste (primeiro só para quem não segue a marca)
      </label>
      {value.trial && value.trial !== "off" ? <label>Depois do teste
        <select value={value.trial} disabled={disabled} onChange={(e) => set({ trial: e.target.value as Options["trial"] })}>
          <option value="manual">A equipe decide no Instagram se vai para os seguidores</option>
          <option value="auto">Vai sozinho para os seguidores se performar bem</option>
        </select></label> : null}
      <label>Nome do áudio original
        <input maxLength={100} value={value.audio_name || ""} placeholder="Áudio original" disabled={disabled}
          onChange={(e) => set({ audio_name: e.target.value || undefined })} /></label>
      <label>Primeiro comentário
        <textarea rows={2} maxLength={2200} value={value.first_comment || ""} disabled={disabled}
          placeholder="Sai logo depois da publicação (link, cupom, hashtags extras)"
          onChange={(e) => set({ first_comment: e.target.value || undefined })} /></label>
      <small className="libHint">Música da biblioteca do Instagram, texto, figurinha e filtro não vão pela API: precisam vir prontos no vídeo.</small>
    </section>
  </div>;
}
