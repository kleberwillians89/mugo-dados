/** Tira um quadro do vídeo (por volta de 1 s) como JPG, para servir de capa do anúncio. Devolve null se o navegador não conseguir ler o vídeo. */
export function videoCover(file: File, at = 1): Promise<Blob | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    let done = false;
    const finish = (blob: Blob | null) => { if (done) return; done = true; URL.revokeObjectURL(url); resolve(blob); };
    const timer = window.setTimeout(() => finish(null), 15000);
    video.muted = true; video.playsInline = true; video.preload = "auto"; video.src = url;
    video.onloadedmetadata = () => { video.currentTime = Math.min(at, Math.max(0, (video.duration || 0) / 2)); };
    video.onseeked = () => {
      try {
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth; canvas.height = video.videoHeight;
        const ctx = canvas.getContext("2d");
        if (!ctx || !canvas.width) { window.clearTimeout(timer); finish(null); return; }
        ctx.drawImage(video, 0, 0);
        canvas.toBlob((blob) => { window.clearTimeout(timer); finish(blob); }, "image/jpeg", 0.88);
      } catch { window.clearTimeout(timer); finish(null); }
    };
    video.onerror = () => { window.clearTimeout(timer); finish(null); };
  });
}
