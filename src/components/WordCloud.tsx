import type { TopWord } from "../app/types";

type Props = {
  words: TopWord[];
};

function fontSize(count: number, max: number) {
  if (max <= 0) return 12;
  const min = 12;
  const top = 34;
  return Math.round(min + ((count / max) * (top - min)));
}

export default function WordCloud({ words }: Props) {
  const list = Array.isArray(words) ? words.slice(0, 40) : [];
  const max = list.reduce((acc, w) => Math.max(acc, Number(w.count || 0)), 0);

  if (!list.length) {
    return <div className="smallMuted">Sem comentários suficientes para nuvem de palavras.</div>;
  }

  return (
    <div className="wordCloud" aria-label="Nuvem de palavras dos comentários">
      {list.map((w) => (
        <span
          key={w.word}
          className="wordTag"
          style={{ fontSize: `${fontSize(Number(w.count || 0), max)}px` }}
          title={`${w.word}: ${w.count}`}
        >
          {w.word}
        </span>
      ))}
    </div>
  );
}
