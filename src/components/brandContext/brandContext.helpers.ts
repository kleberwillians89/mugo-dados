import type { BrandProfile } from "../../app/studio";

/** Soma dos pesos dos pilares; o aviso aparece quando não fecha 100% (nada é normalizado sozinho). */
export function pillarWeightTotal(profile: Pick<BrandProfile, "pillars"> | null | undefined): number {
  return (profile?.pillars || []).reduce((sum, p) => sum + (Number(p.weight) || 0), 0);
}
