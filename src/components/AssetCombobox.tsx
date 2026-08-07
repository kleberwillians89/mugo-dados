import { useId, useMemo, useRef, useState } from "react";
import type { StatusTone } from "./StatusBadge";
import StatusBadge from "./StatusBadge";

export type AssetComboboxOption = {
  value: string;
  label: string;
  subtitle?: string;
  meta?: string;
  status?: { label: string; tone: StatusTone };
};

type Props = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: AssetComboboxOption[];
  placeholder?: string;
  loading?: boolean;
  disabled?: boolean;
  error?: string | null;
  emptyMessage?: string;
};

function normalize(value: string): string {
  return value.trim().toLowerCase();
}

export default function AssetCombobox({
  label,
  value,
  onChange,
  options,
  placeholder = "Buscar...",
  loading = false,
  disabled = false,
  error = null,
  emptyMessage = "Nenhum item encontrado.",
}: Props) {
  const baseId = useId();
  const listboxId = `${baseId}-listbox`;
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);

  const selected = options.find((option) => option.value === value) || null;

  const filtered = useMemo(() => {
    const needle = normalize(query);
    if (!needle) return options;
    return options.filter((option) =>
      normalize(option.label).includes(needle) ||
      normalize(option.subtitle || "").includes(needle) ||
      normalize(option.meta || "").includes(needle)
    );
  }, [options, query]);

  function openList() {
    if (disabled) return;
    setOpen(true);
    setHighlight(0);
  }

  function closeList() {
    setOpen(false);
    setQuery("");
  }

  function selectOption(option: AssetComboboxOption) {
    onChange(option.value);
    closeList();
    inputRef.current?.blur();
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (disabled) return;
    if (!open && (event.key === "ArrowDown" || event.key === "Enter")) {
      event.preventDefault();
      openList();
      return;
    }
    if (!open) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlight((current) => Math.min(current + 1, filtered.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlight((current) => Math.max(current - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const option = filtered[highlight];
      if (option) selectOption(option);
    } else if (event.key === "Escape") {
      event.preventDefault();
      closeList();
    }
  }

  const activeOptionId = open && filtered[highlight] ? `${baseId}-option-${filtered[highlight].value}` : undefined;
  const displayValue = open ? query : selected ? selected.label : "";

  return (
    <div className={`assetCombobox${disabled ? " is-disabled" : ""}${error ? " is-error" : ""}`}>
      {label ? <label className="assetComboboxLabel" htmlFor={`${baseId}-input`}>{label}</label> : null}
      <div className="assetComboboxField">
        <input
          id={`${baseId}-input`}
          ref={inputRef}
          role="combobox"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-activedescendant={activeOptionId}
          aria-autocomplete="list"
          autoComplete="off"
          disabled={disabled}
          placeholder={selected ? selected.label : placeholder}
          value={displayValue}
          onFocus={openList}
          onClick={openList}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
            setHighlight(0);
          }}
          onKeyDown={onKeyDown}
          onBlur={() => {
            // Pequeno atraso para permitir o clique numa opção antes de fechar.
            window.setTimeout(() => closeList(), 120);
          }}
        />
        {loading ? <span className="assetComboboxSpinner" aria-hidden="true" /> : null}
      </div>
      {error ? <p className="assetComboboxError" role="alert">{error}</p> : null}
      {open ? (
        <ul className="assetComboboxList" role="listbox" id={listboxId}>
          {loading ? (
            <li className="assetComboboxStatus">Carregando...</li>
          ) : filtered.length === 0 ? (
            <li className="assetComboboxStatus">{emptyMessage}</li>
          ) : (
            filtered.map((option, index) => (
              <li
                key={option.value}
                id={`${baseId}-option-${option.value}`}
                role="option"
                aria-selected={option.value === value}
                className={`assetComboboxOption${index === highlight ? " is-highlighted" : ""}${option.value === value ? " is-selected" : ""}`}
                onMouseDown={(event) => {
                  event.preventDefault();
                  selectOption(option);
                }}
                onMouseEnter={() => setHighlight(index)}
              >
                <div className="assetComboboxOptionText">
                  <strong>{option.label}</strong>
                  {option.subtitle ? <span>{option.subtitle}</span> : null}
                  {option.meta ? <small>{option.meta}</small> : null}
                </div>
                {option.status ? <StatusBadge label={option.status.label} tone={option.status.tone} /> : null}
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  );
}
