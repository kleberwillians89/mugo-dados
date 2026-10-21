import { useEffect, useRef, type ReactNode } from "react";

type Props = {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
};

export default function Modal({ open, title, onClose, children }: Props) {
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  useEffect(() => {close.current = onClose;}, [onClose]);
  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusable = () => [...(panel.current?.querySelectorAll<HTMLElement>("*") || [])].filter(node => node.tabIndex >= 0 && !node.matches(':disabled') && !node.closest('[hidden], [inert]'));
    (focusable()[0] || panel.current)?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") close.current();
      if (event.key === "Tab") {
        const nodes = focusable();
        const first = nodes[0] || panel.current, last = nodes[nodes.length - 1] || panel.current;
        if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last?.focus();}
        else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus();}
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => {window.removeEventListener("keydown", onKeyDown); document.body.style.overflow = previousOverflow; if (previousFocus?.isConnected) previousFocus.focus();};
  }, [open]);

  if (!open) return null;

  return (
    <div className="modalBackdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={panel} tabIndex={-1} className="modalPanel" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modalHeader">
          <h2>{title}</h2>
          <button type="button" className="modalClose" aria-label="Fechar" onClick={onClose}>×</button>
        </div>
        <div className="modalBody">{children}</div>
      </div>
    </div>
  );
}
