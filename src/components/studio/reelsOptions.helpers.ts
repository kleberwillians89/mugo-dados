/** Ajudantes da capa do Reels (fora do componente para o Fast Refresh). */

/** "3500" → "0:03,5" */
export function formatOffset(ms: number): string {
  const total = Math.max(0, ms) / 1000;
  const minutes = Math.floor(total / 60);
  const seconds = (total - minutes * 60).toFixed(1).replace(".", ",");
  return `${minutes}:${seconds.length < 4 ? `0${seconds}` : seconds}`;
}

/** Link do vídeo mostrando um momento: o navegador pinta esse frame sem tocar o vídeo. */
export function frameSrc(url: string, ms: number): string {
  return `${url.split("#")[0]}#t=${(Math.max(0, ms) / 1000).toFixed(1)}`;
}

export function isJpeg(url: string): boolean {
  return /\.jpe?g$/i.test(url.split("?")[0]) || /^https:\/\/drive\.google\.com\/(file\/d\/|open\?id=|uc\?)/.test(url);
}
