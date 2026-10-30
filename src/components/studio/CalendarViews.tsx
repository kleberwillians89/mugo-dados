import { useState, type DragEvent } from "react";
import { STUDIO_FORMATS, localParts, type CalendarItem, type StudioFormat } from "../../app/studio";
import { addDays, fromKey, mondayOf, todayKey } from "../../app/studioCalendar";

const FORMAT_ICON: Record<StudioFormat, string> = { reels: "▶", carrossel: "▤", imagem: "▢", stories: "◯", video: "▶" };
const WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];

function byDay(items: CalendarItem[]) {
  const map = new Map<string, CalendarItem[]>();
  for (const item of items) {
    const key = localParts(item.scheduled_at).date;
    map.set(key, [...(map.get(key) || []), item]);
  }
  for (const list of map.values()) list.sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at));
  return map;
}

type Common = {
  items: CalendarItem[];
  canManage: boolean;
  onOpen: (item: CalendarItem) => void;
  onMove: (item: CalendarItem, dayKey: string) => void;
  onCreate: (dayKey: string) => void;
};

function useDrop(canManage: boolean, items: CalendarItem[], onMove: Common["onMove"]) {
  const [over, setOver] = useState<string | null>(null);
  const bind = (dayKey: string) => canManage ? {
    onDragOver: (e: DragEvent) => { e.preventDefault(); setOver(dayKey); },
    onDragLeave: () => setOver((o) => (o === dayKey ? null : o)),
    onDrop: (e: DragEvent) => {
      e.preventDefault(); setOver(null);
      const item = items.find((i) => i.id === e.dataTransfer.getData("text/plain"));
      if (item && localParts(item.scheduled_at).date !== dayKey) onMove(item, dayKey);
    },
  } : {};
  return { over, bind };
}

function Chip({ item, canManage, onOpen, compact }: { item: CalendarItem; canManage: boolean; onOpen: Common["onOpen"]; compact?: boolean }) {
  const when = localParts(item.scheduled_at);
  return <button type="button" className={`calChip is-${item.status}`} draggable={canManage}
    onDragStart={(e) => { e.dataTransfer.setData("text/plain", item.id); e.dataTransfer.effectAllowed = "move"; }}
    onClick={() => onOpen(item)} title={`${when.time} · ${STUDIO_FORMATS[item.format]} · ${item.title}`}>
    <span className="calChipMeta">{when.time} <span aria-label={STUDIO_FORMATS[item.format]}>{FORMAT_ICON[item.format]}</span>{item.signals?.seasonal ? " 📅" : ""}{item.boost ? <span className="calChipBoost" aria-label={`Impulsionar a partir de ${item.boost.start.slice(8, 10)}/${item.boost.start.slice(5, 7)}`}> ⚡</span> : null}{item.assets?.length ? <span className="calChipArt" aria-label={`${item.assets.length} mídia(s) anexada(s)`}> 🖼{item.assets.length > 1 ? item.assets.length : ""}</span> : null}</span>
    <span className="calChipTitle">{item.title}</span>
    {!compact && item.pillar ? <span className="calChipPillar">{item.pillar}</span> : null}
  </button>;
}

export function MonthView({ month, ...p }: Common & { month: string; onPickDay: (dayKey: string) => void }) {
  const first = `${month}-01`;
  const start = mondayOf(first);
  const days = Array.from({ length: 42 }, (_, i) => addDays(start, i));
  const weeks = days.slice(35).every((d) => !d.startsWith(month)) ? days.slice(0, 35) : days;
  const map = byDay(p.items);
  const { over, bind } = useDrop(p.canManage, p.items, p.onMove);
  const today = todayKey();
  return <div className="calMonth" role="grid" aria-label="Calendário do mês">
    {WEEKDAYS.map((w) => <div key={w} className="calHead" role="columnheader">{w}</div>)}
    {weeks.map((day) => {
      const list = map.get(day) || [];
      const outside = !day.startsWith(month);
      return <div key={day} role="gridcell" className={`calCell ${outside ? "is-outside" : ""} ${day === today ? "is-today" : ""} ${over === day ? "is-over" : ""}`} {...bind(day)}>
        <div className="calCellHead">
          <button type="button" className="calDayNum" onClick={() => p.onPickDay(day)} aria-label={`Abrir dia ${day}`}>{Number(day.slice(8))}</button>
          {p.canManage && !outside ? <button type="button" className="calAdd" aria-label="Nova pauta neste dia" onClick={() => p.onCreate(day)}>+</button> : null}
        </div>
        <div className="calChips">
          {list.slice(0, 3).map((item) => <Chip key={item.id} item={item} canManage={p.canManage} onOpen={p.onOpen} compact />)}
          {list.length > 3 ? <button type="button" className="calMore" onClick={() => p.onPickDay(day)}>+{list.length - 3} mais</button> : null}
        </div>
        <div className="calDots" aria-hidden="true">{list.map((i) => <i key={i.id} className={`is-${i.status}`} />)}</div>
      </div>;
    })}
  </div>;
}

export function WeekView({ weekStart, ...p }: Common & { weekStart: string; onPickDay: (dayKey: string) => void }) {
  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));
  const map = byDay(p.items);
  const { over, bind } = useDrop(p.canManage, p.items, p.onMove);
  const today = todayKey();
  return <div className="calWeek">
    {days.map((day, idx) => {
      const list = map.get(day) || [];
      return <section key={day} className={`calWeekCol ${day === today ? "is-today" : ""} ${over === day ? "is-over" : ""}`} {...bind(day)}>
        <header><button type="button" className="calWeekDay" onClick={() => p.onPickDay(day)}><span>{WEEKDAYS[idx]}</span><b>{fromKey(day).getDate()}</b></button>
          {p.canManage ? <button type="button" className="calAdd" aria-label="Nova pauta neste dia" onClick={() => p.onCreate(day)}>+</button> : null}</header>
        <div className="calChips">{list.length ? list.map((item) => <Chip key={item.id} item={item} canManage={p.canManage} onOpen={p.onOpen} />) : <p className="calEmpty">—</p>}</div>
      </section>;
    })}
  </div>;
}

export function DayView({ day, ...p }: Common & { day: string }) {
  const list = byDay(p.items).get(day) || [];
  const hours = Array.from({ length: 18 }, (_, i) => i + 6); // 06h–23h
  const byHour = new Map<number, CalendarItem[]>();
  for (const item of list) {
    const h = Number(localParts(item.scheduled_at).time.slice(0, 2));
    byHour.set(h, [...(byHour.get(h) || []), item]);
  }
  const early = list.filter((i) => Number(localParts(i.scheduled_at).time.slice(0, 2)) < 6);
  return <div className="calDay">
    {early.length ? <div className="calHour"><span>madrugada</span><div className="calChips">{early.map((item) => <Chip key={item.id} item={item} canManage={false} onOpen={p.onOpen} />)}</div></div> : null}
    {hours.map((h) => <div key={h} className="calHour">
      <span>{String(h).padStart(2, "0")}:00</span>
      <div className="calChips">{(byHour.get(h) || []).map((item) => <article key={item.id} className={`calDayCard is-${item.status}`} onClick={() => p.onOpen(item)}>
        <header><b>{localParts(item.scheduled_at).time}</b><span className="studioChip">{STUDIO_FORMATS[item.format]}</span>{item.pillar ? <span className="studioChip is-pillar">{item.pillar}</span> : null}</header>
        <h3>{item.title}</h3>
        {item.hook ? <p className="studioHook">“{item.hook}”</p> : null}
      </article>)}
      {p.canManage && !(byHour.get(h) || []).length ? <button type="button" className="calHourAdd" onClick={() => p.onCreate(`${day}T${String(h).padStart(2, "0")}:00`)} aria-label={`Nova pauta às ${h}h`}>+</button> : null}
      </div>
    </div>)}
  </div>;
}
