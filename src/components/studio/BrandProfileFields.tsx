import { CONTENT_LANGUAGES, STUDIO_CHANNELS, STUDIO_FORMATS, listToText, textToList, type BrandProfile, type ContentLanguage, type StudioFormat } from "../../app/studio";

/**
 * Campos do Perfil da marca (idioma, tom, pilares, palavras, restrições, frequência, plataformas e datas).
 * Um só formulário para o Calendário (equipe, com a sugestão da IA) e para o Contexto da Marca (admin da empresa).
 */
export default function BrandProfileFields({ profile, onChange }: { profile: BrandProfile; onChange: (profile: BrandProfile) => void }) {
  const setProfile = onChange;
  return <>
    <label>Idioma das publicações e das respostas de comentário
      <select value={profile.content_language || "pt-BR"} onChange={(e) => setProfile({ ...profile, content_language: e.target.value as ContentLanguage })}>
        {Object.entries(CONTENT_LANGUAGES).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
      </select>
      {profile.content_language && profile.content_language !== "pt-BR"
        ? <small className="libHint">Legendas, roteiros, hashtags e respostas saem em {CONTENT_LANGUAGES[profile.content_language].toLowerCase()}. Pautas e justificativas continuam em português para a equipe.</small> : null}
    </label>
    <label>Tom de voz<textarea rows={3} maxLength={1000} value={profile.tone_of_voice} onChange={(e) => setProfile({ ...profile, tone_of_voice: e.target.value })} /></label>
    <label>Personalidade<input maxLength={500} value={profile.personality} onChange={(e) => setProfile({ ...profile, personality: e.target.value })} /></label>
    <label>Público<textarea rows={2} maxLength={1000} value={profile.audience} onChange={(e) => setProfile({ ...profile, audience: e.target.value })} /></label>
    <fieldset className="studioPillars"><legend>Pilares de conteúdo (peso em %)</legend>
      {profile.pillars.map((p, idx) => <div key={idx} className="studioPillarRow">
        <input aria-label="Nome do pilar" required maxLength={80} value={p.name} onChange={(e) => setProfile({ ...profile, pillars: profile.pillars.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)) })} />
        <input aria-label="Peso" type="number" min={0} max={100} value={p.weight} onChange={(e) => setProfile({ ...profile, pillars: profile.pillars.map((x, i) => (i === idx ? { ...x, weight: Number(e.target.value) } : x)) })} />
        <input aria-label="Descrição" maxLength={400} placeholder="O que entra neste pilar" value={p.description} onChange={(e) => setProfile({ ...profile, pillars: profile.pillars.map((x, i) => (i === idx ? { ...x, description: e.target.value } : x)) })} />
        <button type="button" className="studioLink" aria-label="Remover pilar" onClick={() => setProfile({ ...profile, pillars: profile.pillars.filter((_, i) => i !== idx) })}>Remover</button>
      </div>)}
      {profile.pillars.length < 8 ? <button type="button" className="ds-button" onClick={() => setProfile({ ...profile, pillars: [...profile.pillars, { name: "", weight: 0, description: "" }] })}>+ Pilar</button> : null}
    </fieldset>
    <label>Palavras para usar (separe por vírgula)<input value={listToText(profile.keywords_use)} onChange={(e) => setProfile({ ...profile, keywords_use: textToList(e.target.value) })} /></label>
    <label>Palavras proibidas<input value={listToText(profile.keywords_avoid)} onChange={(e) => setProfile({ ...profile, keywords_avoid: textToList(e.target.value) })} /></label>
    <label>Hashtags<input value={listToText(profile.hashtags)} onChange={(e) => setProfile({ ...profile, hashtags: textToList(e.target.value) })} /></label>
    <label>Restrições (o que nunca pode ser dito ou prometido)<textarea rows={3} maxLength={1500} value={profile.restrictions} onChange={(e) => setProfile({ ...profile, restrictions: e.target.value })} /></label>
    <label>Identidade visual (cores, composição, estilo de foto e de arte)<textarea rows={3} maxLength={1500} value={profile.visual_identity || ""} placeholder="A IA preenche olhando as imagens dos posts mais curtidos." onChange={(e) => setProfile({ ...profile, visual_identity: e.target.value })} /></label>
    <div className="studioRow is-top">
      <label>Posts por semana<input type="number" min={1} max={14} value={profile.posts_per_week} onChange={(e) => setProfile({ ...profile, posts_per_week: Number(e.target.value) })} /></label>
      <fieldset><legend>Formatos</legend>{Object.entries(STUDIO_FORMATS).map(([k, v]) => <label key={k} className="studioCheck">
        <input type="checkbox" checked={profile.formats_enabled.includes(k as StudioFormat)} onChange={(e) => setProfile({ ...profile, formats_enabled: e.target.checked ? [...profile.formats_enabled, k as StudioFormat] : profile.formats_enabled.filter((f) => f !== k) })} />{v}</label>)}</fieldset>
    </div>
    <fieldset><legend>Plataformas do planejamento editorial</legend>
      <p className="libHint">Independem das contas conectadas. Sem frequência específica, o total semanal é distribuído entre as redes conforme a estratégia.</p>
      {Object.entries(STUDIO_CHANNELS).map(([key, label]) => {
        const channel = key as keyof typeof STUDIO_CHANNELS;
        const selected = (profile.editorial_platforms || []).includes(channel);
        const frequencies = profile.posts_per_week_by_platform || {};
        return <div key={channel} className="studioRow">
          <label className="studioCheck"><input type="checkbox" checked={selected} onChange={(e) => {
            const editorial_platforms = e.target.checked
              ? [...(profile.editorial_platforms || []), channel]
              : (profile.editorial_platforms || []).filter((item) => item !== channel);
            const posts_per_week_by_platform = { ...frequencies };
            if (!e.target.checked) delete posts_per_week_by_platform[channel];
            setProfile({ ...profile, editorial_platforms, posts_per_week_by_platform });
          }} />{label}</label>
          {selected ? <label>Posts/semana nesta rede (opcional)<input type="number" min={1} max={14}
            value={frequencies[channel] ?? ""} placeholder="Distribuição automática" onChange={(e) => {
              const posts_per_week_by_platform = { ...frequencies };
              if (e.target.value) posts_per_week_by_platform[channel] = Number(e.target.value); else delete posts_per_week_by_platform[channel];
              setProfile({ ...profile, posts_per_week_by_platform });
            }} /></label> : null}
        </div>;
      })}
    </fieldset>
    <fieldset><legend>Datas da marca (MM-DD todo ano, ou AAAA-MM-DD)</legend>
      {profile.custom_dates.map((d, idx) => <div key={idx} className="studioDateRow">
        <input aria-label="Data" required pattern="(\d{4}-)?\d{2}-\d{2}" placeholder="11-03" value={d.date} onChange={(e) => setProfile({ ...profile, custom_dates: profile.custom_dates.map((x, i) => (i === idx ? { ...x, date: e.target.value } : x)) })} />
        <input aria-label="Nome da data" required maxLength={80} placeholder="Aniversário da marca" value={d.label} onChange={(e) => setProfile({ ...profile, custom_dates: profile.custom_dates.map((x, i) => (i === idx ? { ...x, label: e.target.value } : x)) })} />
        <button type="button" className="studioLink" aria-label="Remover data" onClick={() => setProfile({ ...profile, custom_dates: profile.custom_dates.filter((_, i) => i !== idx) })}>Remover</button>
      </div>)}
      <button type="button" className="ds-button" onClick={() => setProfile({ ...profile, custom_dates: [...profile.custom_dates, { date: "", label: "" }] })}>+ Data</button>
    </fieldset>
  </>;
}
