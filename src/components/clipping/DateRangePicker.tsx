import { useEffect, useRef, useState } from "react";
import { PRESETS, PRESET_NAME, iso, parseIso, presetRange, type Preset } from "../../app/brandHealth";

const WEEKDAYS = ["D", "S", "T", "Q", "Q", "S", "S"];
const fmt = (value: string) => parseIso(value).toLocaleDateString("pt-BR");

type Range = { start: string; end: string; preset: Preset };

/** Intervalo de datas: atalhos (hoje, 7/30 dias, mês, 3 meses, trimestre, ano) ou dois cliques no calendário. */
export default function DateRangePicker({ value, onChange }: { value: Range; onChange: (next: Range) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Range>(value);
  const [picking, setPicking] = useState<string | null>(null);
  const [month, setMonth] = useState(() => { const d = parseIso(value.end); return new Date(d.getFullYear(), d.getMonth(), 1); });
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !box.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);

  function toggle() {
    if (!open) {
      setDraft(value); setPicking(null);
      const d = parseIso(value.end); setMonth(new Date(d.getFullYear(), d.getMonth(), 1));
    }
    setOpen(!open);
  }
  function pickDay(day: string) {
    if (!picking) { setPicking(day); setDraft({ start: day, end: day, preset: "custom" }); return; }
    const [a, b] = picking <= day ? [picking, day] : [day, picking];
    setPicking(null); setDraft({ start: a, end: b, preset: "custom" });
  }

  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const today = iso(new Date());
  const cells: (string | null)[] = [...Array(first.getDay()).fill(null),
    ...Array.from({ length: days }, (_, i) => iso(new Date(month.getFullYear(), month.getMonth(), i + 1)))];

  return <div className="bhDate" ref={box}>
    <button type="button" className="bhDateBtn" aria-expanded={open} aria-haspopup="dialog" onClick={toggle}>
      <span aria-hidden="true">📅</span> {fmt(value.start)} – {fmt(value.end)} <span aria-hidden="true">▾</span>
    </button>
    {open ? <div className="bhCal" role="dialog" aria-label="Escolher período">
      <div className="bhPresets">
        {[...PRESETS, "custom" as const].map((p) => <button key={p} type="button" className={draft.preset === p ? "is-on" : ""}
          onClick={() => { if (p === "custom") { setDraft({ ...draft, preset: "custom" }); return; } setDraft({ ...presetRange(p), preset: p }); }}>{PRESET_NAME[p]}</button>)}
      </div>
      <div className="bhMonth">
        <div className="bhMonthHead">
          <button type="button" aria-label="Mês anterior" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}>‹</button>
          <b>{month.toLocaleDateString("pt-BR", { month: "long", year: "numeric" })}</b>
          <button type="button" aria-label="Próximo mês" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}>›</button>
        </div>
        <div className="bhGrid">
          {WEEKDAYS.map((d, i) => <span key={i} className="bhWd">{d}</span>)}
          {cells.map((day, i) => day ? <button key={day} type="button" disabled={day > today}
            className={`${day === draft.start || day === draft.end ? "is-edge" : day > draft.start && day < draft.end ? "is-in" : ""}`}
            aria-pressed={day >= draft.start && day <= draft.end} onClick={() => pickDay(day)}>{parseIso(day).getDate()}</button>
            : <span key={`e${i}`} />)}
        </div>
        <p className="bhCalHint">{picking ? "Agora clique no último dia." : `${fmt(draft.start)} – ${fmt(draft.end)}`}</p>
        <div className="bhCalFoot">
          <button type="button" className="ds-button" onClick={() => setOpen(false)}>Cancelar</button>
          <button type="button" className="ds-button is-primary" disabled={Boolean(picking)} onClick={() => { onChange(draft); setOpen(false); }}>Aplicar</button>
        </div>
      </div>
    </div> : null}
  </div>;
}
