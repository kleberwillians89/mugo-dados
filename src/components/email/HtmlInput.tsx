import { useRef, useState, type DragEvent } from "react";
import { FileUp } from "lucide-react";
import type { HtmlReport } from "../../app/emailMarketing";

const MAX_BYTES = 300_000;

/** HTML próprio: colar, importar arquivo .html (botão ou arrastar) e ver na hora o que o e-mail vai levar. */
export default function HtmlInput({ value, onChange, disabled, report, hint }: {
  value: string; onChange: (html: string) => void; disabled?: boolean; report?: HtmlReport | null; hint: string;
}) {
  const file = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);

  async function load(picked: File | undefined) {
    setError("");
    if (!picked) return;
    if (!/\.(html?|txt)$/i.test(picked.name) && !picked.type.includes("html")) { setError("Escolha um arquivo .html."); return; }
    if (picked.size > MAX_BYTES) { setError("Arquivo acima de 300 KB. Comprima as imagens ou hospede-as fora do HTML."); return; }
    onChange(await picked.text());
  }

  function onDrop(event: DragEvent<HTMLTextAreaElement>) {
    event.preventDefault();
    setDragging(false);
    if (!disabled) void load(event.dataTransfer.files?.[0]);
  }

  const kb = report ? Math.max(1, Math.round(report.bytes / 1024)) : null;
  return (
    <div className="emHtml">
      <div className="emHtmlTools">
        <button type="button" className="ds-button" disabled={disabled} onClick={() => file.current?.click()}>
          <FileUp size={15} aria-hidden="true" /> Importar arquivo .html
        </button>
        {value && !disabled ? <button type="button" className="emLink is-danger" onClick={() => onChange("")}>Limpar</button> : null}
        <input ref={file} type="file" accept=".html,.htm,text/html" hidden aria-label="Arquivo HTML"
          onChange={(e) => { void load(e.target.files?.[0]); e.target.value = ""; }} />
      </div>
      <textarea className={`emCode${dragging ? " is-dragging" : ""}`} rows={16} value={value} disabled={disabled} aria-label="HTML do e-mail"
        placeholder="Cole aqui o HTML (do Canva, Mailchimp, Stripo, Figma…) ou arraste o arquivo .html para cá."
        onChange={(e) => onChange(e.target.value)}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop} />
      <p className="emHint">{hint} · {"{{descadastro}}"} para usar seu próprio link de saída. Também aceitamos *|FNAME|* e *|UNSUB|* do Mailchimp.</p>
      {error ? <p className="emError" role="alert">{error}</p> : null}
      {report && value ? (
        <ul className="emHtmlReport" aria-label="Sobre este HTML">
          <li>{kb} KB · {report.full_document ? "documento completo (mantemos seu <head> e estilos)" : "trecho (entra na moldura padrão de 600 px)"}</li>
          <li>{report.has_unsubscribe ? "Descadastro: o seu link" : "Descadastro: adicionado automaticamente no rodapé"}</li>
          {report.variables.length ? <li>Variáveis: {report.variables.map((v) => `{{${v}}}`).join(" · ")}</li> : null}
          {report.gmail_clip ? <li className="is-warn">Acima de 102 KB: o Gmail corta o e-mail e esconde o rodapé. Enxugue o HTML.</li> : null}
          {report.removed_unsafe ? <li className="is-warn">Removemos partes que e-mail não aceita (scripts, eventos, formulários ou links javascript:).</li> : null}
        </ul>
      ) : null}
    </div>
  );
}
