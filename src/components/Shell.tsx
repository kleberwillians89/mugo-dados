// src/components/Shell.tsx
import React from "react";

type Props = {
  title: string;
  subtitle?: string;
  syncing?: boolean;
  onRefresh?: () => void;

  onAi?: () => void;
  aiLoading?: boolean;
  themeClass?: string;
  logoSrc?: string;
  logoAlt?: string;

  right?: React.ReactNode;
  children: React.ReactNode;
};

export default function Shell({
  title,
  subtitle,
  syncing,
  onRefresh,
  onAi,
  aiLoading,
  themeClass,
  logoSrc,
  logoAlt,
  right,
  children,
}: Props) {
  return (
    <div className={`app appShell ${themeClass || ""}`.trim()}>
      <header className="topbar glass">
        <div className="topbarInner">
          <div className="brand">
            <div className={`brandLogoWrap ${logoSrc ? "" : "brandLogoBadge"}`.trim()}>
              {logoSrc ? (
                <img className="brandLogoImg" src={logoSrc} alt={logoAlt || "Mugô Dados"} />
              ) : (
                <span className="brandLogoText" aria-label={logoAlt || "Mugô Dados"}>
                  Mugô Dados
                </span>
              )}
            </div>

            {title || subtitle ? (
              <div className="brandText">
                {title ? <div className="brandTitle">{title}</div> : null}
                {subtitle ? <div className="brandSub">{subtitle}</div> : null}
              </div>
            ) : null}
          </div>

          <div className="topbarRight">
            {right}

            {onAi ? (
              <button className="btn btnGold" onClick={onAi} disabled={!!aiLoading} type="button">
                {aiLoading ? "Analisando..." : "Análise IA"}
              </button>
            ) : null}

            {onRefresh ? (
              <button className="btn btnPrimary" onClick={onRefresh} disabled={!!syncing} type="button">
                {syncing ? "Atualizando..." : "Atualizar dados"}
              </button>
            ) : null}
          </div>
        </div>
      </header>

      <main className="content">{children}</main>
    </div>
  );
}
