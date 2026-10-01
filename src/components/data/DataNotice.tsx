import type { ReactNode } from "react";

type Props = {
  title: string;
  children?: ReactNode;
  tone?: "neutral" | "warning" | "negative";
  role?: "status" | "alert";
  actions?: ReactNode;
  testId?: string;
};

/** Estado da página (vazio, pendente, erro) sem cartão: régua lateral + texto. */
export default function DataNotice({ title, children, tone = "neutral", role, actions, testId }: Props) {
  const toneClass = tone === "neutral" ? "" : ` is-${tone}`;
  return (
    <div className={`ds-notice${toneClass}`} role={role} data-testid={testId}>
      <p className="ds-noticeTitle">{title}</p>
      {children ? <p className="ds-noticeText">{children}</p> : null}
      {actions ? <div className="ds-noticeActions">{actions}</div> : null}
    </div>
  );
}
