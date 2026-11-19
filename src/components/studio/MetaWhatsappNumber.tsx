import { useEffect, useState } from "react";
import { readAdWhatsappNumbers } from "../../app/metaAds";

/** Anúncio que abre conversa: escolhe o número do WhatsApp da marca (o mesmo que a IA atende). */
export default function MetaWhatsappNumber({ value, disabled, onChange }: { value: string | null | undefined; disabled?: boolean; onChange: (n: string | null) => void }) {
  const [numbers, setNumbers] = useState<{ number: string; label: string; name: string }[] | null>(null);
  useEffect(() => {
    let alive = true;
    readAdWhatsappNumbers().then((r) => { if (alive) setNumbers(r.numbers); }).catch(() => { if (alive) setNumbers([]); });
    return () => { alive = false; };
  }, []);
  useEffect(() => { if (numbers?.length === 1 && !value) onChange(numbers[0].number); }, [numbers, value, onChange]);
  return <div className="metaPixel">
    <div className="metaPixelHead"><b>Número do WhatsApp</b><span>Quem clicar no anúncio abre a conversa neste número. A IA da marca responde e, se configurado, manda o convite do grupo.</span></div>
    <label className="metaPixelRow"><span className="ds-srOnly">Número do WhatsApp</span>
      <select value={value || ""} disabled={disabled || numbers === null} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">{numbers === null ? "Carregando…" : "O número ligado à Página do Facebook"}</option>
        {(numbers || []).map((n) => <option key={n.number} value={n.number}>{n.label}{n.name ? ` · ${n.name}` : ""}</option>)}
      </select></label>
    {numbers && !numbers.length ? <p className="metaPixelWarn">Nenhum número de WhatsApp desta marca ligado ao MUGOVERSO: a Meta usa o número ligado à Página.</p> : null}
  </div>;
}
