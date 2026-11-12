import type { ReactNode } from "react";
import { Lightbulb } from "lucide-react";
import "../../styles/howToRead.css";

export type HowToReadItem = { term: string; text: ReactNode };

/** Explicação para o cliente: título, uma frase de abertura, os termos em grade e uma nota final. */
export default function HowToRead({ title = "Como ler", intro, items, note }: {
  title?: string; intro?: ReactNode; items?: HowToReadItem[]; note?: ReactNode;
}) {
  return <aside className="howToRead" aria-label={title}>
    <p className="howToReadHead"><Lightbulb size={16} aria-hidden="true" /><b>{title}</b>{intro ? <span>{intro}</span> : null}</p>
    {items?.length ? <dl className="howToReadGrid">{items.map((i) => <div key={i.term}><dt>{i.term}</dt><dd>{i.text}</dd></div>)}</dl> : null}
    {note ? <p className="howToReadNote">{note}</p> : null}
  </aside>;
}
