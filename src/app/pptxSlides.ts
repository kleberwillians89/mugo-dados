import { strFromU8, unzipSync } from "fflate";

/** Texto e links de um slide do PowerPoint (o arquivo e as imagens nunca saem do navegador). */
export type SlideText = { index: number; text: string; links: string[] };

const SLIDE = /^ppt\/slides\/slide(\d+)\.xml$/;
const SLIDE_RELS = /^ppt\/slides\/_rels\/slide(\d+)\.xml\.rels$/;
const NOTES = /^ppt\/notesSlides\/notesSlide(\d+)\.xml$/;
const NOTES_RELS = /^ppt\/notesSlides\/_rels\/notesSlide(\d+)\.xml\.rels$/;
const URL_IN_TEXT = /https:\/\/[^\s<>"')\]]+/g;
const MAX_TEXT = 3000;

function parseXml(xml: string): Document {
  return new DOMParser().parseFromString(xml, "application/xml");
}

/** Parágrafos (<a:p>) viram linhas; quebras e tabelas mantêm a leitura de cima para baixo. */
function paragraphs(doc: Document): string {
  const lines: string[] = [];
  for (const p of Array.from(doc.getElementsByTagNameNS("*", "p"))) {
    const text = Array.from(p.getElementsByTagNameNS("*", "t")).map((t) => t.textContent || "").join("");
    if (text.trim()) lines.push(text.trim());
  }
  return lines.join("\n");
}

/** Links clicáveis (<a:hlinkClick r:id>) resolvidos pelo .rels do slide. */
function hyperlinks(doc: Document, rels: Document | null): string[] {
  if (!rels) return [];
  const targets = new Map<string, string>();
  for (const rel of Array.from(rels.getElementsByTagNameNS("*", "Relationship"))) {
    const id = rel.getAttribute("Id"); const target = rel.getAttribute("Target") || "";
    if (id && /^https:\/\//.test(target)) targets.set(id, target);
  }
  const out: string[] = [];
  for (const link of Array.from(doc.getElementsByTagNameNS("*", "hlinkClick"))) {
    const id = link.getAttributeNS("http://schemas.openxmlformats.org/officeDocument/2006/relationships", "id") || link.getAttribute("r:id");
    const url = id ? targets.get(id) : undefined;
    if (url && !out.includes(url)) out.push(url);
  }
  return out;
}

/** Abre o .pptx (zip) e devolve um item por slide, na ordem, com as notas do apresentador junto. */
export function extractSlides(data: Uint8Array): SlideText[] {
  const wanted = (name: string) => SLIDE.test(name) || SLIDE_RELS.test(name) || NOTES.test(name) || NOTES_RELS.test(name);
  let files: Record<string, Uint8Array>;
  try {
    files = unzipSync(data, { filter: (f) => wanted(f.name) });
  } catch {
    throw new Error("Não consegui abrir o arquivo. Envie um .pptx (PowerPoint, Google Slides ou Canva exportado).");
  }
  const xml = (name: string) => (files[name] ? parseXml(strFromU8(files[name])) : null);
  // Nota do apresentador: o slide aponta para ela no próprio .rels.
  const notesOf = (n: number): Document | null => {
    const rels = xml(`ppt/slides/_rels/slide${n}.xml.rels`);
    const target = rels ? Array.from(rels.getElementsByTagNameNS("*", "Relationship"))
      .map((r) => r.getAttribute("Target") || "").find((t) => t.includes("notesSlide")) : undefined;
    const name = target ? `ppt/notesSlides/${target.split("/").pop()}` : "";
    return name ? xml(name) : null;
  };
  const numbers = Object.keys(files).map((f) => SLIDE.exec(f)?.[1]).filter(Boolean).map(Number).sort((a, b) => a - b);
  const slides: SlideText[] = [];
  for (const n of numbers) {
    const doc = xml(`ppt/slides/slide${n}.xml`);
    if (!doc) continue;
    const notesDoc = notesOf(n);
    const notes = notesDoc ? paragraphs(notesDoc).replace(/^\d+$/m, "").trim() : "";
    const body = paragraphs(doc);
    const text = [body, notes ? `Notas: ${notes}` : ""].filter(Boolean).join("\n").slice(0, MAX_TEXT);
    const links = [...hyperlinks(doc, xml(`ppt/slides/_rels/slide${n}.xml.rels`)),
      ...(notesDoc ? hyperlinks(notesDoc, xml(`ppt/notesSlides/_rels/notesSlide${n}.xml.rels`)) : []),
      ...(text.match(URL_IN_TEXT) || [])];
    const unique = [...new Set(links.map((l) => l.replace(/[.,;]+$/, "")))].slice(0, 10);
    if (text.trim() || unique.length) slides.push({ index: n, text, links: unique });
  }
  return slides;
}

/** Texto colado (sem PowerPoint): cada bloco separado por linha em branco vira um "slide". */
export function slidesFromText(text: string): SlideText[] {
  return text.split(/\n\s*\n/).map((block) => block.trim()).filter(Boolean).slice(0, 150)
    .map((block, i) => ({ index: i + 1, text: block.slice(0, MAX_TEXT), links: [...new Set(block.match(URL_IN_TEXT) || [])].slice(0, 10) }));
}
