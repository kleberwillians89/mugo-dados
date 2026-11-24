import { useEffect, useRef, useState } from "react";
import { Music, Pause, Play, Search, X } from "lucide-react";
import { STUDIO_FORMATS, searchReelsAudio, type ReelsAudio, type ReelsMusic, type StudioFormat } from "../../app/studio";

type Props = {
  value?: ReelsMusic; onChange: (next: ReelsMusic | undefined) => void; disabled?: boolean;
  /** Formato da pauta: só o Reels recebe a música pela API; nos outros ela fica anotada para a equipe pôr no app. */
  format?: StudioFormat;
  manualNote?: string;
  onManualNote?: (note: string) => void;
};

const time = (ms: number | null) => {
  if (!ms) return "";
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

/**
 * Música do post pela biblioteca do Instagram. Sem busca, mostra o que está em alta.
 * A Meta só libera para apps parte do catálogo do app; o volume da música e do som do vídeo vai junto.
 * No Reels a música vai na publicação automática; em Stories, imagem e carrossel a API da Meta não aceita música,
 * então ela fica na pauta e o post vira publicação à mão (a equipe põe a música no app do Instagram).
 */
export default function ReelsMusicPicker({ value, onChange, disabled, format = "reels", manualNote = "", onManualNote }: Props) {
  const autoMusic = format === "reels" || format === "video";
  const story = format === "stories";
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<"music" | "original_sound">("music");
  const [results, setResults] = useState<ReelsAudio[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const player = useRef<HTMLAudioElement | null>(null);
  const searchVersion = useRef(0);

  async function search(q = query, type = kind) {
    const version = ++searchVersion.current;
    setBusy(true); setError(null); setResults([]);
    try {
      const found = await searchReelsAudio(q.trim(), type);
      if (version === searchVersion.current) setResults(found.audio);
    } catch (cause) {
      if (version === searchVersion.current) {
        setError(cause instanceof Error ? cause.message : "Não foi possível buscar músicas.");
        setResults([]);
      }
    } finally {
      if (version === searchVersion.current) setBusy(false);
    }
  }

  useEffect(() => () => { searchVersion.current += 1; player.current?.pause(); }, []);
  useEffect(() => { if (open && !results.length && !busy && !error) void search("", kind); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  function toggle(audio: ReelsAudio) {
    if (!audio.preview_url) return;
    if (playing === audio.audio_id) { player.current?.pause(); setPlaying(null); return; }
    player.current?.pause();
    player.current = new Audio(audio.preview_url);
    player.current.onended = () => setPlaying(null);
    void player.current.play().catch(() => setPlaying(null));
    setPlaying(audio.audio_id);
  }

  function choose(audio: ReelsAudio) {
    player.current?.pause(); setPlaying(null);
    onChange({ audio_id: audio.audio_id, title: audio.title, artist: audio.artist, cover: audio.cover,
      audio_volume: value?.audio_volume ?? 100, video_volume: value?.video_volume ?? 30 });
    setOpen(false);
  }

  return <section className="reelsOptsBlock" aria-labelledby="reels-music-title">
    <span className="postArtTitle" id="reels-music-title">Música {story ? "do Story" : ""}</span>
    {story && onManualNote ? <label>Faixa que você quer usar no Instagram (nome original e artista)
      <input type="text" maxLength={200} placeholder="Ex.: Magnólia — Ben" disabled={disabled}
        value={manualNote} onChange={(e) => onManualNote(e.target.value)} />
      <small className="postArtHint">Você pode escrever a música exata mesmo que ela não apareça na biblioteca limitada da Meta. A equipe adicionará a faixa no aplicativo Instagram antes de publicar.</small>
    </label> : null}
    {value ? <div className="reelsMusicPicked">
      {value.cover ? <img src={value.cover} alt="" /> : <span className="reelsMusicIcon"><Music size={18} aria-hidden="true" /></span>}
      <div><b>{value.title || "Música escolhida"}</b>{value.artist ? <small>{value.artist}</small> : null}</div>
      <button type="button" className="studioLink" disabled={disabled} onClick={() => onChange(undefined)} aria-label="Tirar a música"><X size={15} /> Tirar</button>
    </div> : null}
    {value && autoMusic ? <div className="reelsMusicVolumes">
      <label>Volume da música <b>{value.audio_volume ?? 100}%</b>
        <input type="range" min={1} max={100} value={value.audio_volume ?? 100} disabled={disabled}
          onChange={(e) => onChange({ ...value, audio_volume: Number(e.target.value) })} /></label>
      <label>Som do vídeo <b>{value.video_volume ?? 100}%</b>
        <input type="range" min={1} max={100} value={value.video_volume ?? 100} disabled={disabled}
          onChange={(e) => onChange({ ...value, video_volume: Number(e.target.value) })} /></label>
    </div> : null}
    <button type="button" className="ds-button" disabled={disabled} aria-expanded={open} onClick={() => setOpen(!open)}>
      <Music size={15} aria-hidden="true" /> {open ? "Fechar músicas" : value ? "Trocar música" : "Escolher música do Instagram"}</button>

    {open ? <div className="reelsMusicBox">
      <div className="reelsSeg" role="group" aria-label="Tipo de áudio">
        {(["music", "original_sound"] as const).map((t) => <button key={t} type="button" className={kind === t ? "is-on" : ""} aria-pressed={kind === t}
          onClick={() => { setKind(t); void search(query, t); }}>{t === "music" ? "Músicas" : "Áudios de Reels"}</button>)}
      </div>
      {/* div, não <form>: o modal já é um formulário e form dentro de form enviava a página (recarregava o Mugoverso). */}
      <div className="reelsMusicSearch" role="search">
        <input type="search" value={query} placeholder="Nome da música ou artista (vazio = em alta)" aria-label="Buscar música"
          onChange={(e) => { searchVersion.current += 1; setQuery(e.target.value); setResults([]); setBusy(false); setError(null); }} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void search(); } }} />
        <button type="button" className="ds-button" disabled={busy} onClick={() => void search()}><Search size={15} aria-hidden="true" /> {busy ? "Buscando…" : "Buscar"}</button>
      </div>
      {error ? <small className="studioError" role="alert">{error}</small> : null}
      {!busy && !error && !results.length ? <small className="libHint">{query.trim() ? "Nenhum áudio correspondente foi encontrado no catálogo liberado pela Meta. Tente título ou artista; não será sugerida uma música diferente." : "Nenhuma música disponibilizada pela Meta para esta conta."}</small> : null}
      <ul className="reelsMusicList">{results.map((a) => <li key={a.audio_id} className={value?.audio_id === a.audio_id ? "is-on" : ""}>
        {a.cover ? <img src={a.cover} alt="" loading="lazy" /> : <span className="reelsMusicIcon"><Music size={16} aria-hidden="true" /></span>}
        <div><b>{a.title}</b><small>{[a.artist, time(a.duration_ms)].filter(Boolean).join(" · ")}</small></div>
        {a.preview_url ? <button type="button" className="ds-button" aria-label={playing === a.audio_id ? `Pausar ${a.title}` : `Ouvir ${a.title}`}
          onClick={() => toggle(a)}>{playing === a.audio_id ? <Pause size={15} /> : <Play size={15} />}</button> : null}
        <button type="button" className="ds-button is-primary" disabled={disabled} onClick={() => choose(a)}>Usar</button>
      </li>)}</ul>
      <small className="libHint">A busca consulta apenas as faixas disponibilizadas pela Meta, não todo o catálogo do Instagram. Não substituímos a música pedida por outra. Em Stories, escreva o nome original acima para a equipe adicionar manualmente.</small>
    </div> : null}
    {value && !autoMusic ? <small className="postArtHint is-pending">A Meta só põe música sozinha no Reels. Em {STUDIO_FORMATS[format] || format} a música fica
      anotada na pauta e, na hora marcada, o post fica para <b>publicar à mão</b> no app do Instagram com essa música.</small> : null}
  </section>;
}
