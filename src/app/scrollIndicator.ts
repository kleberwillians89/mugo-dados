/** Marca <html class="is-scrolling"> enquanto qualquer área rola: a barra de rolagem só aparece nessa hora. */
export function installScrollIndicator(win: Window = window): () => void {
  let timer: number | undefined;
  const root = win.document.documentElement;
  const onScroll = () => {
    root.classList.add("is-scrolling");
    if (timer) win.clearTimeout(timer);
    timer = win.setTimeout(() => root.classList.remove("is-scrolling"), 900);
  };
  win.addEventListener("scroll", onScroll, { capture: true, passive: true });
  return () => { win.removeEventListener("scroll", onScroll, { capture: true }); if (timer) win.clearTimeout(timer); };
}
