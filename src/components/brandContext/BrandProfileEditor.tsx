import { useEffect, useState, type FormEvent } from "react";
import Drawer from "../Drawer";
import BrandProfileFields from "../studio/BrandProfileFields";
import { BRAND_PROFILE_SAVED, getBrandProfile, saveBrandProfile, type BrandProfile } from "../../app/studio";
import { pillarWeightTotal } from "./brandContext.helpers";

/**
 * Editar o Perfil da marca no Contexto da Marca (admin da empresa e equipe). Usa os MESMOS campos do Calendário
 * (BrandProfileFields) e o mesmo PUT /brand-profile, que valida papel e módulo no servidor. Ao salvar, avisa o
 * resto do app (Matriz, Calendário, resumo) pelo evento de perfil salvo: a IA passa a usar o perfil novo.
 */
export default function BrandProfileEditor({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [profile, setProfile] = useState<BrandProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setProfile(null); setError(null);
    getBrandProfile().then((d) => { if (alive) setProfile(d.profile); })
      .catch(() => { if (alive) setError("Não foi possível carregar o perfil da marca."); });
    return () => { alive = false; };
  }, [open]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!profile) return;
    setBusy(true); setError(null);
    try {
      const result = await saveBrandProfile(profile);
      window.dispatchEvent(new CustomEvent(BRAND_PROFILE_SAVED, { detail: result.profile }));
      onClose();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível salvar o perfil."); }
    finally { setBusy(false); }
  }

  const total = profile ? pillarWeightTotal(profile) : 100;
  return <Drawer open={open} title="Perfil da marca" description="Base para a IA escrever no jeito da marca." width="lg" onClose={() => { if (!busy) onClose(); }}>
    {profile ? <form className="studioForm" onSubmit={(e) => void submit(e)} data-testid="brand-profile-editor">
      <BrandProfileFields profile={profile} onChange={setProfile} />
      {profile.pillars.length && total !== 100 ? <p className="studioWarn" role="status">Os pesos dos pilares somam {total}%. O ideal é fechar 100%.</p> : null}
      {error ? <p role="alert" className="studioError">{error}</p> : null}
      <div className="studioActions">
        <button type="button" className="ds-button" disabled={busy} onClick={onClose}>Cancelar</button>
        <button className="ds-button is-primary" disabled={busy}>{busy ? "Salvando…" : "Salvar perfil"}</button>
      </div>
    </form> : error ? <p role="alert" className="studioError">{error}</p> : <p className="libHint" role="status">Carregando perfil…</p>}
  </Drawer>;
}
