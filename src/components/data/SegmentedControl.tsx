export type SegmentedOption = {
  id: string;
  label: string;
  /** Para opções que abrem um painel (ex.: "Personalizado"). */
  expanded?: boolean;
};

type Props = {
  options: SegmentedOption[];
  /** Opção ativa; null quando nenhuma corresponde. */
  value: string | null;
  onSelect: (id: string) => void;
  ariaLabel: string;
};

/** Grupo de opções com estado ativo evidente; rola na horizontal no mobile. */
export default function SegmentedControl({ options, value, onSelect, ariaLabel }: Props) {
  return (
    <div className="ds-segmented" role="group" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          aria-pressed={value === option.id}
          aria-expanded={option.expanded}
          onClick={() => onSelect(option.id)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
