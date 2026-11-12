import { useEffect, useRef, useState } from "react";
import type { EmailPreviewResult, HtmlReport } from "../../app/emailMarketing";

/** Prévia do e-mail exatamente como o servidor monta. Relê com uma pausa curta depois de cada mudança. */
export default function EmailPreview({ load, deps, onReport }: {
  load: () => Promise<EmailPreviewResult>; deps: unknown[]; onReport?: (report: HtmlReport | null) => void;
}) {
  const [preview, setPreview] = useState<EmailPreviewResult | null>(null);
  const [error, setError] = useState("");
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  const generation = useRef(0);
  const loader = useRef(load);
  const reporter = useRef(onReport);
  useEffect(() => { loader.current = load; reporter.current = onReport; });
  const key = JSON.stringify(deps);

  useEffect(() => {
    const request = ++generation.current;
    const timer = setTimeout(async () => {
      try {
        const next = await loader.current();
        if (request === generation.current) { setPreview(next); setError(""); reporter.current?.(next.report || null); }
      } catch (cause) {
        if (request === generation.current) setError(cause instanceof Error ? cause.message : "Prévia indisponível.");
      }
    }, 450);
    return () => clearTimeout(timer);
  }, [key]);

  return (
    <div className="emPreview">
      <div className="emPreviewHead">
        <div className="emInbox">
          <span className="emInboxLabel">Assunto</span>
          <strong>{preview?.subject || "—"}</strong>
        </div>
        <div className="ds-segmented" role="group" aria-label="Tamanho da prévia">
          <button type="button" aria-pressed={device === "desktop"} onClick={() => setDevice("desktop")}>Computador</button>
          <button type="button" aria-pressed={device === "mobile"} onClick={() => setDevice("mobile")}>Celular</button>
        </div>
      </div>
      {error ? <p className="emError" role="alert">{error}</p> : null}
      <div className={`emFrameWrap is-${device}`}>
        {preview ? <iframe title="Prévia do e-mail" sandbox="" srcDoc={preview.html} /> : <p className="emMuted">Montando prévia…</p>}
      </div>
    </div>
  );
}
