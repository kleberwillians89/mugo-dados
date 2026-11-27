import type { ReactNode } from "react";

const ACTION_RE = /^(o que eu faria agora|próximo passo|recomendação)\s*:?/i;

/** Texto da IA → parágrafos, listas e o bloco "O que eu faria agora" em destaque. Sem HTML vindo da IA. */
export function AnswerBody({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  let action: string[] | null = null;
  const flushList = () => {
    if (list.length) blocks.push(<ul key={`l${blocks.length}`}>{list.map((item, i) => <li key={i}>{item}</li>)}</ul>);
    list = [];
  };
  // "… O que eu faria agora: …" no meio do parágrafo também vira o bloco em destaque.
  const normalized = text.replace(/\s+(o que eu faria agora\s*:)/i, "\n$1");
  for (const raw of normalized.split("\n")) {
    const line = raw.trim();
    if (!line) { flushList(); continue; }
    if (ACTION_RE.test(line)) {
      flushList();
      action = [];
      const rest = line.replace(ACTION_RE, "").trim();
      if (rest) action.push(rest.replace(/^[-•]\s*/, ""));
      continue;
    }
    if (action) { action.push(line.replace(/^[-•]\s*/, "")); continue; }
    if (/^[-•]\s+/.test(line)) { list.push(line.replace(/^[-•]\s+/, "")); continue; }
    flushList();
    blocks.push(<p key={`p${blocks.length}`}>{line}</p>);
  }
  flushList();
  return <div className="miaAnswer">
    {blocks}
    {action && (action as string[]).length ? <div className="miaAction"><b>O que eu faria agora</b>
      {(action as string[]).length > 1 ? <ul>{(action as string[]).map((a, i) => <li key={i}>{a}</li>)}</ul> : <p>{(action as string[])[0]}</p>}</div> : null}
  </div>;
}
