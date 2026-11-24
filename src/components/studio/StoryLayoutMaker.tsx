import { useState } from "react";

type Layout = "texto" | "gradiente" | "colagem";
type Props = { disabled?: boolean; onGenerate: (file: File) => Promise<void> };

const palettes = [
  { name: "Azul Mugô", colors: ["#0c4160", "#004f6e"] },
  { name: "Escuro", colors: ["#111821", "#303848"] },
  { name: "Areia", colors: ["#e9decb", "#c79830"] },
];

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => { URL.revokeObjectURL(url); resolve(image); };
    image.onerror = () => { URL.revokeObjectURL(url); reject(new Error("Não foi possível abrir a imagem.")); };
    image.src = url;
  });
}

function cover(ctx: CanvasRenderingContext2D, image: HTMLImageElement, x: number, y: number, w: number, h: number) {
  const scale = Math.max(w / image.naturalWidth, h / image.naturalHeight);
  const sw = image.naturalWidth * scale;
  const sh = image.naturalHeight * scale;
  ctx.drawImage(image, x + (w - sw) / 2, y + (h - sh) / 2, sw, sh);
}

function wrap(ctx: CanvasRenderingContext2D, message: string, maxWidth: number): string[] {
  const lines: string[] = [];
  for (const paragraph of message.split("\n")) {
    let line = "";
    for (const word of paragraph.split(/\s+/).filter(Boolean)) {
      const next = line ? line + " " + word : word;
      if (ctx.measureText(next).width > maxWidth && line) { lines.push(line); line = word; }
      else line = next;
    }
    lines.push(line);
  }
  return lines.slice(0, 9);
}

export default function StoryLayoutMaker({ disabled, onGenerate }: Props) {
  const [layout, setLayout] = useState<Layout>("texto");
  const [title, setTitle] = useState("");
  const [palette, setPalette] = useState(0);
  const [photos, setPhotos] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    if (busy || disabled) return;
    setBusy(true); setError(null);
    try {
      const canvas = document.createElement("canvas");
      canvas.width = 1080; canvas.height = 1920;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Seu navegador não conseguiu gerar a arte.");
      const gradient = ctx.createLinearGradient(0, 0, 1080, 1920);
      gradient.addColorStop(0, palettes[palette].colors[0]);
      gradient.addColorStop(1, palettes[palette].colors[1]);
      ctx.fillStyle = gradient; ctx.fillRect(0, 0, 1080, 1920);
      if (layout === "gradiente") {
        ctx.fillStyle = "rgba(255,255,255,.07)";
        ctx.beginPath(); ctx.arc(900, 300, 550, 0, Math.PI * 2); ctx.fill();
        ctx.beginPath(); ctx.arc(150, 1600, 450, 0, Math.PI * 2); ctx.fill();
      }
      if (layout === "colagem") {
        if (photos.length !== 2) throw new Error("Escolha duas fotos para a colagem.");
        const [one, two] = await Promise.all(photos.map(loadImage));
        cover(ctx, one, 0, 0, 1080, 955);
        cover(ctx, two, 0, 965, 1080, 955);
        ctx.fillStyle = "rgba(0,0,0,.3)"; ctx.fillRect(0, 0, 1080, 1920);
      }
      if (title.trim()) {
        const white = layout !== "texto" || palette !== 2;
        ctx.fillStyle = white ? "#fff" : "#20242b";
        ctx.font = "bold 82px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const lines = wrap(ctx, title.trim(), 870);
        const lineHeight = 106;
        lines.forEach((line, i) => ctx.fillText(line, 540, 960 + (i - (lines.length - 1) / 2) * lineHeight, 900));
      }
      const blob = await new Promise<Blob>((resolve, reject) =>
        canvas.toBlob((b) => b ? resolve(b) : reject(new Error("Não foi possível criar o PNG.")), "image/png"));
      await onGenerate(new File([blob], "mugoverso-story.png", { type: "image/png" }));
    } catch (err) { setError(err instanceof Error ? err.message : "Erro ao gerar arte."); }
    finally { setBusy(false); }
  }

  return <div className="storyLayoutMaker" aria-label="Criar arte do Story">
    <strong>Ou crie um Story aqui</strong>
    <div className="storyLayoutChoices" role="group" aria-label="Layout do Story">
      {(["texto", "gradiente", "colagem"] as const).map((mode) =>
        <button type="button" key={mode} className={layout === mode ? "is-on" : ""} aria-pressed={layout === mode}
          onClick={() => setLayout(mode)} disabled={disabled}>
          {mode === "texto" ? "Texto" : mode === "gradiente" ? "Gradiente" : "Colagem (2 fotos)"}
        </button>)}
    </div>
    <label>Texto sobre a arte (opcional)
      <textarea rows={2} maxLength={180} placeholder="Escreva a frase do Story" value={title}
        disabled={disabled} onChange={(event) => setTitle(event.target.value)} />
    </label>
    <label>Paleta
      <select value={palette} disabled={disabled} onChange={(e) => setPalette(Number(e.target.value))}>
        {palettes.map((p, i) => <option value={i} key={p.name}>{p.name}</option>)}
      </select>
    </label>
    {layout === "colagem" ? <label>Duas imagens para a colagem
      <input type="file" accept="image/jpeg,image/png,image/webp" multiple disabled={disabled}
        onChange={(e) => setPhotos(Array.from(e.target.files || []).slice(0, 2))} />
      <small>{photos.length} de 2 imagens selecionadas</small>
    </label> : null}
    <button type="button" className="ds-button is-primary" onClick={() => void generate()}
      disabled={disabled || busy || (layout === "colagem" && photos.length !== 2) || (layout !== "colagem" && !title.trim())}>
      {busy ? "Criando arte…" : "Gerar arte 9:16 e adicionar à pauta"}
    </button>
    {error ? <small className="studioError" role="alert">{error}</small> : null}
    <small className="postArtHint">Gera um PNG real para publicação. Boomerang, efeitos e filtros nativos do Instagram não são reproduzidos pela API.</small>
  </div>;
}
