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
  /**
   * "editorial": sem topbar própria — marca e página já estão na navegação
   * principal e a página abre com a identidade do cliente. Só `right`
   * (ações utilitárias) aparece, discreto. Páginas não migradas usam "default".
   */
  variant?: "default" | "editorial";
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
  right,
  variant = "default",
  children,
}: Props) {
  if (variant === "editorial") {
    return (
      <div className={`app appShell ${themeClass || ""}`.trim()}>
        {right ? <div className="ds-utilityBar">{right}</div> : null}
        <main className="content ds-content" aria-label={title || undefined}>{children}</main>
      </div>
    );
  }

  // A marca do produto vive na sidebar global: aqui só o que é da página
  // (título opcional e controles). logoSrc/logoAlt ficam no tipo por compatibilidade.
  return (
    <div className={`app appShell ${themeClass || ""}`.trim()}>
      <header className="topbar pageTopbar">
        <div className="topbarInner">
          {title || subtitle ? (
            <div className="brand">
              <div className="brandText">
                {title ? <div className="brandTitle">{title}</div> : null}
                {subtitle ? <div className="brandSub">{subtitle}</div> : null}
              </div>
            </div>
          ) : null}

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
