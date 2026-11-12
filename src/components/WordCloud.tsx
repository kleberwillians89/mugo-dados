import type { TopWord } from "../app/types";
import { TONES, TONE_NAME, wordTitle } from "../app/wordTone";

type Props = {
  words: TopWord[];
};

function fontSize(count: number, max: number) {
  if (max <= 0) return 12;
  const min = 12;
  const top = 34;
  return Math.round(min + ((count / max) * (top - min)));
}

/** Nuvem de palavras: tamanho = quantas vezes aparece; cor = sentimento dominante dos comentários com ela. */
export default function WordCloud({ words }: Props) {
  const list = Array.isArray(words) ? words.slice(0, 40) : [];
  const max = list.reduce((acc, w) => Math.max(acc, Number(w.count || 0)), 0);
  const tonesUsed = TONES.filter((t) => list.some((w) => w.tone === t));
  const hasPending = list.some((w) => !w.tone);

  if (!list.length) {
    return <div className="smallMuted">Sem comentários suficientes para nuvem de palavras.</div>;
  }

  return (
    <>
      <div className="wordCloud" aria-label="Nuvem de palavras dos comentários, coloridas pelo sentimento">
        {list.map((w) => (
          <span
            key={w.word}
            className={`wordTag${w.tone ? ` is-${w.tone}` : " is-sem_analise"}`}
            style={{ fontSize: `${fontSize(Number(w.count || 0), max)}px` }}
            title={wordTitle(w)}
          >
            {w.word}
          </span>
        ))}
      </div>
      {tonesUsed.length ? (
        <div className="wordCloudLegend" aria-label="Legenda das cores">
          {tonesUsed.map((t) => <span key={t}><i className={`wordDot is-${t}`} />{TONE_NAME[t]}</span>)}
          {hasPending ? <span><i className="wordDot is-sem_analise" />Sem análise</span> : null}
        </div>
      ) : null}
    </>
  );
}
