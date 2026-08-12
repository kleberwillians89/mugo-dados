import { usePeriod } from "../app/PeriodContext";

function formatDay(value: string) {
  return new Date(`${value}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" });
}

function todayIso() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date());
}

export default function DayPeriodControl() {
  const { period, setDayPeriod, shiftDayPeriod } = usePeriod();
  const isToday = period.start === todayIso();
  return <div className="dayPeriodControl" aria-label="Navegação por dia">
    <button type="button" onClick={() => shiftDayPeriod(-1)} aria-label="Dia anterior">‹ <span>Dia anterior</span></button>
    <label><small>{isToday ? "Hoje" : "Data selecionada"}</small><strong>{formatDay(period.start)}</strong><input type="date" value={period.start} onChange={(event) => setDayPeriod(event.target.value)} /></label>
    <button type="button" onClick={() => shiftDayPeriod(1)} aria-label="Dia seguinte"><span>Dia seguinte</span> ›</button>
    {isToday ? <p>Os dados de hoje ainda podem sofrer alterações.</p> : null}
  </div>;
}
