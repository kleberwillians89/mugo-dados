import { useState } from "react";
import { http } from "../../app/api";
import { ArrowDown, ArrowUp, Trash2 } from "lucide-react";
import { getActiveClientId } from "../../app/activeClient";
import { listLibrary, previewKind, type LibraryItem } from "../../app/library";
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
export default function BlockEditor({ design, onChange, allowProducts, disabled: readOnly, allowImageUpload, onUploadPending }: {
  design: EmailDesign; onChange: (design: EmailDesign) => void; allowProducts?: boolean; disabled?: boolean;
  allowImageUpload?: boolean; onUploadPending?: (pending: boolean) => void;
}) {
  const [picker, setPicker] = useState<number | null>(null);
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [pickerTenant, setPickerTenant] = useState<string | null>(null);
  const [pickerBusy, setPickerBusy] = useState(false);
  const [pickerError, setPickerError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const disabled = readOnly || uploading;
  const blocks = design.blocks || [];
  async function openPicker(index: number) {
    if (disabled) return;
    if (picker === index) { setPicker(null); return; }
    const tenant = getActiveClientId();
    setPicker(index); setPickerTenant(tenant); setPickerBusy(true); setPickerError("");
    try {
      const library = await listLibrary();
      if (getActiveClientId() !== tenant) { setPicker(null); return; }
      setItems(library.items.filter((it) => it.kind === "arquivo" && previewKind(it) === "image"
        && /^https:\/\//i.test(it.url) && /^(image\/jpeg|image\/png|image\/webp|image\/gif)$/i.test(it.mime_type || "")));
    } catch (cause) {
      if (getActiveClientId() === tenant) setPickerError(cause instanceof Error ? cause.message : "Biblioteca indisponível.");
    } finally { if (getActiveClientId() === tenant) setPickerBusy(false); }
  }
  function chooseImage(index: number, item: LibraryItem) {
    if (disabled || pickerTenant !== getActiveClientId() || !items.some((it) => it.id === item.id)) {
      setPickerError("A empresa mudou ou a imagem não está mais disponível. Reabra a Biblioteca.");
      return;
    }
    patch(index, { url: item.url, alt: blocks[index]?.alt || item.title.slice(0, 180) });
    setPicker(null);
  }
  const set = (next: EmailBlock[]) => onChange({ blocks: next });
  const patch = (index: number, change: Partial<EmailBlock>) => set(blocks.map((b, i) => (i === index ? { ...b, ...change } : b)));
  async function upload(index: number, file: File) {
    setUploadError("");
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setUploadError("Selecione um JPG, PNG ou WebP.");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setUploadError("A imagem deve ter até 5 MB.");
      return;
    }
    setPicker(null);
    setUploading(true);
    onUploadPending?.(true);
    try {
      const { url } = await http<{ url: string }>("/api/email/images", {
        method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" }, timeoutMs: 60_000,
      });
      patch(index, { url });
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "Falha ao enviar imagem.");
    } finally {
      setUploading(false);
      onUploadPending?.(false);
    }
  }
  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= blocks.length) return;
    setPicker(null);
    const next = [...blocks];
    [next[index], next[target]] = [next[target], next[index]];
    set(next);
  };

  return (
    <div className="emBlocks">
      {uploading ? <p role="status">Enviando imagem…</p> : null}
      {uploadError ? <p className="emError" role="alert">{uploadError}</p> : null}
      <ol className="emBlockList">
        {blocks.map((block, index) => (
          <li key={index} className="emBlock">
            <div className="emBlockHead">
              <strong>{BLOCK_LABEL[block.type]}</strong>
              <div className="emBlockTools">
                <button type="button" aria-label="Subir" onClick={() => move(index, -1)} disabled={disabled || index === 0}><ArrowUp size={14} /></button>
                <button type="button" aria-label="Descer" onClick={() => move(index, 1)} disabled={disabled || index === blocks.length - 1}><ArrowDown size={14} /></button>
                <button type="button" aria-label="Remover bloco" onClick={() => { setPicker(null); set(blocks.filter((_, i) => i !== index)); }} disabled={disabled}><Trash2 size={14} /></button>
              </div>
            </div>
            {block.type === "titulo" ? (
              <input aria-label="Título" value={block.text || ""} disabled={disabled} onChange={(e) => patch(index, { text: e.target.value })} />
            ) : null}
            {block.type === "texto" ? (
              <textarea aria-label="Texto" rows={3} value={block.text || ""} disabled={disabled} onChange={(e) => patch(index, { text: e.target.value })} />
            ) : null}
            {block.type === "imagem" ? (
              <>
                <div className="emBlockRow">
                  {block.url?.startsWith("https://") ? (
                    <img src={block.url} alt={block.alt || ""} className="emImageThumb" referrerPolicy="no-referrer" />
                  ) : null}
                  {allowImageUpload ? <label className="emField">
                    <span>{block.url ? "Substituir imagem" : "Enviar imagem"}</span>
                    <input type="file" accept="image/jpeg,image/png,image/webp" disabled={disabled}
                      onChange={(event) => {
                        const file = event.currentTarget.files?.[0];
                        event.currentTarget.value = "";
                        if (file) void upload(index, file);
                      }} />
                  </label> : null}
                  {block.url ? <button type="button" className="ds-button" disabled={disabled}
                    onClick={() => patch(index, { url: "" })}>Remover imagem</button> : null}
                  <input aria-label="Texto alternativo" placeholder="Texto alternativo" maxLength={200}
                    value={block.alt || ""} disabled={disabled} onChange={(e) => patch(index, { alt: e.target.value })} />
                  <input aria-label="Link da imagem (https)" placeholder="https://… imagem" value={block.url || ""} disabled={disabled} onChange={(e) => patch(index, { url: e.target.value })} />
                  <input aria-label="Link ao clicar" placeholder="Link ao clicar (opcional)" value={block.href || ""} disabled={disabled} onChange={(e) => patch(index, { href: e.target.value })} />
                </div>
                <div className="emLibraryRow">
                  <button type="button" className="ds-button" disabled={disabled || pickerBusy} aria-expanded={picker === index}
                    onClick={() => void openPicker(index)}>
                    {picker === index ? "Fechar Biblioteca" : "Escolher da Biblioteca"}
                  </button>
                </div>
                {picker === index ? <div className="emLibraryPicker" aria-label="Imagens da Biblioteca">
                  {pickerBusy ? <p role="status">Carregando imagens da marca…</p> : null}
                  {pickerError ? <p role="alert">{pickerError}</p> : null}
                  {!pickerBusy && !items.length && !pickerError ? <p>Nenhuma imagem disponível. Envie fotos pela Biblioteca.</p> : null}
                  {!pickerBusy && items.length ? <div className="emLibraryImages">
                    {items.map((it) => <button key={it.id} type="button" onClick={() => chooseImage(index, it)}
                      aria-label={`Selecionar ${it.title}`}><img src={it.url} alt="" loading="lazy" /><span>{it.title}</span></button>)}
                  </div> : null}
                </div> : null}
              </>
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
