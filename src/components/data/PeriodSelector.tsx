import DayPeriodControl from "../DayPeriodControl";
import SegmentedControl from "./SegmentedControl";

export type PeriodOptionId = "day" | "7d" | "30d" | "month" | "specific";

const OPTIONS: Array<{ id: PeriodOptionId; label: string }> = [
  { id: "day", label: "Dia" },
  { id: "7d", label: "7 dias" },
  { id: "30d", label: "30 dias" },
  { id: "month", label: "Este mês" },
  { id: "specific", label: "Mês específico" },
];

const MONTHS = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
];

type Props = {
  /** Opção em vigor; null quando o período não corresponde a nenhum atalho. */
  active: PeriodOptionId | null;
  onSelect: (id: PeriodOptionId) => void;
  month: number;
  year: number;
  years: number[];
  onMonthChange: (month: number) => void;
  onYearChange: (year: number) => void;
};

/**
 * Período das páginas que usam o PeriodContext (Meta, Google): mesmos
 * atalhos de antes, na linguagem do Ecommerce. "Dia" abre a navegação por
 * dia; "Mês específico" abre mês e ano. Quem decide o período é a página.
 */
export default function PeriodSelector({ active, onSelect, month, year, years, onMonthChange, onYearChange }: Props) {
  return (
    <>
      <SegmentedControl
        ariaLabel="Período"
        value={active ?? "custom"}
        onSelect={(id) => {
          // "Personalizado" só sinaliza o período em vigor; não é um atalho.
          if (id !== "custom") onSelect(id as PeriodOptionId);
        }}
        options={[
          ...OPTIONS.map((option) => (option.id === "specific" ? { ...option, expanded: active === "specific" } : option)),
          ...(active === null ? [{ id: "custom", label: "Personalizado" }] : []),
        ]}
      />
      {active === "day" ? <DayPeriodControl /> : null}
      {active === "specific" ? (
        <div className="ds-customPeriod">
          <label className="ds-field">
            <span>Mês</span>
            <select value={month} onChange={(event) => onMonthChange(Number(event.target.value))}>
              {MONTHS.map((label, index) => <option key={label} value={index + 1}>{label}</option>)}
            </select>
          </label>
          <label className="ds-field">
            <span>Ano</span>
            <select value={year} onChange={(event) => onYearChange(Number(event.target.value))}>
              {years.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
      ) : null}
    </>
  );
}
