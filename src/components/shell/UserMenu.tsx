import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { ChevronsUpDown } from "lucide-react";

type Props = {
  /** Nome exibido (metadado do perfil ou parte local do e-mail). */
  name: string;
  email?: string | null;
  /** Papel na empresa ativa, quando conhecido. */
  roleLabel?: string | null;
  onLogout: () => void | Promise<void>;
};

/**
 * Área do usuário: identidade uma vez só e as ações da conta. Só aparecem
 * opções que existem no produto hoje ("Sair"); "Minha conta" depende de uma
 * página que ainda não existe.
 */
export default function UserMenu({ name, email, roleLabel, onLogout }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const menuId = useId();
  const initial = (name || email || "?").trim().charAt(0).toUpperCase() || "?";

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent | TouchEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("touchstart", onPointerDown);
    menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("touchstart", onPointerDown);
    };
  }, [open]);

  function close(returnFocus: boolean) {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }

  function onMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const items = [...(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') || [])];
    const index = items.indexOf(event.target as HTMLElement);
    if (event.key === "Escape") { event.preventDefault(); close(true); }
    else if (event.key === "ArrowDown") { event.preventDefault(); items[(index + 1) % items.length]?.focus(); }
    else if (event.key === "ArrowUp") { event.preventDefault(); items[(index - 1 + items.length) % items.length]?.focus(); }
    else if (event.key === "Tab") setOpen(false);
  }

  return (
    <div className={`userMenu${open ? " is-open" : ""}`} ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="userMenuTrigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={`Conta de ${name}`}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === "Escape" && open) { event.preventDefault(); close(true); }
          if ((event.key === "ArrowDown" || event.key === "ArrowUp") && !open) { event.preventDefault(); setOpen(true); }
        }}
      >
        <span className="userMenuAvatar" aria-hidden="true">{initial}</span>
        <span className="userMenuName">{name}</span>
        <ChevronsUpDown className="userMenuChevron" size={16} aria-hidden="true" />
      </button>
      {open ? (
        <div ref={menuRef} id={menuId} className="userMenuPanel" role="menu" aria-label="Conta" onKeyDown={onMenuKeyDown}>
          <div className="userMenuIdentity">
            <span className="userMenuIdentityName">{name}</span>
            {email && email !== name ? <span className="userMenuIdentityDetail">{email}</span> : null}
            {roleLabel ? <span className="userMenuIdentityDetail">{roleLabel}</span> : null}
          </div>
          <button
            type="button"
            role="menuitem"
            className="userMenuItem"
            onClick={() => {
              setOpen(false);
              void onLogout();
            }}
          >
            Sair
          </button>
        </div>
      ) : null}
    </div>
  );
}
