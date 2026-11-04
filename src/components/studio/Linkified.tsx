/** Texto com links https clicáveis (abrem em nova aba). Nada de HTML do usuário é interpretado. */
const URL_RE = /(https:\/\/[^\s<>"']+)/g;

export default function Linkified({ text }: { text: string }) {
  const parts = text.split(URL_RE);
  return <>{parts.map((part, i) => (i % 2 === 1
    ? <a key={i} href={part} target="_blank" rel="noopener noreferrer nofollow">{part.length > 60 ? `${part.slice(0, 57)}…` : part}</a>
    : <span key={i}>{part}</span>))}</>;
}
