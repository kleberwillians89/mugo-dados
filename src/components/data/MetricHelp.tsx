import {useId, useLayoutEffect, useRef, useState} from "react";
import {createPortal} from "react-dom";
import {Info} from "lucide-react";
import {METRIC_GLOSSARY, metricIdForLabel, type MetricId} from "../../app/metricGlossary";
import "../../styles/metric-help.css";

export default function MetricHelp({label, metricId}: {label: string; metricId?: MetricId}) {
  const id = useId();
  const metric = metricId || metricIdForLabel(label);
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const beforePointer = useRef(false);
  const closing = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const keepOpen = () => clearTimeout(closing.current);
  const closeSoon = () => {if (document.activeElement !== trigger.current) closing.current = setTimeout(() => setOpen(false), 150);};
  useLayoutEffect(() => {
    if (!open || !metric) return;
    const place = () => {
      if (!trigger.current || !panel.current) return;
      const anchor = trigger.current.getBoundingClientRect();
      const box = panel.current.getBoundingClientRect();
      panel.current.style.left = `${Math.max(8, Math.min(anchor.left, window.innerWidth - box.width - 8))}px`;
      panel.current.style.top = `${Math.max(8, Math.min(anchor.bottom + 8, window.innerHeight - box.height - 8))}px`;
    };
    const outside = (event: PointerEvent) => {
      if (!trigger.current?.contains(event.target as Node) && !panel.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); setOpen(false); }
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape, true);
    return () => {clearTimeout(closing.current); window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape, true);};
  }, [open, metric]);
  if (!metric) return null;
  const entry = METRIC_GLOSSARY[metric];
  return <span className="metricHelp" onClick={event => event.stopPropagation()} onKeyDown={event => event.stopPropagation()}>
    <button type="button" ref={trigger} className="metricHelpTrigger" aria-label={`Entender ${label}`} aria-describedby={open ? id : undefined}
      onPointerDown={() => { beforePointer.current = open; }}
      onClick={event => setOpen(event.detail === 0 || !beforePointer.current)}
      onFocus={() => setOpen(true)} onBlur={event => {if (!panel.current?.contains(event.relatedTarget)) setOpen(false);}}
      onPointerEnter={event => {keepOpen(); if (event.pointerType === "mouse") setOpen(true);}}
      onPointerLeave={closeSoon}>
      <Info size={15} aria-hidden="true" />
    </button>
    {open ? createPortal(<div ref={panel} id={id} role="tooltip" className="metricHelpPanel" onPointerEnter={keepOpen} onPointerLeave={closeSoon}>
      <strong>{entry.acronym ? `${entry.acronym} — ` : ""}{entry.name}</strong>
      <p>{entry.explanation}</p>
      {entry.formula ? <p><b>Fórmula:</b> {entry.formula}</p> : null}
      <p><b>Unidade:</b> {entry.unit} · <b>Fonte:</b> {entry.platforms}</p>
      <p className="metricHelpCaveat">{entry.caveat}</p>
    </div>, document.body) : null}
  </span>;
}
