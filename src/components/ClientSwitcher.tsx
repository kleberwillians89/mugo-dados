import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { Check, ChevronsUpDown } from "lucide-react";
import type { ClientMembership } from "../app/api";
import ClientBrand from "./ClientBrand";

type Props = {
  /**
   * Empresas que o usuário pode acessar — sempre as memberships já resolvidas
   * pelo App (bootstrap validado no backend). Este componente nunca acrescenta
   * empresas: o registro de marcas só fornece o logo de quem já está na lista.
   */
  clients: ClientMembership[];
  activeClientId: string;
  onChange: (clientId: string) => void;
};

// A partir de 5 empresas a busca aparece; abaixo disso a lista inteira cabe à vista.
const SEARCH_MIN_CLIENTS = 5;

export default function ClientSwitcher({ clients, activeClientId, onChange }: Props) {
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLUListElement | null>(null);
  const baseId = useId();
  const listId = `${baseId}-empresas`;
  const titleId = `${baseId}-titulo`;

  if (pendingId && pendingId === activeClientId) {
    // Ajuste em tempo de render: assim que o pai confirmar a troca via prop,
    // encerramos o estado "trocando" no mesmo ciclo, sem passar por useEffect.
    setPendingId(null);
  }

  // Clique/toque fora fecha o painel (sem depender de blur).
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent | TouchEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("touchstart", onPointerDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("touchstart", onPointerDown);
    };
  }, [open]);

  // Ao abrir, o foco vai para a busca (quando existe) ou para a empresa ativa.
  useEffect(() => {
    if (!open) return;
    const target =
      searchRef.current ||
      listRef.current?.querySelector<HTMLElement>('[aria-selected="true"]') ||
      listRef.current?.querySelector<HTMLElement>('[role="option"]');
    target?.focus();
  }, [open]);

  if (!clients.length) return null;
  const activeClient = clients.find((client) => client.client_id === activeClientId);
  const activeName = activeClient?.name || "Empresa";
  const pendingClient = pendingId ? clients.find((client) => client.client_id === pendingId) : null;

  // Uma empresa só: identidade, não um seletor.
  if (clients.length === 1) {
    return (
      <div className="clientSwitcher clientSwitcherStatic" role="group" aria-label={`Empresa ativa: ${activeName}`}>
        <ClientBrand
          inline
          size="compact"
          titleAs="span"
          clientId={activeClientId}
          clientName={activeName}
          nameClassName="clientSwitcherName"
        />
      </div>
    );
  }

  const needle = query.trim().toLowerCase();
  const filtered = needle ? clients.filter((client) => client.name.toLowerCase().includes(needle)) : clients;

  function close(returnFocus: boolean) {
    setOpen(false);
    setQuery("");
    if (returnFocus) triggerRef.current?.focus();
  }

  function select(clientId: string) {
    if (!open) return;
    // Mesmo contrato de antes: toda escolha passa pelo onChange do App.
    setPendingId(clientId);
    onChange(clientId);
    close(true);
  }

  function options(): HTMLElement[] {
    return [...(listRef.current?.querySelectorAll<HTMLElement>('[role="option"]') || [])];
  }

  function moveFocus(from: HTMLElement | null, step: number | "first" | "last") {
    const items = options();
    if (!items.length) return;
    const index = from ? items.indexOf(from) : -1;
    const next =
      step === "first" ? 0
        : step === "last" ? items.length - 1
          : index < 0 ? (step > 0 ? 0 : items.length - 1)
            : (index + step + items.length) % items.length;
    items[next]?.focus();
  }

  function onListKeyDown(event: KeyboardEvent<HTMLElement>) {
    const current = event.target as HTMLElement;
    if (event.key === "ArrowDown") { event.preventDefault(); moveFocus(current, 1); }
    else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (searchRef.current && options()[0] === current) searchRef.current.focus();
      else moveFocus(current, -1);
    }
    else if (event.key === "Home") { event.preventDefault(); moveFocus(current, "first"); }
    else if (event.key === "End") { event.preventDefault(); moveFocus(current, "last"); }
    else if (event.key === "Escape") { event.preventDefault(); close(true); }
  }

  return (
    <div
      ref={rootRef}
      className={`clientSwitcher${pendingClient ? " is-switching" : ""}${open ? " is-open" : ""}`}
      onBlur={(event) => {
        // Tab para fora do componente fecha o painel.
        if (open && rootRef.current && !rootRef.current.contains(event.relatedTarget as Node | null) && event.relatedTarget) {
          setOpen(false);
          setQuery("");
        }
      }}
    >
      <button
        ref={triggerRef}
        type="button"
        className="clientSwitcherTrigger"
        aria-label={pendingClient ? `Trocando para ${pendingClient.name}` : `Empresa ativa: ${activeName}. Trocar empresa`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        disabled={Boolean(pendingClient)}
        onClick={() => (open ? close(false) : setOpen(true))}
        onKeyDown={(event) => {
          if (event.key === "Escape" && open) { event.preventDefault(); close(true); }
          if ((event.key === "ArrowDown" || event.key === "ArrowUp") && !open) { event.preventDefault(); setOpen(true); }
        }}
      >
        {pendingClient ? (
          <span className="clientSwitcherName clientSwitcherPending" aria-live="polite">
            Trocando para {pendingClient.name}…
          </span>
        ) : (
          <ClientBrand
            inline
            size="compact"
            titleAs="span"
            clientId={activeClientId}
            clientName={activeName}
            nameClassName="clientSwitcherName"
          />
        )}
        <ChevronsUpDown className="clientSwitcherChevron" size={16} aria-hidden="true" />
      </button>

      {open ? (
        <div className="clientSwitcherPanel">
          <p className="clientSwitcherPanelTitle" id={titleId}>Empresas</p>
          {clients.length >= SEARCH_MIN_CLIENTS ? (
            <input
              ref={searchRef}
              type="search"
              className="clientSwitcherSearch"
              placeholder="Buscar empresa"
              aria-label="Buscar empresa"
              aria-controls={listId}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") { event.preventDefault(); close(true); }
                if (event.key === "ArrowDown") { event.preventDefault(); moveFocus(null, "first"); }
                if (event.key === "Enter" && filtered[0]) { event.preventDefault(); select(filtered[0].client_id); }
              }}
            />
          ) : null}
          {filtered.length === 0 ? (
            <p className="clientSwitcherEmpty" role="status">Nenhuma empresa encontrada.</p>
          ) : (
            <ul ref={listRef} id={listId} role="listbox" aria-labelledby={titleId} className="clientSwitcherList" onKeyDown={onListKeyDown}>
              {filtered.map((client) => {
                const active = client.client_id === activeClientId;
                return (
                  <li key={client.client_id} role="none">
                    <button
                      type="button"
                      role="option"
                      aria-selected={active}
                      className={`clientSwitcherOption${active ? " is-selected" : ""}`}
                      onMouseDown={(event) => {
                        // mousedown: seleciona antes de o foco sair do painel.
                        event.preventDefault();
                        select(client.client_id);
                      }}
                      onClick={() => select(client.client_id)}
                    >
                      <span className="clientSwitcherOptionName">{client.name}</span>
                      {active ? <Check className="clientSwitcherCheck" size={16} aria-hidden="true" /> : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
