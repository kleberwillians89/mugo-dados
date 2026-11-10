export type KnowledgeSection = { title: string; items: string[] };
/** Quebra o texto da IA em blocos: linha de título ("Produtos:", "# Produtos", "**Produtos**") + marcadores. */
export function parseKnowledge(text: string): KnowledgeSection[] {
  const out: KnowledgeSection[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const bullet = /^([-•*·]|\d+[.)])\s+/.test(line);
    const heading = !bullet && (/^#{1,4}\s/.test(line) || /^\*\*[^*]+\*\*:?$/.test(line) || (/:$/.test(line) && line.length <= 60));
    if (heading) { out.push({ title: line.replace(/^#+\s*|\*\*|:$/g, "").replace(/:$/, "").trim(), items: [] }); continue; }
    if (!out.length) out.push({ title: "Sobre a marca", items: [] });
    out[out.length - 1].items.push(line.replace(/^([-•*·]|\d+[.)])\s+/, "").replace(/\*\*/g, ""));
  }
  return out.filter((s) => s.items.length);
}
