import { useState } from "react";
import { usePeriod } from "../../app/PeriodContext";
import { countSelectedPeriodDays } from "../../app/periodRange";
import DayPeriodControl from "../DayPeriodControl";
import SegmentedControl from "./SegmentedControl";

export type PeriodOptionId = "day" | "7d" | "30d" | "month" | "specific";

const OPTIONS: Array<{ id: PeriodOptionId; label: string }> = [
  { id: "day", label: "Dia" },
  { id: "7d", label: "7 dias" },
  { id: "30d", label: "30 dias" },
  { id: "month", label: "Mês atual" },
  { id: "specific", label: "Mês específico" },
];

const MONTHS = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
];

type Props = {
  /** Opção em vigor; null quando o período não corresponde a nenhum atalho. */
  active?: PeriodOptionId | null;
  onSelect?: (id: PeriodOptionId) => void;
  month?: number;
  year?: number;
  years?: number[];
  onMonthChange?: (month: number) => void;
  onYearChange?: (year: number) => void;
};

/**
 * Seletor compartilhado de Meta, Google e Inteligência. Os novos atalhos
 * atualizam o PeriodContext; callbacks mantêm a seleção de mês existente.
 */
export default function PeriodSelector({ active, onSelect, month, year, years = [], onMonthChange, onYearChange }: Props = {}) {
  const context = usePeriod();
  const [custom, setCustom] = useState(false);
  const [draft, setDraft] = useState(context.period);
  const [error, setError] = useState("");
  const selectedDays = countSelectedPeriodDays(context.period);
  const now = new Date();
  const format = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  const previousStart = format(new Date(now.getFullYear(), now.getMonth() - 1, 1));
  const previousEnd = format(new Date(now.getFullYear(), now.getMonth(), 0));
  const currentStart = format(new Date(now.getFullYear(), now.getMonth(), 1));
  const selectedEnd = new Date(`${context.period.end}T12:00:00`);
  const fixedMonth = context.period.start === format(new Date(selectedEnd.getFullYear(), selectedEnd.getMonth(), 1)) && context.period.end === format(new Date(selectedEnd.getFullYear(), selectedEnd.getMonth() + 1, 0));
  const value = custom ? "custom" : context.period.start === previousStart && context.period.end === previousEnd ? "previous"
    : context.period.start === currentStart && context.period.end === format(now) ? "month"
    : selectedDays === 90 ? "90d" : selectedDays === 7 ? "7d" : selectedDays === 30 ? "30d" : selectedDays === 1 ? "day" : active === "specific" && fixedMonth ? "specific" : "custom";
  function select(id: string) {
    setError("");
    setCustom(id === "custom");
    if (id === "custom") { setDraft(context?.period ?? draft); return; }
    if (id === "90d") { context?.setPresetPeriod(90); return; }
    if (id === "previous") {
      const now = new Date();
      const previous = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      context?.setMonthPeriod(previous.getFullYear(), previous.getMonth() + 1);
      return;
    }
    if (onSelect) { onSelect(id as PeriodOptionId); return; }
    if (id === "7d" || id === "30d") context?.setPresetPeriod(id === "7d" ? 7 : 30);
    else if (id === "month") context?.setCurrentMonthPeriod();
    else if (id === "day" && context) context.setDayPeriod(context.period.end);
  }
  function applyCustom() {
    const days = countSelectedPeriodDays(draft);
    if (!draft.start || !draft.end || draft.start > draft.end || days > 90) {
      setError("Selecione um período de 1 a 90 dias."); return;
    }
    context?.setPeriod(draft);
  }
  return (
    <>
      <SegmentedControl
        ariaLabel="Período"
        value={value}
        onSelect={select}
        options={[
          ...OPTIONS.filter(option => option.id !== "specific" || onSelect).map((option) => (option.id === "specific" ? { ...option, expanded: active === "specific" } : option)),
          { id: "90d", label: "90 dias" },
          { id: "previous", label: "Mês anterior" },
          { id: "custom", label: "Personalizado" },
        ]}
      />
      {value === "custom" ? <div className="ds-customPeriod">
        <label className="ds-field">Início<input type="date" value={draft.start} onChange={event => setDraft({ ...draft, start: event.target.value })} /></label>
        <label className="ds-field">Fim<input type="date" value={draft.end} onChange={event => setDraft({ ...draft, end: event.target.value })} /></label>
        <button type="button" className="btn" onClick={applyCustom}>Aplicar período</button>
        {error ? <p role="alert">{error}</p> : null}
      </div> : null}
      {value === "day" ? <DayPeriodControl /> : null}
      {value === "specific" ? (
        <div className="ds-customPeriod">
          <label className="ds-field">
            <span>Mês</span>
            <select value={month} onChange={(event) => onMonthChange?.(Number(event.target.value))}>
              {MONTHS.map((label, index) => <option key={label} value={index + 1}>{label}</option>)}
            </select>
          </label>
          <label className="ds-field">
            <span>Ano</span>
            <select value={year} onChange={(event) => onYearChange?.(Number(event.target.value))}>
              {years.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
      ) : null}
    </>
  );
}
