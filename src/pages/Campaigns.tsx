import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import BrandContextPanel from "../components/studio/BrandContextPanel";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import ContentMatrix from "../components/studio/ContentMatrix";
import "../styles/studio.css";

const Calendar = lazy(() => import("./Calendar"));

export type SocialMediaTab = "matriz" | "calendario";

type SocialMediaProps = {
  /** Compatibilidade com os consumidores anteriores: controla a edição de Matriz/Criação. */
  canManage?: boolean;
  canViewSocial?: boolean;
  canViewCalendar?: boolean;
  canManageCalendar?: boolean;
  isAgency?: boolean;
  initialTab?: SocialMediaTab;
};

function sectionFromLocation(): SocialMediaTab {
  if (typeof window === "undefined") return "matriz";
  const pathname = window.location.pathname.toLowerCase();
  if (pathname.startsWith("/calendario") || pathname.startsWith("/aprovacao") || pathname.startsWith("/atendimento")) return "calendario";
  const requested = new URLSearchParams(window.location.search).get("aba") || window.location.hash.replace(/^#social-/, "");
  if (requested === "calendario" || requested === "calendar") return "calendario";
  return "matriz";
}

function allowedSection(requested: SocialMediaTab, canViewSocial: boolean, canViewCalendar: boolean): SocialMediaTab {
  if (requested === "calendario" && canViewCalendar) return requested;
  if (requested !== "calendario" && canViewSocial) return requested;
  return canViewCalendar ? "calendario" : "matriz";
}

/**
 * Social Media reúne Matriz e Calendário em seções verticais sem misturar permissões:
 * social_media.* controla a Matriz e calendar.* controla o Calendário. (O Planejador de Conteúdo saiu da tela.)
 * A Redação (editor de texto da iAgência) é uma página própria: pages/RedacaoPage.tsx.
 */
export default function Campaigns({
  canManage = true,
  canViewSocial = true,
  canViewCalendar = true,
  canManageCalendar = true,
  isAgency = false,
  initialTab,
}: SocialMediaProps) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "empresa";
  const [profileOpenRequest, setProfileOpenRequest] = useState(0);

  const openSection = useCallback((next: SocialMediaTab, updateUrl = true) => {
    const allowed = allowedSection(next, canViewSocial, canViewCalendar);
    const target = document.getElementById(`social-${allowed}`);
    target?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    if (!updateUrl || typeof window === "undefined") return;
    window.history.pushState({}, document.title, `/social-media#social-${allowed}`);
  }, [canViewCalendar, canViewSocial]);

  useEffect(() => {
    const focus = () => openSection(initialTab || sectionFromLocation(), false);
    focus();
    const onPopState = () => focus();
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [initialTab, openSection]);

  return <Shell title="Social Media" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={clientName} title="Social Media" />
    {canViewSocial ? <BrandContextPanel clientId={clientId} /> : null}
    {canViewSocial ? <section id="social-matriz" className="socialWorkspaceSection" aria-labelledby="social-matriz-title">
      <header className="socialSectionHeader"><span>01</span><div><h2 id="social-matriz-title">Matriz Tática de Conteúdo</h2><p>Planejamento editorial das próximas quatro semanas.</p></div></header>
      <ContentMatrix key={`matrix:${clientId}`} canManage={canManage} onOpenCalendar={() => openSection("calendario")}
        onOpenBrandProfile={isAgency && canManageCalendar ? () => { setProfileOpenRequest((value) => value + 1); openSection("calendario"); } : undefined} />
    </section> : null}
    {canViewCalendar ? <section id="social-calendario" className="socialWorkspaceSection" aria-labelledby="social-calendario-title">
      <header className="socialSectionHeader"><span>02</span><div><h2 id="social-calendario-title">Calendário de Postagens</h2><p>Edição, programação, aprovações e publicação no calendário existente.</p></div></header>
      <Suspense fallback={<p>Carregando calendário…</p>}><Calendar key={`calendar:${clientId}`} embedded isAgency={isAgency} canManage={canManageCalendar} openProfileRequest={profileOpenRequest} showBrandContext={false} /></Suspense>
    </section> : null}
  </div></Shell>;
}
