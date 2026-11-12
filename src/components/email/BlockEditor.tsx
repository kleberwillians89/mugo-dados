import { ArrowDown, ArrowUp, Trash2 } from "lucide-react";
import { BLOCK_LABEL, type BlockType, type EmailBlock, type EmailDesign } from "../../app/emailMarketing";

const ADDABLE: BlockType[] = ["logo", "titulo", "texto", "imagem", "botao", "produtos", "divisor", "espaco"];

function emptyBlock(type: BlockType): EmailBlock {
  if (type === "titulo") return { type, text: "Novo título" };
  if (type === "texto") return { type, text: "" };
  if (type === "botao") return { type, label: "Ver agora", href: "{{link_loja}}", align: "center" };
  if (type === "imagem") return { type, url: "", alt: "" };
  if (type === "logo") return { type, align: "center" };
  return { type };
}

/** Editor por blocos: cada bloco vira uma linha com os campos que ele usa. O HTML final é montado no servidor. */
export default function BlockEditor({ design, onChange, allowProducts, disabled }: {
  design: EmailDesign; onChange: (design: EmailDesign) => void; allowProducts?: boolean; disabled?: boolean;
}) {
  const blocks = design.blocks || [];
  const set = (next: EmailBlock[]) => onChange({ blocks: next });
  const patch = (index: number, change: Partial<EmailBlock>) => set(blocks.map((b, i) => (i === index ? { ...b, ...change } : b)));
  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= blocks.length) return;
    const next = [...blocks];
    [next[index], next[target]] = [next[target], next[index]];
    set(next);
  };

  return (
    <div className="emBlocks">
      <ol className="emBlockList">
        {blocks.map((block, index) => (
          <li key={index} className="emBlock">
            <div className="emBlockHead">
              <strong>{BLOCK_LABEL[block.type]}</strong>
              <div className="emBlockTools">
                <button type="button" aria-label="Subir" onClick={() => move(index, -1)} disabled={disabled || index === 0}><ArrowUp size={14} /></button>
                <button type="button" aria-label="Descer" onClick={() => move(index, 1)} disabled={disabled || index === blocks.length - 1}><ArrowDown size={14} /></button>
                <button type="button" aria-label="Remover bloco" onClick={() => set(blocks.filter((_, i) => i !== index))} disabled={disabled}><Trash2 size={14} /></button>
              </div>
            </div>
            {block.type === "titulo" ? (
              <input aria-label="Título" value={block.text || ""} disabled={disabled} onChange={(e) => patch(index, { text: e.target.value })} />
            ) : null}
            {block.type === "texto" ? (
              <textarea aria-label="Texto" rows={3} value={block.text || ""} disabled={disabled} onChange={(e) => patch(index, { text: e.target.value })} />
            ) : null}
            {block.type === "imagem" ? (
              <div className="emBlockRow">
                <input aria-label="Link da imagem (https)" placeholder="https://… imagem" value={block.url || ""} disabled={disabled} onChange={(e) => patch(index, { url: e.target.value })} />
                <input aria-label="Link ao clicar" placeholder="Link ao clicar (opcional)" value={block.href || ""} disabled={disabled} onChange={(e) => patch(index, { href: e.target.value })} />
              </div>
            ) : null}
            {block.type === "botao" ? (
              <div className="emBlockRow">
                <input aria-label="Texto do botão" value={block.label || ""} disabled={disabled} onChange={(e) => patch(index, { label: e.target.value })} />
                <input aria-label="Link do botão" placeholder="https://… ou {{link_loja}}" value={block.href || ""} disabled={disabled} onChange={(e) => patch(index, { href: e.target.value })} />
              </div>
            ) : null}
            {block.type === "logo" ? <p className="emBlockNote">Usa o logo do remetente (aba Remetente).</p> : null}
            {block.type === "produtos" ? <p className="emBlockNote">Mostra os itens que ficaram no carrinho.</p> : null}
            {["titulo", "texto", "botao", "logo"].includes(block.type) ? (
              <label className="emAlign">
                <input type="checkbox" checked={block.align === "center"} disabled={disabled}
                  onChange={(e) => patch(index, { align: e.target.checked ? "center" : "left" })} /> Centralizar
              </label>
            ) : null}
          </li>
        ))}
      </ol>
      <div className="emAddRow" role="group" aria-label="Adicionar bloco">
        {ADDABLE.filter((t) => allowProducts || t !== "produtos").map((type) => (
          <button key={type} type="button" className="emChip" disabled={disabled || blocks.length >= 40} onClick={() => set([...blocks, emptyBlock(type)])}>
            + {BLOCK_LABEL[type]}
          </button>
        ))}
      </div>
    </div>
  );
}
