import { useEffect, useRef, type ReactNode } from "react";

type Props = {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  width?: "md" | "lg";
};

export default function Drawer({ open, title, description, onClose, children, footer, width = "md" }: Props) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  // O pai costuma recriar onClose a cada render (ex.: a cada tecla digitada).
  // Guardá-lo numa ref impede que o efeito abaixo rode de novo e devolva o
  // foco ao painel no meio da digitação — o foco inicial acontece só ao abrir.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onCloseRef.current();
      if (event.key === "Tab") {
        const panel = panelRef.current;
        if (!panel) return;
        const focusable = panel.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    window.addEventListener("keydown", onKeyDown);
    // Respeita um campo com autoFocus já focado dentro do painel.
    const panel = panelRef.current;
    if (panel && !panel.contains(document.activeElement)) panel.focus();
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  if (!open) return null;

  return (
    <div className="drawerBackdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div
        className={`drawerPanel drawerPanel-${width}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={panelRef}
      >
        <div className="drawerHeader">
          <div>
            <h2>{title}</h2>
            {description ? <p>{description}</p> : null}
          </div>
          <button type="button" className="drawerClose" aria-label="Fechar" onClick={onClose}>×</button>
        </div>
        <div className="drawerBody">{children}</div>
        {footer ? <div className="drawerFooter">{footer}</div> : null}
      </div>
    </div>
  );
}
