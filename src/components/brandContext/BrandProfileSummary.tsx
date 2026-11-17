import { useEffect, useState, type ReactNode } from "react";
import { pillarWeightTotal } from "./brandContext.helpers";
import { BRAND_PROFILE_SAVED, STUDIO_CHANNELS, STUDIO_FORMATS, getBrandProfile, type BrandProfile, type StudioChannel } from "../../app/studio";

type Loaded = { profile: BrandProfile; saved: boolean; updated_at?: string | null };

const channelLabel = (c: string) => STUDIO_CHANNELS[c as StudioChannel] || c;
const formatLabel = (f: string) => STUDIO_FORMATS[f as keyof typeof STUDIO_FORMATS] || f;

function Row({ label, children }: { label: string; children: ReactNode }) {
  return <div className="bcRow"><dt>{label}</dt><dd>{children}</dd></div>;
}

const empty = <span className="bcEmpty">Não configurado</span>;
const text = (value?: string | null) => (value && value.trim() ? value : empty);
const list = (values?: string[] | null) => (values && values.length ? values.join(", ") : empty);

/**
 * Perfil da marca (o mesmo usado pelo Calendário, pela Matriz e pelos agentes), só para consulta.
 * A edição continua no lugar de sempre: Social Media → Calendário → Perfil da marca. Nada é duplicado aqui.
 */
export default function BrandProfileSummary({ onEdit, editHint }: { onEdit?: () => void; editHint?: string }) {
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () => getBrandProfile().then((d) => { if (alive) { setData(d); setError(false); } }).catch(() => { if (alive) setError(true); });
    load();
    // Salvou o perfil em outra tela (ou na importação): recarrega.
    window.addEventListener(BRAND_PROFILE_SAVED, load);
    return () => { alive = false; window.removeEventListener(BRAND_PROFILE_SAVED, load); };
  }, []);

  if (error) return <p className="studioError" role="alert">Não foi possível carregar o perfil da marca agora.</p>;
  if (!data) return <p className="libHint" role="status">Carregando perfil da marca…</p>;

  const p = data.profile;
  const total = pillarWeightTotal(p);
  const byPlatform = Object.entries(p.posts_per_week_by_platform || {}).filter(([, n]) => Number(n) > 0);

  return <section className="bcCard" aria-labelledby="bc-profile-title" data-testid="brand-profile-summary">
    <header className="bcCardHead">
      <div>
        <h2 id="bc-profile-title">Perfil da marca</h2>
        <p className="libHint">Tom de voz, pilares e frequência que a IA usa para criar pautas e legendas.
          {data.saved ? "" : " Ainda não foi salvo: a IA usa os valores padrão."}</p>
      </div>
      {onEdit ? <button type="button" className="ds-button" onClick={onEdit}>Editar perfil</button> : null}
    </header>
    {editHint ? <p className="libHint">{editHint}</p> : null}
    <dl className="bcList">
      <Row label="Personalidade">{text(p.personality)}</Row>
      <Row label="Tom de voz">{text(p.tone_of_voice)}</Row>
      <Row label="Público">{text(p.audience)}</Row>
      <Row label="Pilares editoriais">
        {p.pillars.length ? <>
          <ul className="bcPillars">{p.pillars.map((pillar) => <li key={pillar.name}><b>{pillar.name}</b> · {pillar.weight}%
            {pillar.description ? <small> — {pillar.description}</small> : null}</li>)}</ul>
          {total !== 100 ? <p className="studioWarn" role="status">Os pesos somam {total}%. Revise para fechar 100%.</p> : null}
        </> : empty}
      </Row>
      <Row label="Frequência">
        {p.posts_per_week} post{p.posts_per_week === 1 ? "" : "s"} por semana
        {byPlatform.length ? <small className="bcSub"> ({byPlatform.map(([c, n]) => `${channelLabel(c)}: ${n}`).join(" · ")})</small> : null}
      </Row>
      <Row label="Plataformas">{list((p.editorial_platforms || []).map(channelLabel))}</Row>
      <Row label="Formatos">{list(p.formats_enabled.map(formatLabel))}</Row>
      <Row label="Palavras a usar">{list(p.keywords_use)}</Row>
      <Row label="Palavras a evitar">{list(p.keywords_avoid)}</Row>
      <Row label="Restrições">{text(p.restrictions)}</Row>
    </dl>
  </section>;
}
